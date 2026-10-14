#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Banderines: registro de pasos de cada proceso (copias, recuperaciones, mantenimiento, avisos...).

Cada paso queda apuntado con la hora, el proceso, el equipo (si es de un equipo) y, si algo falla, el codigo
del fallo (ver avisos.py). Sirve para saber siempre hasta donde llego algo y por que se paro, para la ficha
de cada equipo ("Ultimos pasos") y para el diagnostico que se puede descargar desde el panel.

Se guarda en /data/banderines/<proceso>.jsonl (una linea JSON por paso; se recorta solo para no crecer).
Nunca se apuntan contrasenas ni claves: el texto pasa por limpiar() antes de guardarse.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

DIR = Path(os.environ.get("OCTOPUS_BANDERINES_DIR") or (Path(os.environ.get("OCTOPUS_DATA", "/data")) / "banderines"))
MAX_LINEAS = 3000
_lock = threading.Lock()

# lo que parezca un secreto se tapa: clave=valor, tokens largos, contrasenas en URLs
_SECRETOS = [
    (re.compile(r"(?i)\b(pass(word)?|contrase\w*|clave|token|secret\w*|api[_-]?key|key)\s*[=:]\s*\S+"), r"\1=***"),
    (re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+@"), r"\1***@"),
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "***"),
]


def limpiar(texto: str) -> str:
    t = str(texto or "")
    for patron, sust in _SECRETOS:
        t = patron.sub(sust, t)
    return t[:1000]


def marcar(proceso: str, texto: str, equipo: str | None = None, codigo: str | None = None,
           nivel: str = "info") -> None:
    """Apunta un paso. nivel: info / ok / aviso / error."""
    linea = {"t": datetime.now().astimezone().isoformat(timespec="seconds"), "proceso": proceso,
             "nivel": nivel, "texto": limpiar(texto)}
    if equipo:
        linea["equipo"] = equipo
    if codigo:
        linea["codigo"] = codigo
    try:
        with _lock:
            DIR.mkdir(parents=True, exist_ok=True)
            f = DIR / f"{re.sub(r'[^a-z0-9_-]', '_', proceso.lower())}.jsonl"
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(linea, ensure_ascii=False) + "\n")
            if f.stat().st_size > MAX_LINEAS * 400:
                lineas = f.read_text(encoding="utf-8").splitlines()[-MAX_LINEAS:]
                f.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    except OSError:
        pass  # apuntar un banderin nunca debe romper lo que se esta haciendo


def leer(proceso: str | None = None, equipo: str | None = None, limite: int = 50) -> list[dict]:
    """Ultimos pasos (los mas recientes primero), de un proceso y/o de un equipo."""
    archivos = [DIR / f"{proceso}.jsonl"] if proceso else sorted(DIR.glob("*.jsonl"))
    pasos = []
    for f in archivos:
        try:
            for l in f.read_text(encoding="utf-8").splitlines()[-MAX_LINEAS:]:
                try:
                    d = json.loads(l)
                except ValueError:
                    continue
                if equipo and (d.get("equipo") or "").lower() != equipo.lower():
                    continue
                pasos.append(d)
        except OSError:
            continue
    pasos.sort(key=lambda d: d.get("t", ""), reverse=True)
    return pasos[:limite]


def archivos() -> list[Path]:
    try:
        return sorted(DIR.glob("*.jsonl"))
    except OSError:
        return []
