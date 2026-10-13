#!/usr/bin/env python3
"""
OCTOPUS - Qué avisos se arreglan solos y cuáles necesitan permiso.

Regla: OCTOPUS arregla solo lo que NO tiene riesgo (repetir una copia, quitar un bloqueo antiguo, renovar el
certificado...). Lo que puede borrar datos o es una operación gorda (borrar copias antiguas, reparar el almacén)
espera a que una persona pulse «Solucionar» y confirme. Si hay un incidente abierto (posible ataque), no se arregla
nada solo: decide una persona.

Para no machacar el servidor, cada arreglo automático tiene un tiempo mínimo entre intentos y, si falla 3 veces
seguidas, OCTOPUS deja de intentarlo y el aviso pide que se mire a mano.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

ESTADO_FILE = Path(__file__).resolve().parent.parent / "data" / "autoarreglos.json"
MAX_FALLOS = 3
MAX_AL_DIA = 6      # si algo se arregla y vuelve a pasar una y otra vez, hay que mirarlo a mano
_lock = threading.Lock()

# accion -> como se trata. auto=True: se hace sola. riesgo: texto que se enseña antes de pedir permiso.
POLITICA: dict[str, dict] = {
    "copia_equipo": {"auto": True, "cada": 2 * 3600, "equipo_conectado": True},
    "prueba_equipo": {"auto": True, "cada": 24 * 3600, "equipo_conectado": True},
    "desbloquear_almacen": {"auto": True, "cada": 3600},       # solo quita bloqueos antiguos: no borra nada
    "copia_servidor": {"auto": True, "cada": 6 * 3600},
    "mantenimiento_ahora": {"auto": True, "cada": 24 * 3600},  # el de la noche, que no se hizo
    "renovar_certificado": {"auto": True, "cada": 24 * 3600, "madrugada": True},  # el panel se reinicia unos segundos
    "reenviar_sugerencias": {"auto": True, "cada": 24 * 3600},
    "comprobar_actualizacion": {"auto": False},  # ya se comprueba sola cada 2 días
    "limpiar_copias": {"auto": False, "riesgo": "Se borran las copias antiguas que sobran según cuántas has elegido "
                                                "guardar. Lo que se borra no se puede recuperar."},
    "reparar_almacen": {"auto": False, "riesgo": "Se reconstruye el índice del almacén de copias. Es una operación "
                                                 "larga y, si hay trozos dañados, alguna copia antigua podría quedar "
                                                 "incompleta. Si tienes almacén externo, mejor avisa antes al técnico."},
}


def politica(accion: str | None) -> dict:
    return POLITICA.get(accion or "", {"auto": False})


def es_automatica(accion: str | None) -> bool:
    return bool(politica(accion).get("auto"))


def riesgo(accion: str | None) -> str | None:
    """Texto del riesgo si esa acción necesita permiso de una persona; None si no tiene riesgo."""
    return politica(accion).get("riesgo")


def _leer() -> dict:
    try:
        return json.loads(ESTADO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar(datos: dict) -> None:
    try:
        ESTADO_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = ESTADO_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ESTADO_FILE)
    except OSError:
        pass


def info(clave: str) -> dict:
    return _leer().get(clave) or {}


def rendido(clave: str) -> bool:
    """True si ya falló MAX_FALLOS veces seguidas arreglándolo solo (hay que mirarlo a mano)."""
    cuenta = (_leer().get("_cuenta") or {}).get(clave) or {}
    tope = cuenta.get("dia") == datetime.now().strftime("%Y-%m-%d") and cuenta.get("n", 0) >= MAX_AL_DIA
    return tope or info(clave).get("fallos", 0) >= MAX_FALLOS


def toca(clave: str, accion: str, ahora: float | None = None, hora: int | None = None) -> tuple[bool, str]:
    """¿Toca intentar arreglarlo solo ahora? Devuelve (si/no, motivo)."""
    p = politica(accion)
    if not p.get("auto"):
        return False, "necesita permiso" if p.get("riesgo") else "no se arregla solo"
    ahora = time.time() if ahora is None else ahora
    hora = datetime.now().hour if hora is None else hora
    if p.get("madrugada") and hora >= 7:
        return False, "se hará sola de madrugada"
    i = info(clave)
    if i.get("en_curso") and ahora - i.get("ultimo", 0) < 6 * 3600:
        return False, "ya se está arreglando"
    cuenta = (_leer().get("_cuenta") or {}).get(clave) or {}
    if cuenta.get("dia") == datetime.now().strftime("%Y-%m-%d") and cuenta.get("n", 0) >= MAX_AL_DIA:
        return False, f"ya se ha arreglado solo {cuenta['n']} veces hoy y vuelve a pasar: hay que mirarlo"
    if i.get("fallos", 0) >= MAX_FALLOS:
        return False, f"falló {i['fallos']} veces seguidas arreglándolo solo"
    if ahora - i.get("ultimo", 0) < p.get("cada", 3600):
        return False, "se intentó hace poco"
    return True, ""


def empezar(clave: str, ahora: float | None = None) -> None:
    with _lock:
        datos = _leer()
        i = datos.get(clave) or {"fallos": 0}
        i.update(ultimo=time.time() if ahora is None else ahora, en_curso=True)
        datos[clave] = i
        hoy = datetime.now().strftime("%Y-%m-%d")
        cuenta = datos.setdefault("_cuenta", {})
        c = cuenta.get(clave) if (cuenta.get(clave) or {}).get("dia") == hoy else {"dia": hoy, "n": 0}
        c["n"] += 1
        cuenta[clave] = c
        _guardar(datos)


def terminar(clave: str, ok: bool) -> None:
    """Apunta el resultado. Un arreglo bien (solo o con el botón) pone a cero los fallos."""
    with _lock:
        datos = _leer()
        if ok:   # arreglado: si vuelve a pasar más adelante, se arregla otra vez sin esperar
            datos.pop(clave, None)
        else:    # falló: se espera el tiempo mínimo antes de reintentar, y se cuentan los fallos seguidos
            i = datos.get(clave) or {"fallos": 0, "ultimo": time.time()}
            i["en_curso"] = False
            i["fallos"] = i.get("fallos", 0) + 1
            datos[clave] = i
        _guardar(datos)


def olvidar(clave: str) -> None:
    """Cuando alguien pulsa «Solucionar» a mano, se vuelve a dar a OCTOPUS sus intentos automáticos."""
    with _lock:
        datos = _leer()
        if datos.pop(clave, None) is not None:
            _guardar(datos)


def limpiar_viejos(claves_activas: set[str]) -> None:
    """Quita el historial de avisos que ya no existen (así un fallo nuevo empieza con sus 3 intentos)."""
    with _lock:
        datos = _leer()
        hoy = datetime.now().strftime("%Y-%m-%d")
        nuevos = {k: v for k, v in datos.items() if k != "_cuenta" and (k in claves_activas or v.get("en_curso"))}
        cuenta = {k: v for k, v in (datos.get("_cuenta") or {}).items() if v.get("dia") == hoy}
        if cuenta:
            nuevos["_cuenta"] = cuenta
        if len(nuevos) != len(datos):
            _guardar(nuevos)


INTERVALO = int(os.environ.get("OCTOPUS_AUTOARREGLO_SEGUNDOS", "600"))
