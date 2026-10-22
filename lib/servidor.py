#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS Zero-Touch - Arranque del servidor dentro del contenedor (punto de entrada de la imagen).

Pone en marcha y vigila (si uno se cae, se vuelve a arrancar):
  - el almacen de copias (restic rest-server, HTTPS, modo solo-anadir) en el puerto 8000
  - el panel web HTTPS (gunicorn) en el 8080, por donde los agentes recogen sus ordenes
  - el mantenimiento nocturno (limpieza, verificacion, copia del servidor, vigilancia)
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
DATA = Path(os.environ.get("OCTOPUS_DATA", "/data"))
BOVEDA = Path(os.environ.get("OCTOPUS_BOVEDA_DIR", "/boveda"))
HTPASSWD = DATA / "boveda.htpasswd"
_parar = threading.Event()
_procesos: dict[str, subprocess.Popen] = {}
_inicios: dict[str, float] = {}


def programa(nombre: str) -> str:
    """Ruta de restic / rest-server: la carpeta bin de la instalacion (Windows y Mac sin Docker) o el PATH."""
    for carpeta in (os.environ.get("OCTOPUS_BIN"), str(BASE_DIR / "bin")):
        if carpeta:
            for n in (nombre + ".exe", nombre) if os.name == "nt" else (nombre,):
                if (Path(carpeta) / n).is_file():
                    return str(Path(carpeta) / n)
    return shutil.which(nombre) or nombre


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [octopus] {msg}", flush=True)


def preparar_carpetas() -> None:
    for d in ("panel", "ssh", "logs", "ansible", "sandbox"):
        (DATA / d).mkdir(parents=True, exist_ok=True)
    for d in (DATA, DATA / "ssh"):
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    BOVEDA.mkdir(parents=True, exist_ok=True)


def actualizar_ip() -> None:
    """La IP la decide el instalador del equipo anfitrion (OCTOPUS_IP); si cambia, se actualiza
    (y se emite un certificado nuevo con la misma autoridad: los equipos siguen confiando)."""
    import configuracion
    ip = os.environ.get("OCTOPUS_IP", "").strip()
    cambios = False
    for clave in ("OCTOPUS_IP", "OCTOPUS_PUBLIC_HOST"):
        valor = os.environ.get(clave, "").strip()
        if valor and configuracion.leer_env().get(clave) != valor:
            configuracion.fijar(clave, valor)
            cambios = True
    if cambios or os.environ.get("OCTOPUS_NOMBRES_EXTRA"):
        configuracion.certificado_tls()   # solo emite otro si cambian los nombres
        configuracion.config_agentes()
    log(f"Los equipos llegan a este servidor por: {configuracion.leer_env().get('OCTOPUS_PUBLIC_HOST') or ip or '(sin fijar)'}")


def _comando_panel(py: str) -> list[str]:
    """gunicorn en Linux/Mac; en Windows (sin gunicorn) cheroot, que tambien es de produccion y lleva HTTPS."""
    if shutil.which("gunicorn") and os.name != "nt":
        return ["gunicorn", "-c", str(BASE_DIR / "install" / "gunicorn_panel.py"), "admin_panel:app"]
    try:
        import cheroot  # noqa: F401
        return [py, str(BASE_DIR / "lib" / "panel_cheroot.py")]
    except ImportError:
        return [py, str(BASE_DIR / "lib" / "admin_panel.py")]


RUTA_ELEGIDA = DATA / "boveda_ruta.txt"          # la escribe el panel al elegir otro disco (modo casa)
DESCONECTADA = DATA / "boveda_desconectada"       # el panel avisa «conecta tu disco de copias» mientras exista


def boveda_actual() -> Path:
    """Dónde se guardan las copias: la carpeta elegida en el panel (un disco USB, otro disco...) o la de instalación.
    Si el disco elegido no está conectado, se apunta para que el panel lo diga claro."""
    try:
        elegida = RUTA_ELEGIDA.read_text(encoding="utf-8").strip()
    except OSError:
        elegida = ""
    if not elegida:
        DESCONECTADA.unlink(missing_ok=True)
        return BOVEDA
    ruta = Path(elegida)
    if ruta.anchor and not Path(ruta.anchor).exists() or not ruta.parent.exists():
        try:
            DESCONECTADA.write_text(elegida, encoding="utf-8")
        except OSError:
            pass
        log(f"El disco de las copias no está conectado ({elegida}): las copias esperan a que se conecte")
    else:
        DESCONECTADA.unlink(missing_ok=True)
    # el panel y el mantenimiento leen el almacén directamente del disco: que miren en el disco nuevo
    os.environ["OCTOPUS_BOVEDA_DIR"] = str(ruta)
    return ruta


def comandos() -> dict[str, list[str]]:
    py = sys.executable
    return {
        "almacen": [programa("rest-server"), "--path", str(boveda_actual()), "--listen", ":8000", "--append-only",
                    "--htpasswd-file", str(HTPASSWD), "--tls",
                    "--tls-cert", str(BASE_DIR / "data" / "tls" / "panel.crt"),
                    "--tls-key", str(BASE_DIR / "data" / "tls" / "panel.key")],
        "panel": _comando_panel(py),
    }


def arrancar(nombre: str, cmd: list[str]) -> None:
    env = dict(os.environ, PYTHONUNBUFFERED="1", API_BIND="127.0.0.1")
    _procesos[nombre] = subprocess.Popen(cmd, cwd=str(BASE_DIR), env=env)
    _inicios[nombre] = time.time()
    log(f"{nombre} en marcha (pid {_procesos[nombre].pid})")


def esperar_almacen(segundos: int = 60) -> bool:
    import ssl
    import urllib.request
    import urllib.error
    ctx = ssl.create_default_context(cafile=str(BASE_DIR / "data" / "tls" / "ca.crt"))
    fin = time.time() + segundos
    while time.time() < fin:
        try:
            urllib.request.urlopen("https://127.0.0.1:8000/", timeout=2, context=ctx)
            return True
        except urllib.error.HTTPError:
            return True  # 401/404: responde
        except Exception:
            time.sleep(1)
    return False


def iniciar_repositorios() -> None:
    import configuracion
    env = configuracion.leer_env()
    for repo, clave in ((env.get("RESTIC_REPOSITORY"), env.get("RESTIC_PASSWORD")),
                        (env.get("RESTIC_REPOSITORY_CUARENTENA"), env.get("RESTIC_PASSWORD_CUARENTENA"))):
        if not repo or not clave:
            continue
        e = dict(os.environ, RESTIC_REPOSITORY=repo, RESTIC_PASSWORD=clave,
                 RESTIC_CACERT=env.get("RESTIC_CACERT", ""), RESTIC_CACHE_DIR=str(DATA / ".cache" / "restic"))
        if subprocess.run([programa("restic"), "cat", "config"], env=e, capture_output=True, timeout=120).returncode != 0:
            r = subprocess.run([programa("restic"), "init"], env=e, capture_output=True, text=True, timeout=300)
            nombre = repo.rsplit("/", 1)[-1]
            log(f"Repositorio {nombre}: {'creado' if r.returncode == 0 else 'ERROR ' + r.stderr.strip()[-200:]}")


def imagen_sandbox() -> None:
    """La sala de analisis usa contenedores aparte (sin red ni permisos). Necesita el Docker del anfitrion."""
    if not Path("/var/run/docker.sock").exists() or not shutil.which("docker"):
        log("Sala de analisis: sin acceso a Docker, se usara el analisis basico")
        return
    if subprocess.run(["docker", "image", "inspect", "octopus-sandbox:1"], capture_output=True).returncode == 0:
        return
    r = subprocess.run(["docker", "build", "-q", "-t", "octopus-sandbox:1", str(BASE_DIR / "install" / "sandbox")],
                       capture_output=True, text=True, timeout=1800)
    log("Imagen de la sala de analisis " + ("lista" if r.returncode == 0 else "no disponible: " + r.stderr[-200:]))


def mantenimiento_nocturno() -> None:
    hora, minuto = (os.environ.get("MANTENIMIENTO_HORA", "03:30").split(":") + ["0"])[:2]
    while not _parar.is_set():
        ahora = datetime.now()
        prox = ahora.replace(hour=int(hora), minute=int(minuto), second=0, microsecond=0)
        if prox <= ahora:
            prox += timedelta(days=1)
        if _parar.wait((prox - ahora).total_seconds()):
            return
        log("Mantenimiento nocturno...")
        with open(DATA / "logs" / "mantenimiento.log", "a", encoding="utf-8") as fh:
            subprocess.run([sys.executable, str(BASE_DIR / "lib" / "mantenimiento.py"), "todo"],
                           cwd=str(BASE_DIR), stdout=fh, stderr=subprocess.STDOUT)


def terminar(*_):
    _parar.set()


def mostrar_acceso_en_registro(cred: Path) -> None:
    """En un NAS (Synology, QNAP, Unraid, Portainer...) no hay terminal a mano: la forma facil de ver la
    contrasena inicial es el "Registro" del contenedor en la propia web del NAS. Solo se hace si el archivo
    de instalacion lo pide (OCTOPUS_MOSTRAR_ACCESO=1) y mientras nadie haya entrado aun: es de un solo uso
    y el panel obliga a cambiarla nada mas entrar (entonces borra el archivo y deja de salir)."""
    if os.environ.get("OCTOPUS_MOSTRAR_ACCESO", "").strip().lower() not in ("1", "si", "sí", "true", "yes"):
        return
    try:
        texto = cred.read_text(encoding="utf-8").strip()
    except OSError:
        return
    raya = "=" * 64
    log(raya)
    log("PRIMER ACCESO A OCTOPUS (sale aqui solo hasta que entres la primera vez)")
    for linea in texto.splitlines():
        if linea.strip():
            log("   " + linea.strip())
    log(raya)


def main() -> int:
    signal.signal(signal.SIGTERM, terminar)
    signal.signal(signal.SIGINT, terminar)
    preparar_carpetas()
    import configuracion
    configuracion.preparar(HTPASSWD)
    actualizar_ip()
    cmds = comandos()
    arrancar("almacen", cmds["almacen"])
    if not esperar_almacen():
        log("AVISO: el almacen de copias no responde")
    iniciar_repositorios()
    arrancar("panel", cmds["panel"])
    threading.Thread(target=mantenimiento_nocturno, daemon=True).start()
    threading.Thread(target=imagen_sandbox, daemon=True).start()
    cred = BASE_DIR / "data" / "CREDENCIALES_INICIALES.txt"
    if cred.is_file():
        log(f"Acceso inicial: ver {cred}" + ("" if os.environ.get("OCTOPUS_NATIVO")
                                               else " (docker exec octopus cat /data/panel/CREDENCIALES_INICIALES.txt)"))
        mostrar_acceso_en_registro(cred)
    espera: dict[str, float] = {}
    flag = DATA / "reiniciar_servicios"   # lo pone el panel tras renovar el certificado (boton Solucionar)
    while not _parar.wait(2):
        try:
            if flag.exists() and time.time() >= float(flag.read_text(encoding="utf-8").strip() or 0):
                flag.unlink(missing_ok=True)
                log("Reiniciando el panel y el almacen (certificado nuevo u otro disco para las copias)")
                for nombre in ("almacen", "panel"):
                    if nombre in _procesos and _procesos[nombre].poll() is None:
                        _procesos[nombre].terminate()
        except (OSError, ValueError):
            flag.unlink(missing_ok=True)
        for nombre, p in list(_procesos.items()):
            if p.poll() is not None:
                retraso = min(espera.get(nombre, 1) * 2, 60)
                espera[nombre] = retraso
                log(f"{nombre} se ha parado (codigo {p.returncode}); se reinicia en {retraso:.0f} s")
                time.sleep(retraso)
                arrancar(nombre, comandos()[nombre])   # se recalcula: puede haber cambiado el disco de las copias
            elif nombre in espera and time.time() - _inicios.get(nombre, 0) > 300:
                espera.pop(nombre, None)  # lleva 5 min estable: la proxima caida se reintenta rapido
    log("Parando OCTOPUS...")
    for p in _procesos.values():
        p.terminate()
    for p in _procesos.values():
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            p.kill()
    log("OCTOPUS parado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
