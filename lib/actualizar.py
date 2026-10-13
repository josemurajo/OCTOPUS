#!/usr/bin/env python3
"""
OCTOPUS - Actualizar el servidor desde el panel, de forma segura.

El panel NO ejecuta nada en el equipo: solo deja una petición en /data/actualizacion/pedida. La recoge el
actualizador del equipo (actualizador.sh, cada 5 minutos), que descarga la versión de la dirección oficial y solo la
instala si viene firmada con la clave de publicación de OCTOPUS. Aquí solo se lee y escribe ese «buzón».
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

DIR = Path(os.environ.get("OCTOPUS_DATA", "/data")) / "actualizacion"


def _leer(nombre: str) -> str:
    try:
        return (DIR / nombre).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def estado() -> dict:
    vivo_txt = _leer("actualizador_vivo")
    vivo = False
    if vivo_txt:
        try:
            vivo = (time.time() - (DIR / "actualizador_vivo").stat().st_mtime) < 20 * 60
        except OSError:
            vivo = False
    try:
        resultado = json.loads(_leer("resultado.json") or "{}")
    except ValueError:
        resultado = {}
    return {"actualizador": vivo, "pedida": _leer("pedida") or None, "estado": _leer("estado"), "resultado": resultado}


def pedir(version: str, usuario: str) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "resultado.json").unlink(missing_ok=True)
    (DIR / "estado").write_text(f"Pedida por {usuario} el {datetime.now():%d/%m/%Y %H:%M}: esperando al actualizador "
                                f"del servidor (como mucho 5 minutos)...", encoding="utf-8")
    (DIR / "pedida").write_text("".join(c for c in version if c.isdigit() or c == ".")[:20], encoding="utf-8")


def cancelar() -> None:
    (DIR / "pedida").unlink(missing_ok=True)
    (DIR / "estado").write_text("Petición cancelada.", encoding="utf-8")
