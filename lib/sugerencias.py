#!/usr/bin/env python3
"""
OCTOPUS - "Enviar sugerencia o problema": lo que el usuario escribe en el panel llega al soporte de OCTOPUS.

Destinos (todos opcionales; se configuran en el .env del servidor con  sudo bash octopus.sh ajustes):
  SOPORTE_CORREO           correo del soporte (se envia con el correo de avisos configurado en el panel)
  SOPORTE_TELEGRAM_TOKEN   bot de Telegram del soporte  +  SOPORTE_TELEGRAM_CHAT  chat al que avisar
  SOPORTE_GITHUB_REPO      usuario/repositorio  +  SOPORTE_GITHUB_TOKEN: las SUGERENCIAS (nunca problemas con
                           diagnostico ni datos) se publican como incidencia publica en GitHub
Si no hay destino o no hay Internet, se guarda en el servidor y se reintenta cada noche (y con el boton
"Solucionar" del aviso OCT-SUG-01). El diagnostico solo se adjunta si el usuario marca la casilla.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))

GRAVEDADES = {"sugerencia": "Sugerencia o idea", "duda": "Duda", "problema": "Algo no funciona",
              "urgente": "Urgente: no puedo trabajar o no puedo recuperar algo"}


def crear_tabla(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS sugerencias (
        id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, usuario TEXT, gravedad TEXT, texto TEXT,
        correo_respuesta TEXT, diagnostico TEXT, estado TEXT DEFAULT 'pendiente', destinos TEXT, error TEXT)""")


def destinos(env: dict) -> dict:
    return {"correo": env.get("SOPORTE_CORREO", "").strip(),
            "telegram": bool(env.get("SOPORTE_TELEGRAM_TOKEN", "").strip() and env.get("SOPORTE_TELEGRAM_CHAT", "").strip()),
            "github": bool(env.get("SOPORTE_GITHUB_REPO", "").strip() and env.get("SOPORTE_GITHUB_TOKEN", "").strip())}


def hay_destino(env: dict) -> bool:
    d = destinos(env)
    return bool(d["correo"] or d["telegram"] or d["github"])


def _texto(fila: dict, version: str) -> str:
    t = [f"OCTOPUS {version} - {GRAVEDADES.get(fila['gravedad'], fila['gravedad'])}",
         f"Fecha: {fila['fecha']}", f"Usuario del panel: {fila['usuario']}"]
    if fila.get("correo_respuesta"):
        t.append(f"Responder a: {fila['correo_respuesta']}")
    t += ["", fila["texto"]]
    if fila.get("diagnostico"):
        t += ["", "---- Diagnostico (sin contrasenas ni nombres de archivos) ----", fila["diagnostico"]]
    return "\n".join(t)


def _correo(env: dict, db_file: Path, asunto: str, cuerpo: str) -> str | None:
    from config_manager import ConfigManager
    from notifications import NotificationManager
    ok, msg = NotificationManager(ConfigManager(str(db_file))).send_email(env["SOPORTE_CORREO"], asunto, cuerpo)
    return None if ok else f"correo: {msg}"


def _telegram(env: dict, cuerpo: str) -> str | None:
    url = f"https://api.telegram.org/bot{env['SOPORTE_TELEGRAM_TOKEN'].strip()}/sendMessage"
    datos = json.dumps({"chat_id": env["SOPORTE_TELEGRAM_CHAT"].strip(), "text": cuerpo[:3900]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"}),
                                    timeout=20) as r:
            return None if json.loads(r.read() or b"{}").get("ok") else "telegram: respuesta no valida"
    except Exception as exc:
        return f"telegram: {exc.__class__.__name__}"


def _github(env: dict, fila: dict, version: str) -> str | None:
    repo = env["SOPORTE_GITHUB_REPO"].strip()
    datos = json.dumps({"title": f"[Sugerencia] {fila['texto'][:70]}",
                        "body": f"Enviada desde el panel de OCTOPUS {version}.\n\n{fila['texto']}",
                        "labels": ["sugerencia"]}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues", data=datos, method="POST", headers={
        "Authorization": f"Bearer {env['SOPORTE_GITHUB_TOKEN'].strip()}", "Accept": "application/vnd.github+json",
        "User-Agent": "octopus"})
    try:
        with urllib.request.urlopen(req, timeout=20):
            return None
    except Exception as exc:
        return f"github: {exc.__class__.__name__}"


def enviar(env: dict, db_file: Path, sid: int) -> dict:
    """Intenta enviar una sugerencia guardada a todos los destinos configurados."""
    import avisos
    import banderines
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    crear_tabla(conn)
    fila = conn.execute("SELECT * FROM sugerencias WHERE id = ?", (sid,)).fetchone()
    if not fila:
        conn.close()
        return {"ok": False, "detalle": "No existe"}
    fila = dict(fila)
    d = destinos(env)
    if not (d["correo"] or d["telegram"] or d["github"]):
        conn.execute("UPDATE sugerencias SET estado = 'sin_destino', error = ? WHERE id = ?",
                     ("No hay ningun destino de soporte configurado", sid))
        conn.commit()
        conn.close()
        banderines.marcar("sugerencias", f"Sugerencia {sid} guardada: falta configurar el destino del soporte",
                          codigo="OCT-SUG-01", nivel="aviso")
        return {"ok": False, "detalle": "guardada en el servidor (falta configurar a dónde se envían)"}
    version = avisos.version_local()
    cuerpo = _texto(fila, version)
    errores, hechos = [], []
    if d["correo"]:
        e = _correo(env, db_file, f"[OCTOPUS soporte] {GRAVEDADES.get(fila['gravedad'], '')}: {fila['texto'][:60]}", cuerpo)
        (errores if e else hechos).append(e or "correo")
    if d["telegram"]:
        e = _telegram(env, cuerpo)
        (errores if e else hechos).append(e or "telegram")
    if d["github"] and fila["gravedad"] == "sugerencia" and not fila.get("diagnostico"):
        e = _github(env, fila, version)
        (errores if e else hechos).append(e or "github")
    estado = "enviada" if hechos else "pendiente"
    conn.execute("UPDATE sugerencias SET estado = ?, destinos = ?, error = ? WHERE id = ?",
                 (estado, ",".join(hechos), "; ".join(errores), sid))
    conn.commit()
    conn.close()
    banderines.marcar("sugerencias", f"Sugerencia {sid}: " + (f"enviada ({', '.join(hechos)})" if hechos else "no se pudo enviar")
                      + (f"; fallos: {'; '.join(errores)}" if errores else ""),
                      codigo=None if hechos else "OCT-SUG-01", nivel="ok" if hechos else "aviso")
    return {"ok": bool(hechos), "detalle": ("enviada (" + ", ".join(hechos) + ")") if hechos
            else "no se pudo enviar ahora; se reintentará: " + "; ".join(errores)}


def guardar(db_file: Path, usuario: str, gravedad: str, texto: str, correo: str, diagnostico: str) -> int:
    conn = sqlite3.connect(str(db_file))
    crear_tabla(conn)
    cur = conn.execute("INSERT INTO sugerencias (fecha, usuario, gravedad, texto, correo_respuesta, diagnostico) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (datetime.now().astimezone().isoformat(timespec="seconds"), usuario,
                        gravedad if gravedad in GRAVEDADES else "problema", texto[:5000], correo[:200], diagnostico))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def pendientes(db_file: Path) -> list[dict]:
    try:
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        crear_tabla(conn)
        filas = [dict(r) for r in conn.execute(
            "SELECT id, fecha, gravedad, estado, error FROM sugerencias WHERE estado != 'enviada' ORDER BY id")]
        conn.close()
        return filas
    except sqlite3.Error:
        return []


def reenviar_pendientes(env: dict, db_file: Path | None = None) -> dict:
    if db_file is None:
        import mantenimiento as mant
        db_file = mant.db_path(env)
    lista = pendientes(db_file)
    if not lista or not hay_destino(env):
        return {"intentadas": 0, "ok": not lista, "detalle": "nada que reenviar" if not lista
                else f"{len(lista)} guardadas; falta configurar el destino del soporte"}
    enviadas = sum(1 for s in lista if enviar(env, db_file, s["id"])["ok"])
    return {"intentadas": len(lista), "ok": enviadas == len(lista),
            "detalle": f"{enviadas} de {len(lista)} enviadas"}
