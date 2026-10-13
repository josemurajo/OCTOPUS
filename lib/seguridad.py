#!/usr/bin/env python3
"""
OCTOPUS - Capas de seguridad del panel (Ajustes -> Funciones -> Seguridad del panel).

  - Bloqueo de atacantes: una direccion que falla muchas veces la contrasena o va probando paginas que no existen se
    bloquea un rato. Nunca se bloquea el propio servidor ni las direcciones de confianza.
  - Aviso de acceso nuevo: si alguien entra desde un navegador que no se habia usado antes.
  - Doble aprobacion: lo peligroso lo tiene que aprobar otro administrador.

Para no quedarse fuera nunca (desde la consola del servidor):
    python lib/seguridad.py emergencia      quita todos los bloqueos y apaga «Panel solo desde la red de la oficina» y la doble aprobacion
    (octopus.sh acceso-emergencia  /  octopus.ps1 acceso-emergencia)
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import sqlite3
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_lock = threading.Lock()


def _db(db_file: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_file, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init(db_file: str) -> None:
    with _db(db_file) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS bloqueos (ip TEXT PRIMARY KEY, fallos INTEGER DEFAULT 0, primero TEXT, ultimo TEXT,
                                             hasta TEXT, motivo TEXT);
        CREATE TABLE IF NOT EXISTS dispositivos (user_id INTEGER, huella TEXT, ip TEXT, navegador TEXT, primera TEXT,
                                                 ultima TEXT, PRIMARY KEY (user_id, huella));
        CREATE TABLE IF NOT EXISTS aprobaciones (id INTEGER PRIMARY KEY AUTOINCREMENT, accion TEXT, datos TEXT,
            resumen TEXT, pedido_por INTEGER, pedido_nombre TEXT, creado TEXT, caduca TEXT, estado TEXT DEFAULT 'pendiente',
            decidido_por TEXT, decidido TEXT);
        """)


def _ahora() -> datetime:
    return datetime.now()


def _ts(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def _de_ts(t: str | None) -> datetime | None:
    try:
        return datetime.strptime(t, "%Y-%m-%d %H:%M:%S") if t else None
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------- bloqueo de atacantes
def nunca_bloquear(ip: str, confianza: str = "") -> bool:
    import funciones
    try:
        dir_ip = ipaddress.ip_address(ip)
    except ValueError:
        return True          # algo raro (sin IP): mejor no bloquear a ciegas
    return dir_ip.is_loopback or funciones.en_redes(ip, confianza)


def fallo(db_file: str, ip: str, motivo: str, intentos: int, minutos: int, confianza: str = "") -> bool:
    """Apunta un fallo de esta direccion. True si con este fallo queda bloqueada (para avisar una sola vez)."""
    if nunca_bloquear(ip, confianza):
        return False
    ahora = _ahora()
    with _lock, _db(db_file) as c:
        f = c.execute("SELECT * FROM bloqueos WHERE ip = ?", (ip,)).fetchone()
        hasta = _de_ts(f["hasta"]) if f else None
        if hasta and hasta > ahora:
            return False                                   # ya bloqueada
        primero = _de_ts(f["primero"]) if f else None
        # los fallos cuentan dentro de una ventana igual al tiempo de bloqueo; si no, se empieza de cero
        if not f or not primero or ahora - primero > timedelta(minutes=minutos) or hasta:
            fallos, primero = 1, ahora
        else:
            fallos = f["fallos"] + 1
        nuevo_hasta = ahora + timedelta(minutes=minutos) if fallos >= intentos else None
        c.execute("INSERT INTO bloqueos (ip, fallos, primero, ultimo, hasta, motivo) VALUES (?, ?, ?, ?, ?, ?) "
                  "ON CONFLICT(ip) DO UPDATE SET fallos=excluded.fallos, primero=excluded.primero, "
                  "ultimo=excluded.ultimo, hasta=excluded.hasta, motivo=excluded.motivo",
                  (ip, fallos, _ts(primero), _ts(ahora), _ts(nuevo_hasta) if nuevo_hasta else None, motivo[:200]))
        return nuevo_hasta is not None


def bloqueada(db_file: str, ip: str, confianza: str = "") -> int:
    """Minutos que le quedan bloqueada (0 = no lo esta)."""
    if nunca_bloquear(ip, confianza):
        return 0
    with _db(db_file) as c:
        f = c.execute("SELECT hasta FROM bloqueos WHERE ip = ?", (ip,)).fetchone()
    hasta = _de_ts(f["hasta"]) if f else None
    if not hasta or hasta <= _ahora():
        return 0
    return int((hasta - _ahora()).total_seconds() // 60) + 1


def acierto(db_file: str, ip: str) -> None:
    """Entro bien: se olvidan sus fallos."""
    with _lock, _db(db_file) as c:
        c.execute("DELETE FROM bloqueos WHERE ip = ? AND (hasta IS NULL OR hasta <= ?)", (ip, _ts(_ahora())))


def lista_bloqueadas(db_file: str) -> list[dict]:
    with _db(db_file) as c:
        filas = c.execute("SELECT * FROM bloqueos WHERE hasta > ? ORDER BY hasta DESC", (_ts(_ahora()),)).fetchall()
    return [dict(f) for f in filas]


def desbloquear(db_file: str, ip: str | None = None) -> int:
    with _lock, _db(db_file) as c:
        cur = c.execute("DELETE FROM bloqueos" + (" WHERE ip = ?" if ip else ""), (ip,) if ip else ())
        return cur.rowcount


# ----------------------------------------------------------------------------------------------- accesos nuevos
def huella(cookie: str) -> str:
    return hashlib.sha256(("octopus-dispositivo|" + (cookie or "")).encode()).hexdigest()


def acceso(db_file: str, user_id: int, cookie: str, ip: str, navegador: str) -> str:
    """Apunta el acceso. Devuelve 'primero' (primer acceso del usuario: no se avisa), 'conocido' o 'nuevo'."""
    h = huella(cookie) if cookie else ""
    ahora = _ts(_ahora())
    with _lock, _db(db_file) as c:
        hay = c.execute("SELECT COUNT(*) FROM dispositivos WHERE user_id = ?", (user_id,)).fetchone()[0]
        if h and c.execute("SELECT 1 FROM dispositivos WHERE user_id = ? AND huella = ?", (user_id, h)).fetchone():
            c.execute("UPDATE dispositivos SET ultima = ?, ip = ? WHERE user_id = ? AND huella = ?", (ahora, ip, user_id, h))
            return "conocido"
        return "primero" if not hay else "nuevo"


def recordar(db_file: str, user_id: int, cookie: str, ip: str, navegador: str) -> None:
    ahora = _ts(_ahora())
    with _lock, _db(db_file) as c:
        c.execute("INSERT OR REPLACE INTO dispositivos (user_id, huella, ip, navegador, primera, ultima) VALUES "
                  "(?, ?, ?, ?, COALESCE((SELECT primera FROM dispositivos WHERE user_id = ? AND huella = ?), ?), ?)",
                  (user_id, huella(cookie), ip, (navegador or "")[:200], user_id, huella(cookie), ahora, ahora))
        # como mucho 30 navegadores recordados por usuario (los mas antiguos se olvidan)
        c.execute("DELETE FROM dispositivos WHERE user_id = ? AND huella NOT IN (SELECT huella FROM dispositivos "
                  "WHERE user_id = ? ORDER BY ultima DESC LIMIT 30)", (user_id, user_id))


def olvidar_dispositivos(db_file: str, user_id: int) -> None:
    with _lock, _db(db_file) as c:
        c.execute("DELETE FROM dispositivos WHERE user_id = ?", (user_id,))


def nombre_navegador(ua: str) -> str:
    ua = ua or ""
    nav = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                               ("Safari/", "Safari")) if k in ua), "un navegador")
    so = next((n for k, n in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                              ("Mac OS X", "Mac"), ("Linux", "Linux")) if k in ua), "")
    return f"{nav} en {so}" if so else nav


# ----------------------------------------------------------------------------------------------- doble aprobacion
def pedir(db_file: str, accion: str, datos: dict, resumen: str, user_id: int, usuario: str, horas: int) -> int:
    ahora = _ahora()
    with _lock, _db(db_file) as c:
        # la misma peticion repetida no se duplica
        f = c.execute("SELECT id FROM aprobaciones WHERE estado = 'pendiente' AND accion = ? AND datos = ? AND caduca > ?",
                      (accion, json.dumps(datos, sort_keys=True), _ts(ahora))).fetchone()
        if f:
            return f["id"]
        cur = c.execute("INSERT INTO aprobaciones (accion, datos, resumen, pedido_por, pedido_nombre, creado, caduca) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (accion, json.dumps(datos, sort_keys=True), resumen[:300], user_id, usuario, _ts(ahora),
                         _ts(ahora + timedelta(hours=horas))))
        return cur.lastrowid


def pendientes(db_file: str) -> list[dict]:
    with _lock, _db(db_file) as c:
        c.execute("UPDATE aprobaciones SET estado = 'caducada' WHERE estado = 'pendiente' AND caduca <= ?", (_ts(_ahora()),))
        return [dict(f) for f in c.execute("SELECT * FROM aprobaciones WHERE estado = 'pendiente' ORDER BY id").fetchall()]


def decidir(db_file: str, aid: int, user_id: int, usuario: str, aprobar: bool) -> tuple[dict | None, str]:
    """(peticion, '') si se puede ejecutar/rechazar; (None, motivo) si no."""
    with _lock, _db(db_file) as c:
        f = c.execute("SELECT * FROM aprobaciones WHERE id = ?", (aid,)).fetchone()
        if not f or f["estado"] != "pendiente":
            return None, "Esa petición ya no está pendiente."
        if _de_ts(f["caduca"]) and _de_ts(f["caduca"]) <= _ahora():
            c.execute("UPDATE aprobaciones SET estado = 'caducada' WHERE id = ?", (aid,))
            return None, "Esa petición ha caducado: hay que pedirla otra vez."
        if aprobar and f["pedido_por"] == user_id:
            return None, "No puedes aprobar tu propia petición: la tiene que aprobar otro administrador."
        c.execute("UPDATE aprobaciones SET estado = ?, decidido_por = ?, decidido = ? WHERE id = ?",
                  ("aprobada" if aprobar else "rechazada", usuario, _ts(_ahora()), aid))
        d = dict(f)
        d["datos"] = json.loads(d["datos"] or "{}")
        return d, ""


# ----------------------------------------------------------------------------------------------- consola
def _db_por_defecto() -> str:
    import os
    import configuracion
    base = Path(__file__).resolve().parent.parent
    db = configuracion.leer_env().get("DB_PATH", "./data/admin_panel.db")
    return db if os.path.isabs(db) else str((base / db).resolve())


def main(argv: list[str]) -> int:
    orden = argv[1] if len(argv) > 1 else ""
    if orden != "emergencia":
        print(__doc__)
        return 2
    import config_manager
    import registro
    db = _db_por_defecto()
    init(db)
    n = desbloquear(db)
    cm = config_manager.ConfigManager(db)
    cm.set_config("panel_solo_redes", False)
    cm.set_config("doble_aprobacion", False)
    registro.escribir(db, None, "ACCESO_EMERGENCIA", f"Desde la consola del servidor: {n} bloqueos quitados y "
                                                     f"«Panel solo desde la red de la oficina» y doble aprobación apagados")
    print(f"Listo: {n} direcciones desbloqueadas, el panel vuelve a abrirse desde cualquier red y la doble aprobación "
          f"está apagada.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
