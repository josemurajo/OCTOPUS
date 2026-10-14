#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS Zero-Touch - herramienta de consola para los equipos (dentro del contenedor del servidor).

  python lib/equipos_cli.py alta <equipo> [linux|windows|macos] [ip] [rutas_json]
                                        registra el equipo (y sus carpetas) y escribe su clave nueva
  python lib/equipos_cli.py id <equipo>                               numero del equipo en el panel
  python lib/equipos_cli.py pedir <equipo> GET|POST <ruta> [json] [segundos]
  python lib/equipos_cli.py conectado <equipo>                        sale con 0 si el agente esta conectado
  python lib/equipos_cli.py lista
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))


def _cargar_env() -> None:
    f = BASE_DIR / ".env"
    if f.is_file():
        for raw in f.read_text(encoding="utf-8").splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                k, v = raw.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _db() -> str:
    db = os.environ.get("DB_PATH", "./data/admin_panel.db")
    return db if os.path.isabs(db) else str((BASE_DIR / db).resolve())


def main(argv: list[str]) -> int:
    _cargar_env()
    import ordenes
    ordenes.init(_db())
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "alta" and len(argv) >= 3:
        equipo, so = argv[2], (argv[3] if len(argv) > 3 else "linux")
        ip = argv[4] if len(argv) > 4 else ""
        # las carpetas se guardan como en "Anadir equipo": asi el instalador del panel protege lo mismo
        rutas = json.loads(argv[5]) if len(argv) > 5 and argv[5] else None
        notas = json.dumps({"rutas": rutas}) if rutas else None
        conn = sqlite3.connect(_db())
        if not conn.execute("SELECT 1 FROM systems WHERE lower(hostname) = lower(?)", (equipo,)).fetchone():
            conn.execute("INSERT INTO systems (hostname, ip_address, os_family, status, notes) VALUES (?, ?, ?, 'unknown', ?)",
                         (equipo, ip, so, notas))
        else:
            if ip:
                conn.execute("UPDATE systems SET ip_address = ? WHERE lower(hostname) = lower(?)", (ip, equipo))
            if notas:
                conn.execute("UPDATE systems SET notes = ? WHERE lower(hostname) = lower(?)", (notas, equipo))
        conn.commit()
        conn.close()
        print(ordenes.nuevo_token(equipo))
        return 0
    if cmd == "pedir" and len(argv) >= 5:
        datos = json.loads(argv[5]) if len(argv) > 5 and argv[5] else None
        timeout = float(argv[6]) if len(argv) > 6 else 60
        res = ordenes.pedir(argv[2], argv[3].upper(), argv[4], datos, timeout)
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res.get("status") in ("ok", "success") else 1
    if cmd == "id" and len(argv) >= 3:
        conn = sqlite3.connect(_db())
        row = conn.execute("SELECT id FROM systems WHERE lower(hostname) = lower(?)", (argv[2],)).fetchone()
        conn.close()
        if not row:
            return 1
        print(row[0])
        return 0
    if cmd == "conectado" and len(argv) >= 3:
        return 0 if ordenes.en_linea(argv[2]) else 1
    if cmd == "lista":
        conn = sqlite3.connect(_db())
        for (h,) in conn.execute("SELECT hostname FROM systems ORDER BY hostname"):
            print(f"{h}\t{'conectado' if ordenes.en_linea(h) else 'desconectado'}")
        conn.close()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
