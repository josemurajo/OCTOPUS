#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
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


# ---------------------------------------------------------------- actualización automática
# El mantenimiento de cada noche la pide sola si hay versión nueva y no está en pausa. Si una versión falla al
# instalarse, se reintenta como mucho 3 veces y con 2 días entre intentos (para no reiniciar el panel cada noche).
INTENTOS_FILE = DIR / "intentos_automaticos.json"
MAX_INTENTOS = 3
ENTRE_INTENTOS = 2 * 86400 - 3600


def _intentos() -> dict:
    try:
        return json.loads(INTENTOS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def automatica_atascada(version: str) -> bool:
    """True si esa versión ya se intentó instalar sola todas las veces y falló (hace falta mirarlo a mano)."""
    i = _intentos().get(version) or {}
    r = estado()["resultado"]
    return i.get("veces", 0) >= MAX_INTENTOS and not r.get("ok", False)


def la_hara_sola(act: dict, activada: bool) -> bool:
    """True si la versión nueva se va a instalar sola esta noche (para no avisar en el panel de algo que se arregla solo)."""
    return bool(activada and act.get("hay_nueva") and estado()["actualizador"]
                and not automatica_atascada(act.get("remota", "")))


def usuario_ocupado() -> bool:
    """En modo casa: ¿está alguien jugando o usando el ordenador a fondo ahora mismo? (entonces no se actualiza)."""
    try:
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parent.parent / "agentes"))
        import octopus_discreto as d
        p = d._Procesador()
        p.medir(None)
        time.sleep(3)
        cpu = p.medir(None)
        enchufado, bat = d.medir_bateria()
        return d.decidir(cpu, d.medir_grafica(), enchufado, bat)[0] != "libre"
    except Exception:
        return False


def pedir_automatica(act: dict, activada: bool) -> dict:
    """La llama el mantenimiento. Devuelve {'pedida': bool, 'detalle': str}."""
    remota = act.get("remota", "")
    if not act.get("hay_nueva") or not remota:
        return {"pedida": False, "detalle": "no hay versión nueva"}
    if not activada:
        return {"pedida": False, "detalle": f"hay versión nueva ({remota}) pero las actualizaciones automáticas están en pausa"}
    est = estado()
    if not est["actualizador"]:
        return {"pedida": False, "detalle": f"hay versión nueva ({remota}) pero el actualizador del servidor no está activado"}
    if est["pedida"]:
        return {"pedida": False, "detalle": f"ya hay una actualización en marcha ({est['pedida']})"}
    if act.get("casa") and usuario_ocupado():
        return {"pedida": False, "detalle": f"hay versión nueva ({remota}) pero el ordenador se está usando a fondo: "
                                             f"se actualizará otra noche, sin molestar"}
    todos = _intentos()
    i = todos.get(remota) or {"veces": 0, "ultimo": 0}
    if i["veces"] >= MAX_INTENTOS:
        return {"pedida": False, "detalle": f"la versión {remota} falló {i['veces']} veces al instalarse sola: "
                                             f"revisa el último resultado y usa «Actualizar ahora»"}
    if i["veces"] and time.time() - i["ultimo"] < ENTRE_INTENTOS:
        return {"pedida": False, "detalle": f"la versión {remota} falló hace poco: se reintentará en unos días"}
    pedir(remota, "actualización automática")
    todos[remota] = {"veces": i["veces"] + 1, "ultimo": time.time()}
    try:
        INTENTOS_FILE.write_text(json.dumps(todos), encoding="utf-8")
    except OSError:
        pass
    return {"pedida": True, "detalle": f"actualización automática a la {remota} pedida (intento {todos[remota]['veces']})"}
