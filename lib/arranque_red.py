#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - encender y apagar el ARRANQUE POR RED desde el panel (Equipos → Arranque por red).

Lo que hace el trabajo es un contenedor aparte (install/pxe), con la red del anfitrión: el servidor de OCTOPUS solo
lo construye, lo arranca, lo para y enseña cómo va. Se usa el Docker del anfitrión (el mismo que la sala de análisis).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
NOMBRE = "octopus-pxe"
IMAGEN = "octopus-pxe:1"
VOLUMEN = "octopus_pxe"
_trabajo = {"haciendo": "", "error": ""}


def _docker(*args, timeout=60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(args, 1, "", str(exc))


def se_puede() -> tuple[bool, str]:
    if not (Path("/var/run/docker.sock").exists() and shutil.which("docker")):
        return False, ("El servidor no puede usar Docker del ordenador (falta /var/run/docker.sock en "
                       "install/docker-compose.yml).")
    if not os.environ.get("OCTOPUS_IP"):
        return False, "Falta la dirección del servidor (OCTOPUS_IP en install/.env). Vuelve a pasar el instalador."
    return True, ""


def estado() -> dict:
    r = _docker("inspect", "-f", "{{.State.Running}}", NOMBRE, timeout=15)
    encendido = r.returncode == 0 and r.stdout.strip() == "true"
    registro = _docker("logs", "--tail", "15", NOMBRE, timeout=15) if r.returncode == 0 else None
    lineas = ((registro.stdout + registro.stderr) if registro else "").strip().splitlines()[-15:]
    return {"encendido": encendido, "existe": r.returncode == 0, "haciendo": _trabajo["haciendo"],
            "error": _trabajo["error"], "registro": lineas, "ip": os.environ.get("OCTOPUS_IP", ""),
            "listo": any("Listo en la red" in x for x in lineas)}


def _encender():
    try:
        _trabajo.update(haciendo="Preparando (la primera vez tarda unos minutos)...", error="")
        b = _docker("build", "-q", "-t", IMAGEN, str(BASE_DIR / "install" / "pxe"), timeout=900)
        if b.returncode != 0:
            raise RuntimeError(f"No se pudo preparar: {(b.stderr or b.stdout).strip()[-400:]}")
        _docker("rm", "-f", NOMBRE)
        r = _docker("run", "-d", "--name", NOMBRE, "--restart", "unless-stopped", "--network", "host",
                    "--cap-add", "NET_ADMIN", "--cap-add", "NET_RAW", "--cap-add", "NET_BIND_SERVICE",
                    "-e", f"OCTOPUS_IP={os.environ.get('OCTOPUS_IP', '')}",
                    "-e", f"OCTOPUS_PUERTO_PANEL={os.environ.get('OCTOPUS_PUERTO_PANEL', '8080')}",
                    "-e", f"OCTOPUS_PXE_HTTP={os.environ.get('OCTOPUS_PXE_HTTP', '8090')}",
                    *(["-e", f"OCTOPUS_RESCATE_ISO={os.environ['OCTOPUS_RESCATE_ISO']}"]
                      if os.environ.get("OCTOPUS_RESCATE_ISO") else []),
                    "-v", f"{VOLUMEN}:/srv/octopus-pxe", IMAGEN, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"No arranca: {(r.stderr or r.stdout).strip()[-400:]}")
    except Exception as exc:
        _trabajo["error"] = str(exc)
    finally:
        _trabajo["haciendo"] = ""


def encender() -> None:
    if not _trabajo["haciendo"]:
        threading.Thread(target=_encender, daemon=True).start()


def apagar() -> None:
    _docker("rm", "-f", NOMBRE, timeout=60)
    _trabajo["error"] = ""
