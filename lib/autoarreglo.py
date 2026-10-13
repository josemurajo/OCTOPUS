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
    "copia_equipo": {"auto": True, "cada": 2 * 3600, "equipo_conectado": True,
                     "como": "repetir la copia del equipo"},
    "prueba_equipo": {"auto": True, "cada": 24 * 3600, "equipo_conectado": True,
                      "como": "hacer una copia nueva del equipo y repetir la prueba de recuperación"},
    "desbloquear_almacen": {"auto": True, "cada": 3600,        # solo quita bloqueos antiguos: no borra nada
                            "como": "quitar los bloqueos antiguos del almacén (sin borrar ninguna copia) y comprobarlo"},
    "copia_servidor": {"auto": True, "cada": 6 * 3600, "como": "repetir la copia del propio servidor"},
    "mantenimiento_ahora": {"auto": True, "cada": 24 * 3600,   # el de la noche, que no se hizo
                            "como": "hacer ahora el mantenimiento que no se hizo por la noche"},
    "renovar_certificado": {"auto": True, "cada": 24 * 3600, "madrugada": True,  # el panel se reinicia unos segundos
                            "como": "emitir un certificado nuevo con la misma autoridad (los equipos lo aceptan solos)"},
    "reenviar_sugerencias": {"auto": True, "cada": 24 * 3600, "como": "volver a enviar las sugerencias al soporte"},
    "comprobar_actualizacion": {"auto": False, "como": "volver a comprobar si hay versión nueva"},  # ya se hace cada 2 días
    "limpiar_copias": {"auto": False, "como": "borrar las copias antiguas que sobran", "riesgo": "Se borran las copias antiguas que sobran según cuántas has elegido "
                                                "guardar. Lo que se borra no se puede recuperar."},
    "reparar_almacen": {"auto": False, "como": "reconstruir el índice del almacén y comprobarlo", "riesgo": "Se reconstruye el índice del almacén de copias. Es una operación "
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
        nuevos = {k: v for k, v in datos.items() if not k.startswith("_") and (k in claves_activas or v.get("en_curso"))}
        for interna in ("_vistos", "_avisados"):   # avisos que ya no estan: si vuelven a pasar, se avisa otra vez
            if interna in datos:
                nuevos[interna] = {k: v for k, v in datos[interna].items() if k in claves_activas}
        if "_notif" in datos:
            nuevos["_notif"] = {k: v for k, v in datos["_notif"].items() if v.get("dia") == hoy}
        cuenta = {k: v for k, v in (datos.get("_cuenta") or {}).items() if v.get("dia") == hoy}
        if cuenta:
            nuevos["_cuenta"] = cuenta
        if len(nuevos) != len(datos):
            _guardar(nuevos)




# ---------------------------------------------------------------- avisos al momento (correo y Telegram)
INTERVALO = int(os.environ.get("OCTOPUS_AUTOARREGLO_SEGUNDOS", "600"))
DESPERTAR_FILE = ESTADO_FILE.parent / "autoarreglo_ya"   # lo deja el mantenimiento (otro proceso) para avisar ya
MAX_AVISOS_DIA = 4          # el mismo problema, como mucho 4 mensajes al día aunque vaya y venga
# avisos que no se mandan (ya los manda el incidente, o son recordatorios) y los que esperan antes de avisar
NO_SE_AVISA = {"OCT-SEN-01", "OCT-EQ-06", "OCT-KIT-01"}
ESPERA_ANTES_DE_AVISAR = {"OCT-EQ-01": 24 * 3600}   # un portátil apagado por la noche no es un problema


def despertar() -> None:
    """Para el mantenimiento y otros procesos: pide al panel que mire los avisos ya mismo."""
    try:
        DESPERTAR_FILE.parent.mkdir(parents=True, exist_ok=True)
        DESPERTAR_FILE.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def toca_despertar() -> bool:
    try:
        if DESPERTAR_FILE.exists():
            DESPERTAR_FILE.unlink(missing_ok=True)
            return True
    except OSError:
        pass
    return False


def primera_vez() -> bool:
    """True si nunca se ha mirado (instalación o actualización): los avisos que ya había no se reenvían."""
    return "_vistos" not in _leer()


def hay_que_avisar(clave: str, codigo: str, ahora: float | None = None) -> bool:
    """¿Se manda ya el mensaje de este aviso? Apunta cuándo se vio por primera vez."""
    if codigo in NO_SE_AVISA:
        return False
    ahora = time.time() if ahora is None else ahora
    with _lock:
        datos = _leer()
        vistos = datos.setdefault("_vistos", {})
        desde = vistos.setdefault(clave, ahora)
        _guardar(datos)
        if clave in (datos.get("_avisados") or {}):
            return False
        n = (datos.get("_notif") or {}).get(clave) or {}
        if n.get("dia") == datetime.now().strftime("%Y-%m-%d") and n.get("n", 0) >= MAX_AVISOS_DIA:
            return False
    return ahora - desde >= ESPERA_ANTES_DE_AVISAR.get(codigo, 0)


def apuntar_avisado(clave: str, silencioso: bool = False) -> None:
    with _lock:
        datos = _leer()
        datos.setdefault("_avisados", {})[clave] = time.time()
        datos.setdefault("_vistos", {}).setdefault(clave, time.time())
        if not silencioso:
            hoy = datetime.now().strftime("%Y-%m-%d")
            notif = datos.setdefault("_notif", {})
            n = notif.get(clave) if (notif.get(clave) or {}).get("dia") == hoy else {"dia": hoy, "n": 0}
            n["n"] += 1
            notif[clave] = n
        _guardar(datos)


def tipo_alerta(codigo: str) -> str:
    """Tipo para el correo/Telegram (decide quién lo recibe en Ajustes → Avisos por correo)."""
    return "backup_failed" if codigo.startswith("OCT-EQ") else "mantenimiento"


def _lineas_aviso(a: dict) -> list[str]:
    cab = f"[{a['codigo']}] {a['titulo']}" + (f" ({a['equipo']})" if a.get("equipo") and a["equipo"] not in a["titulo"] else "")
    lineas = [cab]
    det = str(a.get("detalle") or "").strip()
    if det and det not in a["titulo"]:
        lineas.append(f"Qué ha pasado: {det}")
    if a.get("por_que"):
        lineas.append(f"Por qué importa: {a['por_que']}")
    return lineas


def _pasos(a: dict) -> list[str]:
    return [f"  {i}. {p}" for i, p in enumerate(a.get("pasos") or [], 1)]


def mensaje_nuevo(a: dict, plan: str, motivo: str = "", panel: str = "") -> str:
    """Mensaje de un aviso nuevo: qué ha pasado y cómo se arregla.
    plan: 'arreglando' (lo hace solo ya) | 'luego' (lo hará solo más tarde, motivo) | 'permiso' | 'rendido' | 'manual'."""
    como = politica(a.get("accion")).get("como", "")
    lineas = ["⚠️ " + _lineas_aviso(a)[0]] + _lineas_aviso(a)[1:]
    enlace = f"{panel}/avisos" if panel else "el panel, apartado Avisos"
    if plan == "arreglando":
        lineas.append(f"🔧 Se arregla solo: OCTOPUS lo está arreglando ahora mismo ({como}). No tienes que hacer nada; "
                      f"te aviso cuando termine.")
    elif plan == "luego":
        lineas.append(f"🔧 Se arregla solo ({como}), pero ahora no se puede: {motivo}. Lo hará en cuanto se pueda.")
        lineas.append(f"Si tienes prisa: entra en {enlace} y pulsa «Solucionar: {a.get('boton', 'Solucionar')}».")
    elif plan == "permiso":
        lineas.append(f"✋ Necesita tu permiso para arreglarlo ({como}): {a.get('riesgo')}")
        lineas.append(f"Para arreglarlo: entra en {enlace}, marca «Entiendo lo que se va a hacer» y pulsa "
                      f"«Solucionar: {a.get('boton', 'Solucionar')}».")
        lineas.append("Lo que dice el aviso:")
        lineas += _pasos(a)
    elif plan == "rendido":
        lineas.append("❌ OCTOPUS lo ha intentado arreglar solo varias veces y no ha podido. Hay que mirarlo:")
        lineas += _pasos(a)
        if a.get("accion"):
            lineas.append(f"Para intentarlo otra vez: {enlace} → «Solucionar: {a.get('boton', 'Solucionar')}».")
    else:
        lineas.append("Qué hacer:")
        lineas += _pasos(a)
        if a.get("accion"):
            lineas.append(f"O entra en {enlace} y pulsa «Solucionar: {a.get('boton', 'Solucionar')}».")
    return "\n".join(lineas)


def mensaje_resultado(a: dict, ok: bool, detalle: str, clave: str, panel: str = "") -> str:
    """Mensaje cuando termina un arreglo automático: qué ha hecho y cómo ha ido."""
    como = politica(a.get("accion")).get("como", "arreglarlo")
    cab = _lineas_aviso(a)[0]
    if ok:
        lineas = [f"✅ Arreglado solo: {cab}",
                  f"Qué ha hecho OCTOPUS: {como}.",
                  f"Resultado: {detalle or 'correcto'}.",
                  "No tienes que hacer nada."]
    else:
        lineas = [f"❌ No se ha podido arreglar solo: {cab}",
                  f"Qué ha intentado OCTOPUS: {como}.",
                  f"Qué ha pasado: {detalle or 'falló'}."]
        if rendido(clave):
            lineas.append("Ya no lo intentará más solo. Qué hacer:")
            lineas += _pasos(a)
            if panel:
                lineas.append(f"Para intentarlo otra vez: {panel}/avisos → «Solucionar: {a.get('boton', 'Solucionar')}».")
        else:
            espera = politica(a.get("accion")).get("cada", 3600)
            lineas.append(f"Lo volverá a intentar solo dentro de {max(1, round(espera / 3600))} h. Si tienes prisa, "
                          f"pulsa «Solucionar» en {panel + '/avisos' if panel else 'el panel, apartado Avisos'}.")
    return "\n".join(lineas)
