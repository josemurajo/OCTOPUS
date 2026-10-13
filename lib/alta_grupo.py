#!/usr/bin/env python3
"""
OCTOPUS - Dar de alta e instalar equipos encontrados en la red (lo usan el panel y el modo consola, el mismo codigo).

  conocidos(db)                         -> IPs y nombres que ya estan dados de alta, y grupos existentes
  alta(db, equipo, grupo, quien)        -> id del equipo nuevo (o None si ya existia uno con ese nombre)
  que_falta(equipo, usuario, password)  -> por que no se puede instalar a distancia (o "" si se puede)
  instalar(db, sid, equipo, usuario, password, solo_clave, paso) -> (ok, mensaje)   (espera a que termine)
La contrasena solo se usa para entrar por SSH y no se guarda en ningun sitio.
"""
from __future__ import annotations

import json
import sqlite3


def _db(db_file: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_file, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def conocidos(db_file: str) -> tuple[dict, list, set]:
    """({ip: nombre}, [grupos], {nombres en minusculas}) de los equipos ya dados de alta."""
    conn = _db(db_file)
    filas = conn.execute("SELECT hostname, ip_address, notes FROM systems").fetchall()
    conn.close()
    ips = {f["ip_address"]: f["hostname"] for f in filas if f["ip_address"]}
    grupos = sorted({(json.loads(f["notes"] or "{}") or {}).get("grupo", "") for f in filas} - {""})
    return ips, grupos, {f["hostname"].lower() for f in filas}


def alta(db_file: str, equipo: dict, grupo: str, quien: str = "", user_id=None) -> int | None:
    """Da de alta un equipo encontrado (nombre, ip, so). None si ya hay otro con ese nombre (no se toca)."""
    import alta_equipos
    import registro
    if equipo["nombre"].lower() in conocidos(db_file)[2]:
        return None
    rutas = alta_equipos.RUTAS_POR_DEFECTO.get(equipo["so"], [])
    conn = _db(db_file)
    cur = conn.execute("INSERT INTO systems (hostname, ip_address, os_family, status, notes) VALUES (?, ?, ?, 'unknown', ?)",
                       (equipo["nombre"], equipo["ip"], equipo["so"], json.dumps({"rutas": rutas, "grupo": grupo})))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    registro.escribir(db_file, user_id, "SYSTEM_ADD",
                      f'{equipo["nombre"]} ({equipo["so"]}, grupo {grupo}, desde «Buscar equipos»{" - " + quien if quien else ""})')
    return sid


def que_falta(equipo: dict, usuario: str, password: str) -> str:
    """Por que no se puede instalar a distancia ahora mismo ("" si se puede)."""
    if not usuario or (not password and equipo["so"] == "windows"):
        return ("Dado de alta. Falta instalarlo: no se escribió usuario/contraseña para su grupo. "
                "Usa «Instalar» en su ficha.")
    if not equipo.get("ssh"):
        return ("No tiene SSH activado, así que no se puede instalar a distancia. "
                + ("En Windows: activa el «Servidor OpenSSH» o usa el instalador de doble clic de su ficha."
                   if equipo["so"] == "windows" else "Activa SSH en el equipo o usa el instalador de su ficha."))
    return ""


def instalar(db_file: str, sid: int, equipo: dict, usuario: str, password: str, solo_clave: bool = False,
             paso=lambda texto: None, user_id=None) -> tuple[bool, str]:
    """Instala OCTOPUS en el equipo por SSH y espera a que se conecte (la misma funcion que usa el panel)."""
    import alta_equipos
    import instalacion_remota
    import ordenes
    import registro
    ordenes.init(db_file)
    conn = _db(db_file)
    fila = conn.execute("SELECT * FROM systems WHERE id = ?", (sid,)).fetchone()
    conn.close()
    notas = json.loads(fila["notes"] or "{}")
    rutas = notas.get("rutas") or alta_equipos.RUTAS_POR_DEFECTO.get(equipo["so"], [])
    registro.escribir(db_file, user_id, "AGENT_REMOTE_START", f'{equipo["nombre"]} ({equipo["ip"]}, usuario {usuario})')
    try:
        ok, msg = instalacion_remota.instalar(
            equipo["nombre"], equipo["so"], equipo["ip"], usuario, password,
            alta_equipos.paquete(equipo["nombre"], equipo["so"], rutas, ordenes.nuevo_token(equipo["nombre"])),
            solo_clave and equipo["so"] == "linux", paso=paso, en_linea=lambda: ordenes.en_linea(equipo["nombre"]))
    except Exception as exc:  # nunca dejar la pantalla colgada; la contrasena nunca sale en el mensaje
        ok, msg = False, instalacion_remota._limpiar(f"Error inesperado: {exc}", password)
    registro.escribir(db_file, user_id, "AGENT_REMOTE_OK" if ok else "AGENT_REMOTE_ERROR", f'{equipo["nombre"]}: {msg}'[:300])
    return ok, msg
