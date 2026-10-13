#!/usr/bin/env python3
"""
OCTOPUS - Diagnostico para soporte: un resumen (texto) y un zip con los banderines y el estado del servidor.

Nunca incluye contrasenas, claves, tokens, el archivo .env, la base de datos ni nombres de archivos de los
usuarios: solo versiones, estado de las tareas, codigos de aviso y los pasos (banderines) ya limpiados.
"""
from __future__ import annotations

import io
import json
import platform
import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))


def _nombres(db_file: Path) -> dict:
    """{nombre real del equipo: equipo-N} para no enviar nunca los nombres de los equipos."""
    try:
        conn = sqlite3.connect(str(db_file))
        filas = [r[0] for r in conn.execute("SELECT hostname FROM systems ORDER BY id")]
        conn.close()
    except sqlite3.Error:
        return {}
    return {h: f"equipo-{i}" for i, h in enumerate(filas, 1) if h}


def anonimizar(texto: str, nombres: dict) -> str:
    import re
    t = str(texto or "")
    for real in sorted(nombres, key=len, reverse=True):
        if len(real) >= 2:
            t = re.sub(r"(?<![\w-])" + re.escape(real) + r"(?![\w-])", nombres[real], t, flags=re.IGNORECASE)
    return t


def _equipos(db_file: Path) -> list[dict]:
    try:
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        filas = conn.execute("SELECT hostname, os_family, agent_info, last_seen FROM systems").fetchall()
        conn.close()
    except sqlite3.Error:
        return []
    lista = []
    for i, r in enumerate(filas, 1):
        try:
            info = json.loads(r["agent_info"] or "{}")
        except (ValueError, TypeError):
            info = {}
        # el nombre del equipo se sustituye por un numero: el soporte no necesita saberlo
        lista.append({"equipo": f"equipo-{i}", "sistema": r["os_family"] or "", "agente": info.get("version", ""),
                      "ultimo_contacto": r["last_seen"] if "last_seen" in r.keys() else ""})
    return lista


def datos(db_file: Path) -> dict:
    nombres = _nombres(db_file)
    d = _datos(db_file)
    return json.loads(anonimizar(json.dumps(d, ensure_ascii=False, default=str), nombres))


def _datos(db_file: Path) -> dict:
    import avisos
    import banderines
    import mantenimiento as mant
    est = mant.leer_estado()
    return {
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "version_octopus": avisos.version_local(),
        "servidor": {"sistema": platform.platform(), "python": platform.python_version()},
        "certificado_dias": avisos.caducidad_certificado(),
        "actualizacion": {k: v for k, v in avisos.leer_actualizacion().items() if k in ("local", "remota", "hay_nueva", "fecha")},
        "mantenimiento": {"fecha": est.get("fecha"),
                          "tareas": {k: {"ok": v.get("ok"), "codigo": v.get("codigo"),
                                         "detalle": banderines.limpiar(str(v.get("detalle", "")))[:300]}
                                     for k, v in (est.get("resultados") or {}).items()}},
        "equipos": _equipos(db_file),
        "ultimos_fallos": [p for p in banderines.leer(limite=400) if p.get("nivel") in ("error", "aviso")][:40],
    }


def resumen_texto(db_file: Path) -> str:
    d = datos(db_file)
    lineas = [f"OCTOPUS {d['version_octopus']} - diagnostico del {d['generado']}",
              f"Servidor: {d['servidor']['sistema']}", f"Certificado: {d['certificado_dias']} dias",
              f"Mantenimiento: {d['mantenimiento']['fecha'] or 'nunca'}"]
    for k, v in d["mantenimiento"]["tareas"].items():
        lineas.append(f"  {k}: {'OK' if v['ok'] else 'FALLO ' + (v['codigo'] or '')} {v['detalle'][:120]}")
    lineas.append(f"Equipos: {len(d['equipos'])}")
    for e in d["equipos"]:
        lineas.append(f"  {e['equipo']}: {e['sistema']} agente {e['agente']}")
    if d["ultimos_fallos"]:
        lineas.append("Ultimos fallos:")
        for p in d["ultimos_fallos"][:15]:
            lineas.append(f"  [{p.get('t')}] {p.get('proceso')} {p.get('codigo') or ''} {p.get('texto')}"[:220])
    return "\n".join(lineas)


def zip_bytes(db_file: Path) -> bytes:
    import banderines
    nombres = _nombres(db_file)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("diagnostico.json", json.dumps(datos(db_file), indent=2, ensure_ascii=False))
        z.writestr("resumen.txt", resumen_texto(db_file))
        for f in banderines.archivos():
            try:
                # se vuelve a limpiar cada linea por si acaso (y sin nombres de equipo)
                limpio = []
                for l in f.read_text(encoding="utf-8").splitlines()[-2000:]:
                    try:
                        p = json.loads(l)
                    except ValueError:
                        continue
                    p.pop("equipo", None)
                    p["texto"] = anonimizar(banderines.limpiar(p.get("texto", "")), nombres)
                    limpio.append(json.dumps(p, ensure_ascii=False))
                z.writestr(f"banderines/{f.name}", "\n".join(limpio) + "\n")
            except OSError:
                continue
        z.writestr("LEEME.txt", "Diagnostico de OCTOPUS para soporte. No contiene contrasenas, claves, la base de datos "
                                "ni nombres de archivos. Los equipos aparecen como equipo-1, equipo-2...\n")
    return buf.getvalue()
