# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS Zero-Touch - Cola de ordenes para los agentes.

El servidor nunca entra en los equipos: cada agente pregunta cada pocos segundos por HTTPS
"¿hay algo para mi?", ejecuta lo que haya y devuelve el resultado. Asi funciona con cualquier IP,
detras de cualquier router y sin abrir puertos en los equipos.

La cola vive en la base de datos del panel, de modo que la pueden usar el panel, la respuesta
a incidentes, el mantenimiento y las herramientas de consola a la vez.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid

DB_FILE = os.environ.get("DB_PATH", "")
SEGUNDOS_EN_LINEA = int(os.environ.get("OCTOPUS_SEGUNDOS_EN_LINEA", "45"))  # sin preguntar en este tiempo = desconectado
INTERVALO_AGENTE = float(os.environ.get("OCTOPUS_INTERVALO_AGENTE", "2"))   # cada cuanto pregunta un agente
_ultimo_visto: dict[str, float] = {}
_lock = threading.Lock()


def init(db_file: str) -> None:
    global DB_FILE
    DB_FILE = db_file
    conn = _db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ordenes (
            id TEXT PRIMARY KEY, equipo TEXT NOT NULL, metodo TEXT NOT NULL, ruta TEXT NOT NULL, datos TEXT,
            estado TEXT NOT NULL DEFAULT 'pendiente', resultado TEXT,
            creada REAL NOT NULL, enviada REAL, terminada REAL, caduca REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS ordenes_equipo ON ordenes (equipo, estado);
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(systems)").fetchall()]
    for col, ddl in (("agent_token_hash", "TEXT"), ("agent_version", "TEXT"), ("last_ip", "TEXT"),
                     ("last_seen_ts", "REAL")):
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE systems ADD COLUMN {col} {ddl}")
    conn.commit()
    conn.close()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------- identidad de los agentes
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def nuevo_token(equipo: str) -> str:
    """Clave propia del equipo: se guarda solo su huella. Si roban una, solo sirve para ese equipo."""
    token = secrets.token_urlsafe(32)
    conn = _db()
    conn.execute("UPDATE systems SET agent_token_hash = ? WHERE lower(hostname) = lower(?)", (_hash(token), equipo))
    conn.commit()
    conn.close()
    return token


def autenticar(equipo: str, token: str) -> sqlite3.Row | None:
    if not equipo or not token:
        return None
    conn = _db()
    row = conn.execute("SELECT * FROM systems WHERE lower(hostname) = lower(?)", (equipo,)).fetchone()
    conn.close()
    if not row:
        return None
    esperado = row["agent_token_hash"] if "agent_token_hash" in row.keys() else None
    if esperado:
        return row if hmac.compare_digest(_hash(token), esperado) else None
    comun = os.environ.get("OCTOPUS_AGENT_TOKEN", "")  # equipos de versiones anteriores (clave comun)
    return row if comun and hmac.compare_digest(token, comun) else None


def latido(row: sqlite3.Row, ip: str, version: str = "") -> None:
    """Marca el equipo como conectado (se escribe como mucho cada 10 s por equipo)."""
    ahora = time.time()
    with _lock:
        if ahora - _ultimo_visto.get(row["hostname"], 0) < 10:
            return
        _ultimo_visto[row["hostname"]] = ahora
    conn = _db()
    conn.execute("UPDATE systems SET last_seen = datetime('now'), last_seen_ts = ?, last_ip = ?, status = 'online', "
                 "agent_version = COALESCE(NULLIF(?, ''), agent_version) WHERE id = ?",
                 (ahora, ip, version, row["id"]))
    conn.commit()
    conn.close()


def en_linea(equipo: str) -> bool:
    ahora = time.time()
    with _lock:
        if ahora - _ultimo_visto.get(equipo, 0) < SEGUNDOS_EN_LINEA:
            return True
    conn = _db()
    row = conn.execute("SELECT last_seen_ts FROM systems WHERE lower(hostname) = lower(?)", (equipo,)).fetchone()
    conn.close()
    return bool(row and row["last_seen_ts"] and ahora - row["last_seen_ts"] < SEGUNDOS_EN_LINEA)


# ---------------------------------------------------------------- cola
def encolar(equipo: str, metodo: str, ruta: str, datos: dict | None, timeout: float) -> str:
    oid = uuid.uuid4().hex
    ahora = time.time()
    conn = _db()
    conn.execute("INSERT INTO ordenes (id, equipo, metodo, ruta, datos, creada, caduca) VALUES (?,?,?,?,?,?,?)",
                 (oid, equipo.lower(), metodo, ruta, json.dumps(datos or {}), ahora, ahora + timeout))
    conn.commit()
    conn.close()
    return oid


def esperar(oid: str, timeout: float) -> dict | None:
    fin = time.time() + timeout
    pausa = 0.1
    while time.time() < fin:
        conn = _db()
        row = conn.execute("SELECT estado, resultado FROM ordenes WHERE id = ?", (oid,)).fetchone()
        conn.close()
        if row and row["estado"] == "hecha":
            try:
                return json.loads(row["resultado"] or "{}")
            except ValueError:
                return {"status": "error", "message": "Respuesta ilegible del equipo"}
        time.sleep(pausa)
        pausa = min(pausa * 1.5, 1.0)
    conn = _db()
    conn.execute("UPDATE ordenes SET estado = 'caducada' WHERE id = ? AND estado != 'hecha'", (oid,))
    conn.commit()
    conn.close()
    return None


def pendientes(equipo: str) -> list[dict]:
    """Ordenes para un equipo (se marcan como enviadas para no repetirlas)."""
    ahora = time.time()
    conn = _db()
    conn.execute("UPDATE ordenes SET estado = 'caducada' WHERE estado = 'pendiente' AND caduca < ?", (ahora,))
    rows = conn.execute("SELECT id, metodo, ruta, datos FROM ordenes WHERE equipo = ? AND estado = 'pendiente' "
                        "ORDER BY creada LIMIT 20", (equipo.lower(),)).fetchall()
    if rows:
        conn.executemany("UPDATE ordenes SET estado = 'enviada', enviada = ? WHERE id = ?",
                         [(ahora, r["id"]) for r in rows])
    # limpieza de ordenes viejas (mas de 2 dias)
    conn.execute("DELETE FROM ordenes WHERE creada < ?", (ahora - 172800,))
    conn.commit()
    conn.close()
    return [{"id": r["id"], "metodo": r["metodo"], "ruta": r["ruta"], "datos": json.loads(r["datos"] or "{}")}
            for r in rows]


def resultado(equipo: str, oid: str, res: dict) -> bool:
    conn = _db()
    cur = conn.execute("UPDATE ordenes SET estado = 'hecha', resultado = ?, terminada = ? "
                       "WHERE id = ? AND equipo = ?", (json.dumps(res)[:5_000_000], time.time(), oid, equipo.lower()))
    conn.commit()
    conn.close()
    return cur.rowcount == 1


def pedir(equipo: str, metodo: str, ruta: str, datos: dict | None = None, timeout: float = 30) -> dict:
    """Envia una orden y espera la respuesta (o devuelve un error si el equipo no esta conectado)."""
    if not en_linea(equipo):
        return {"status": "error", "message": "El equipo no está conectado ahora mismo", "offline": True}
    oid = encolar(equipo, metodo, ruta, datos, timeout)
    res = esperar(oid, timeout)
    if res is None:
        return {"status": "error", "message": "El equipo no ha respondido a tiempo", "offline": not en_linea(equipo)}
    return res
