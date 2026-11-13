#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - COPIA «IMAGEN DE DISCO» de Windows (lo usa el agente, zerotouch_agent.py).

Para el día en que el ordenador ni arranca (disco roto, Windows estropeado): una imagen de TODO lo necesario para
arrancar (Windows, programas, ajustes y archivos de esas unidades), hecha con la herramienta que ya trae Windows
(wbadmin, la «Copia de seguridad de Windows 7»). Va a un disco USB/otro disco (E:) o a una carpeta de red (\\\\NAS\\copias).

Recuperar el equipo entero NO necesita OCTOPUS (por eso es tan útil cuando todo ha fallado):
  arrancar con un USB de instalación de Windows (gratis: herramienta de Microsoft «Media Creation Tool»)
  → Siguiente → «Reparar el equipo» → Solucionar problemas → «Recuperación de imagen del sistema» → elegir la imagen.

Antes de empezar mira si la persona está usando el ordenador a fondo (modo discreto): si es así, lo deja para luego.
Solo Windows (en Linux y Mac no hay una herramienta equivalente que venga con el sistema).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess

SYSTEM = platform.system().lower()
_RE_DESTINO = re.compile(r"^(?:[A-Za-z]:\\?|\\\\[^\\/:*?\"<>|\s][^\\/:*?\"<>|]*\\[^\\/:*?\"<>|]+(?:\\[^\\/:*?\"<>|]+)*\\?)$")
_RE_VERSION = re.compile(r"(\d{1,2}/\d{1,2}/\d{4}-\d{1,2}:\d{2})")


def _wbadmin() -> str | None:
    if SYSTEM != "windows":
        return None
    w = shutil.which("wbadmin") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wbadmin.exe")
    return w if os.path.exists(w) else None


def disponible() -> tuple[bool, str]:
    if SYSTEM != "windows":
        return False, "La imagen de disco solo se hace en Windows (con su propia herramienta)."
    if not _wbadmin():
        return False, ("Este Windows no tiene la herramienta de imágenes (wbadmin). En Windows Server: añade la "
                       "característica «Copias de seguridad de Windows Server».")
    return True, ""


def destino_valido(destino: str) -> str | None:
    """'E:' / 'E:\\' (otro disco o un USB) o '\\\\servidor\\carpeta' (red). Devuelve la forma que entiende wbadmin."""
    d = (destino or "").strip()
    if not _RE_DESTINO.match(d):
        return None
    return d[:2].upper() if re.match(r"^[A-Za-z]:", d) else d.rstrip("\\")


def _run(cmd, timeout):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace",
                              creationflags=0x08000000 if SYSTEM == "windows" else 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))


def ocupado() -> str:
    """Motivo si la persona está usando el ordenador a fondo (entonces la imagen se deja para luego)."""
    try:
        import time
        import octopus_discreto as d
        p = d._Procesador()
        p.medir(None)
        time.sleep(3)
        cpu = p.medir(None)
        enchufado, bat = d.medir_bateria()
        estado, motivo = d.decidir(cpu, d.medir_grafica(), enchufado, bat)
        return motivo if estado != "libre" else ""
    except Exception:
        return ""


def hacer(destino: str, incluir: str | None = None, mirar_si_ocupado: bool = True) -> dict:
    """Hace la imagen. incluir=None: todo lo necesario para arrancar Windows (-allCritical)."""
    ok, motivo = disponible()
    if not ok:
        return {"status": "error", "message": motivo}
    dest = destino_valido(destino)
    if not dest:
        return {"status": "error", "message": "El destino tiene que ser otra unidad (por ejemplo E:) o una carpeta de "
                                              "red (\\\\NAS\\copias)."}
    sistema = os.environ.get("SystemDrive", "C:").upper()
    if dest.upper() == sistema and not incluir:
        return {"status": "error", "message": "La imagen no puede guardarse en el mismo disco del sistema (si se "
                                              "rompe, se pierde todo a la vez). Conecta un disco USB."}
    if mirar_si_ocupado:
        m = ocupado()
        if m:
            return {"status": "pospuesta", "message": f"Se deja para luego para no molestar ({m})."}
    cmd = [_wbadmin(), "start", "backup", f"-backupTarget:{dest}", "-quiet"]
    cmd += [f"-include:{incluir}"] if incluir else ["-allCritical"]
    r = _run(cmd, timeout=12 * 3600)
    if r.returncode != 0:
        texto = (r.stdout + "\n" + r.stderr).strip()
        return {"status": "error", "message": texto[-800:] or "wbadmin falló"}
    return {"status": "success", "destino": dest, "versiones": versiones(dest)[:5]}


def versiones(destino: str) -> list[str]:
    """Las imágenes que hay en ese destino (la más nueva primero), tal como las enseña Windows (MM/DD/AAAA-HH:MM)."""
    dest = destino_valido(destino)
    if not dest or not _wbadmin():
        return []
    r = _run([_wbadmin(), "get", "versions", f"-backupTarget:{dest}"], timeout=300)
    vistas = list(dict.fromkeys(_RE_VERSION.findall(r.stdout or "")))
    return list(reversed(vistas))


COMO_RECUPERAR = [
    "Consigue un USB de instalación de Windows (gratis: en otro PC, busca «Media Creation Tool» de Microsoft).",
    "Conecta el disco donde está la imagen (o asegúrate de que el PC llega a la carpeta de red).",
    "Arranca el ordenador desde el USB (al encender, F12, F8 o Esc según la marca) → Siguiente → «Reparar el equipo».",
    "Solucionar problemas → «Recuperación de imagen del sistema» → elige la imagen más reciente → Siguiente.",
    "Al terminar, el ordenador queda como estaba el día de la imagen. Lo posterior, recupéralo con OCTOPUS.",
]
