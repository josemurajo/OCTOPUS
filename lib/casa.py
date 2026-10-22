# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - MODO CASA: OCTOPUS en el propio ordenador de una persona (y, si quiere, los de su familia).

La primera vez que se entra al panel se pregunta «¿Casa o empresa?» (pantalla bienvenida.html):

  Empresa  como siempre: OCTOPUS en una máquina aparte y siempre encendida; se maneja desde el navegador.
  Casa     OCTOPUS vive en ESTE ordenador. Se protege a sí mismo (un clic), guarda las copias en un disco USB o en
           otro disco (nunca en el mismo disco, que si se rompe se lleva las dos cosas), y no se nota: modo
           discreto siempre encendido (si juegas, la copia se pone en «no molestar»). Panel más sencillo.

Lo que hay aquí (el panel solo llama a estas funciones):
  aplicar_preset()        ajustes de cada modo (casa: sin doble autenticación obligatoria, sin informes por correo...)
  carpetas_personales()   Documentos, Escritorio, Imágenes, Vídeos y Música de las personas de este ordenador
  discos()                discos donde se pueden guardar las copias, con cuál es el del sistema y cuáles son USB
  mover_copias()          pasa las copias a otro disco sin perder nada y reinicia el almacén apuntando allí
  proteger_este_equipo()  da de alta este ordenador y le instala el agente (en segundo plano)

Solo en los servidores nativos (Windows y Mac). En Docker (Linux, NAS) las copias van al volumen del contenedor.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import string
import subprocess
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("OCTOPUS_DATA", "/data"))
SISTEMA = platform.system().lower()
ESTADO = DATA / "casa_estado.json"     # cómo va «proteger este equipo» y «mover las copias»
_lock = threading.Lock()


def nativo() -> bool:
    return os.environ.get("OCTOPUS_NATIVO") == "1" and SISTEMA in ("windows", "darwin")


# ------------------------------------------------------------------------------------------- ajustes de cada modo
PRESETS = {
    # en casa el panel solo se usa desde este mismo ordenador: menos pasos, nada de correos
    "casa": {"dosfa": False, "informe_mensual": False, "multiempresa": False, "buscar_equipos": False,
             "monitorizacion": False, "discreto": True, "bloqueo_atacantes": True, "senuelos": True,
             "icono_usuario": True},
    "empresa": {"dosfa": True, "discreto": True},
}


def aplicar_preset(modo: str, cm, usuario_id=None) -> None:
    for clave, valor in PRESETS.get(modo, {}).items():
        cm.set_config(clave, valor, usuario_id)
    cm.set_config("modo_uso", modo, usuario_id)


# ------------------------------------------------------------------------------------------- qué copiar
NOMBRES_CARPETAS = {
    "windows": ["Documents", "Desktop", "Pictures", "Videos", "Music",
                "OneDrive/Documents", "OneDrive/Documentos", "OneDrive/Desktop", "OneDrive/Escritorio",
                "OneDrive/Pictures", "OneDrive/Imágenes"],
    "darwin": ["Documents", "Desktop", "Pictures", "Movies", "Music"],
    "linux": ["Documentos", "Documents", "Escritorio", "Desktop", "Imágenes", "Pictures", "Vídeos", "Videos",
              "Música", "Music"],
}
_NO_PERSONAS = {"public", "default", "default user", "all users", "shared", "guest", "wdagutilityaccount"}


def carpetas_personales(raiz: str | None = None) -> list[str]:
    """Las carpetas importantes de cada persona de este ordenador (OCTOPUS corre como sistema, no como la persona)."""
    if raiz is None:
        raiz = (os.environ.get("SystemDrive", "C:") + "\\Users") if SISTEMA == "windows" else \
               "/Users" if SISTEMA == "darwin" else "/home"
    encontradas: list[str] = []
    try:
        personas = sorted(p for p in Path(raiz).iterdir() if p.is_dir())
    except OSError:
        return []
    for p in personas:
        n = p.name.lower()
        if n in _NO_PERSONAS or n.startswith(("defaultuser", ".", "_")):
            continue
        for sub in NOMBRES_CARPETAS.get(SISTEMA, NOMBRES_CARPETAS["linux"]):
            c = p / sub
            try:
                if c.is_dir() and not c.is_symlink() and str(c) not in encontradas:
                    encontradas.append(str(c))
            except OSError:
                pass
    return encontradas


# ------------------------------------------------------------------------------------------- dónde guardarlas
def _gb(n) -> float:
    try:
        return round(float(n) / 1024 ** 3, 1)
    except (TypeError, ValueError):
        return 0.0


def discos() -> list[dict]:
    """[{ruta, nombre, libre_gb, total_gb, externo, sistema, actual}] - el del sistema marcado (no sirve para copias)."""
    lista: list[dict] = []
    if SISTEMA == "windows":
        ps = ("$s=$env:SystemDrive[0]; $sd=(Get-Partition -DriveLetter $s -ErrorAction SilentlyContinue).DiskNumber;"
              "Get-Partition | Where-Object DriveLetter | ForEach-Object { $d=Get-Disk -Number $_.DiskNumber;"
              "$v=Get-Volume -DriveLetter $_.DriveLetter -ErrorAction SilentlyContinue;"
              "if ($v) { [pscustomobject]@{letra=[string]$_.DriveLetter; disco=$_.DiskNumber; sd=$sd;"
              "bus=[string]$d.BusType; nombre=$v.FileSystemLabel; libre=$v.SizeRemaining; total=$v.Size } } }"
              "| ConvertTo-Json -Compress")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                               timeout=60, creationflags=0x08000000)
            datos = json.loads(r.stdout or "[]")
            datos = datos if isinstance(datos, list) else [datos]
        except Exception:
            datos = []
        for d in datos:
            letra = str(d.get("letra") or "").strip()
            if not letra:
                continue
            lista.append({"ruta": f"{letra}:\\", "nombre": d.get("nombre") or f"Disco {letra}:",
                          "libre_gb": _gb(d.get("libre")), "total_gb": _gb(d.get("total")),
                          "externo": str(d.get("bus")).upper() in ("USB", "SD", "MMC", "1394"),
                          "sistema": d.get("disco") == d.get("sd")})
        if not lista:   # sin PowerShell de almacenamiento: al menos las letras
            for letra in string.ascii_uppercase:
                raiz = f"{letra}:\\"
                if os.path.exists(raiz):
                    u = shutil.disk_usage(raiz)
                    lista.append({"ruta": raiz, "nombre": f"Disco {letra}:", "libre_gb": _gb(u.free),
                                  "total_gb": _gb(u.total), "externo": False,
                                  "sistema": raiz[0].upper() == os.environ.get("SystemDrive", "C:")[0].upper()})
    else:
        raiz_dev = os.stat("/").st_dev
        base = Path("/Volumes") if SISTEMA == "darwin" else Path("/media")
        candidatos = []
        for b in ([base] if SISTEMA == "darwin" else [Path("/media"), Path("/mnt"), Path("/run/media")]):
            try:
                for p in b.iterdir():
                    candidatos.extend([p] if SISTEMA == "darwin" or os.path.ismount(p) else
                                      [q for q in p.iterdir() if os.path.ismount(q)] if p.is_dir() else [])
            except OSError:
                pass
        lista.append({"ruta": "/", "nombre": "Disco del sistema", "libre_gb": _gb(shutil.disk_usage("/").free),
                      "total_gb": _gb(shutil.disk_usage("/").total), "externo": False, "sistema": True})
        for p in candidatos:
            try:
                st = os.stat(p)
                if st.st_dev == raiz_dev:
                    continue
                u = shutil.disk_usage(p)
                externo = True
                if SISTEMA == "darwin":
                    info = subprocess.run(["diskutil", "info", str(p)], capture_output=True, text=True, timeout=20).stdout
                    externo = "External" in info or "Removable" in info or "Externo" in info
                lista.append({"ruta": str(p), "nombre": p.name, "libre_gb": _gb(u.free), "total_gb": _gb(u.total),
                              "externo": externo, "sistema": False})
            except OSError:
                pass
    actual = str(boveda_actual())
    for d in lista:
        d["actual"] = actual.lower().startswith(d["ruta"].lower()) and (d["ruta"] != "/" or not any(
            x["ruta"] != "/" and actual.startswith(x["ruta"]) for x in lista))
    lista.sort(key=lambda d: (d["sistema"], not d["externo"], -d["libre_gb"]))
    return lista


def boveda_actual() -> Path:
    try:
        elegida = (DATA / "boveda_ruta.txt").read_text(encoding="utf-8").strip()
    except OSError:
        elegida = ""
    return Path(elegida) if elegida else Path(os.environ.get("OCTOPUS_BOVEDA_DIR", "/boveda"))


def uso_copias() -> float:
    """GB que ocupan ahora las copias."""
    total = 0
    for raiz, _dirs, archivos in os.walk(boveda_actual()):
        for a in archivos:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
    return _gb(total)


# ------------------------------------------------------------------------------------------- estado en disco
def estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar(**cambios) -> None:
    with _lock:
        e = estado()
        e.update(cambios)
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            ESTADO.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


# ------------------------------------------------------------------------------------------- mover las copias
def mover_copias(destino_disco: str, env_file: Path | None = None) -> None:
    """Copia todo el almacén a <disco>/OCTOPUS-copias, lo comprueba y reinicia el almacén apuntando allí.
    Las copias viejas NO se borran (se dice dónde están, por si acaso)."""
    origen = boveda_actual()
    destino = Path(destino_disco) / "OCTOPUS-copias"

    def trabajo():
        _guardar(mover={"fase": "copiando", "destino": str(destino), "desde": str(origen), "t": time.time()})
        try:
            destino.mkdir(parents=True, exist_ok=True)
            if origen.exists() and origen.resolve() != destino.resolve():
                shutil.copytree(origen, destino, dirs_exist_ok=True)
            n_origen = sum(len(f) for _r, _d, f in os.walk(origen)) if origen.exists() else 0
            n_destino = sum(len(f) for _r, _d, f in os.walk(destino))
            if n_destino < n_origen:
                raise OSError(f"faltan archivos en el destino ({n_destino} de {n_origen})")
            (DATA / "boveda_ruta.txt").write_text(str(destino), encoding="utf-8")
            if env_file and env_file.is_file():   # para que la recuperación del servidor y la consola lo sepan
                lineas = [l for l in env_file.read_text(encoding="utf-8").splitlines()
                          if not l.startswith("OCTOPUS_BOVEDA_DIR=")]
                env_file.write_text("\n".join(lineas + [f"OCTOPUS_BOVEDA_DIR={destino}"]) + "\n", encoding="utf-8")
            (DATA / "reiniciar_servicios").write_text(str(time.time() + 3), encoding="utf-8")
            _guardar(mover={"fase": "hecho", "destino": str(destino), "desde": str(origen), "t": time.time()})
        except Exception as exc:
            _guardar(mover={"fase": "error", "destino": str(destino), "error": str(exc)[:300], "t": time.time()})
    threading.Thread(target=trabajo, daemon=True).start()


# ------------------------------------------------------------------------------------------- proteger este equipo
def proteger_este_equipo(paquete_zip: bytes, nombre: str) -> None:
    """Instala el agente en ESTE ordenador con el instalador normal del panel (en segundo plano)."""
    carpeta = DATA / "casa_instalador"

    def trabajo():
        _guardar(proteger={"fase": "instalando", "equipo": nombre, "t": time.time()})
        try:
            import zipfile
            import io
            shutil.rmtree(carpeta, ignore_errors=True)
            carpeta.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(paquete_zip)) as z:
                z.extractall(carpeta)
            if SISTEMA == "windows":
                cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                       str(carpeta / "instalar_windows.ps1")]
                kw = {"creationflags": 0x08000000}
            else:
                cmd = ["bash", str(carpeta / "INSTALAR.command"), "--sin-preguntas"]
                kw = {}
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=str(carpeta), **kw)
            (DATA / "logs").mkdir(parents=True, exist_ok=True)
            (DATA / "logs" / "casa_instalacion.log").write_text((r.stdout or "") + "\n" + (r.stderr or ""),
                                                                encoding="utf-8", errors="replace")
            if r.returncode != 0:
                raise RuntimeError(f"el instalador terminó con código {r.returncode}")
            _guardar(proteger={"fase": "hecho", "equipo": nombre, "t": time.time()})
        except Exception as exc:
            _guardar(proteger={"fase": "error", "equipo": nombre, "error": str(exc)[:300], "t": time.time()})
    threading.Thread(target=trabajo, daemon=True).start()


def nombre_este_equipo() -> str:
    return (socket.gethostname() or "Mi-ordenador").split(".")[0][:60]
