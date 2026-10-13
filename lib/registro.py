#!/usr/bin/env python3
"""
OCTOPUS - Registro de actividad encadenado (lo usan el panel y el modo consola).

Cada linea lleva la huella SHA-256 de la anterior: si alguien borra o cambia una linea por detras, la cadena se rompe
y el panel lo avisa (Ajustes -> Registro de actividad).
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone


def huella(anterior, rid, user_id, action, details, ts, ip) -> str:
    base = "|".join("" if x is None else str(x) for x in (anterior, rid, user_id, action, details, ts, ip))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def escribir(db_file: str, user_id, action: str, details: str = "", ip_address: str = "") -> None:
    conn = sqlite3.connect(db_file, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        prev = conn.execute("SELECT hash FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()
        anterior = prev["hash"] if prev and prev["hash"] else ""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute("INSERT INTO audit_logs (user_id, action, details, ip_address, timestamp, hash_anterior) "
                           "VALUES (?, ?, ?, ?, ?, ?)", (user_id, action, details, ip_address, ts, anterior))
        conn.execute("UPDATE audit_logs SET hash = ? WHERE id = ?",
                     (huella(anterior, cur.lastrowid, user_id, action, details, ts, ip_address), cur.lastrowid))
        conn.commit()
    finally:
        conn.close()
