# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS Zero-Touch - Alta de equipos desde el panel.

Para cada equipo nuevo se crea:
  * su clave propia (si roban una, solo sirve para ese equipo; cada descarga genera una nueva),
  * la configuracion del agente (servidor, autoridad de certificados de OCTOPUS, almacen, carpetas),
  * un paquete .zip con todo lo necesario y un instalador de doble clic (Windows), .command (Mac) o script (Linux).
El agente se conecta el al servidor por HTTPS: no hace falta abrir puertos en el equipo.

El paquete contiene claves: se descarga solo por HTTPS, solo administradores, y queda registrado.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = Path(os.environ.get("OCTOPUS_ANSIBLE_DIR") or (BASE_DIR / "ansible"))
INSTALADORES = BASE_DIR / "agentes" / "instaladores"
CEREBRO_TUNEL = "10.8.0.1"

RUTAS_POR_DEFECTO = {"windows": ["C:\\Users"], "linux": ["/home"], "macos": ["/Users"]}
NOMBRE_VALIDO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


def nombre_valido(nombre: str) -> bool:
    """El nombre debe ser el nombre real del equipo (hostname): con el se identifican sus copias."""
    return bool(NOMBRE_VALIDO.match(nombre or ""))


def limpiar_rutas(texto: str, so: str) -> list[str]:
    rutas = []
    for linea in re.split(r"[\r\n;]+", texto or ""):
        r = linea.strip().strip('"').strip("'")
        if not r:
            continue
        if so == "windows":
            if not re.match(r"^[A-Za-z]:\\", r):
                raise ValueError(f"«{r}» no es una carpeta de Windows (ejemplo: C:\\Users\\ana\\Documents)")
        elif not r.startswith("/"):
            raise ValueError(f"«{r}» no es una carpeta de Linux (ejemplo: /home/ana)")
        rutas.append(r)
    return rutas or list(RUTAS_POR_DEFECTO.get(so, ["/home"]))


def _env() -> dict:
    env = {}
    f = BASE_DIR / ".env"
    if f.is_file():
        for raw in f.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def config_agente(nombre: str, rutas: list[str], token: str) -> dict:
    """Configuracion del agente: la base comun del servidor + el nombre, las carpetas y la clave del equipo."""
    base_file = ANSIBLE_DIR / "config.json"
    if not base_file.is_file():
        raise RuntimeError("Falta la configuracion base de los agentes: arranca antes el servidor")
    cfg = json.loads(base_file.read_text(encoding="utf-8"))
    if not cfg.get("servidor"):
        raise RuntimeError("El servidor no sabe su direccion (OCTOPUS_IP): vuelve a ejecutar el instalador")
    cfg.update({"hostname": nombre, "backup_paths": rutas, "agent_token": token, "bind_addresses": ["127.0.0.1"]})
    return cfg


def paquete(nombre: str, so: str, rutas: list[str], token: str) -> bytes:
    """Zip con el agente, su configuracion y el instalador para ese sistema."""
    cfg = config_agente(nombre, rutas, token)
    agente = (BASE_DIR / "agentes" / "zerotouch_agent.py").read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("zerotouch_agent.py", agente)
        z.writestr("octopus_monitor.py", (BASE_DIR / "agentes" / "octopus_monitor.py").read_bytes())
        z.writestr("octopus_vms.py", (BASE_DIR / "agentes" / "octopus_vms.py").read_bytes())
        z.writestr("config.json", json.dumps(cfg, indent=2, ensure_ascii=False))
        if so == "windows":
            for f in ("INSTALAR.bat", "instalar_windows.ps1", "DESINSTALAR.bat"):
                z.writestr(f, (INSTALADORES / f).read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n"))
            leeme = LEEME_WINDOWS
        elif so == "macos":
            info = zipfile.ZipInfo("INSTALAR.command")
            info.external_attr = 0o755 << 16
            z.writestr(info, (INSTALADORES / "instalar_mac.sh").read_text(encoding="utf-8"))
            leeme = LEEME_MAC
        else:
            info = zipfile.ZipInfo("instalar_linux.sh")
            info.external_attr = 0o755 << 16
            z.writestr(info, (INSTALADORES / "instalar_linux.sh").read_text(encoding="utf-8"))
            leeme = LEEME_LINUX
        z.writestr("LEEME.txt", leeme.format(nombre=nombre, rutas="\n".join("  - " + r for r in rutas),
                                              servidor=cfg["servidor"]))
    return buf.getvalue()


LEEME_WINDOWS = """OCTOPUS Zero-Touch - Instalador del equipo {nombre}

1. Copia esta carpeta al equipo {nombre} (descomprimida).
2. Haz clic derecho en INSTALAR.bat -> "Ejecutar como administrador".
3. Espera al mensaje "OCTOPUS instalado". En el panel el equipo pasara a "Protegido" en 1-2 minutos.

Carpetas que se protegen:
{rutas}
Servidor: {servidor} (conexion cifrada; el equipo no necesita puertos abiertos)

Este paquete contiene claves. Cuando termine la instalacion, BORRA esta carpeta y el .zip.
"""

LEEME_LINUX = """OCTOPUS Zero-Touch - Instalador del equipo {nombre}

1. Copia el .zip al equipo {nombre} y descomprimelo:   unzip octopus-{nombre}.zip -d octopus
2. Ejecuta:   sudo bash octopus/instalar_linux.sh
3. En el panel el equipo pasara a "Protegido" en 1-2 minutos.

Carpetas que se protegen:
{rutas}
Servidor: {servidor} (conexion cifrada; el equipo no necesita puertos abiertos)

Este paquete contiene claves. Cuando termine la instalacion, BORRA la carpeta y el .zip.
"""

LEEME_MAC = """OCTOPUS Zero-Touch - Instalador del equipo {nombre}

1. Copia el .zip al Mac {nombre} y abrelo (se descomprime solo).
2. Haz clic derecho en INSTALAR.command -> Abrir (la primera vez macOS pide confirmacion) y escribe
   la contrasena de administrador cuando la pida.
3. Para proteger documentos, Escritorio y Descargas, macOS pide dar "Acceso total al disco" al agente:
   el instalador abre la ventana de Ajustes y explica que hay que activar.

Carpetas que se protegen:
{rutas}
Servidor: {servidor} (conexion cifrada; el equipo no necesita puertos abiertos)

Este paquete contiene claves. Cuando termine la instalacion, BORRA la carpeta y el .zip.
"""
