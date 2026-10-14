#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Panel web con cheroot (servidor WSGI de produccion, con HTTPS, que funciona en Windows).

En Linux y Mac el panel va con gunicorn; gunicorn no existe para Windows, asi que alli se usa este. Igual que con
gunicorn: un solo proceso con varios hilos (las tareas en segundo plano viven en memoria y se comparten).
"""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
os.chdir(BASE_DIR / "lib")


def main() -> int:
    from cheroot import wsgi
    import admin_panel

    import configuracion
    env = configuracion.leer_env()   # igual que install/gunicorn_panel.py: variable del proceso o .env
    puerto = int(os.environ.get("ADMIN_PORT") or env.get("ADMIN_PORT") or "8080")
    bind = os.environ.get("ADMIN_BIND") or env.get("ADMIN_BIND") or "0.0.0.0"
    hilos = int(os.environ.get("PANEL_THREADS", "32"))
    servidor = wsgi.Server((bind, puerto), admin_panel.app, numthreads=hilos, request_queue_size=64,
                           timeout=300, server_name="octopus")
    if admin_panel.USE_HTTPS:
        from cheroot.ssl.builtin import BuiltinSSLAdapter
        servidor.ssl_adapter = BuiltinSSLAdapter(admin_panel.TLS_CERT, admin_panel.TLS_KEY)

    def parar(*_):
        servidor.stop()
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, parar)
        except (ValueError, OSError):
            pass
    print(f"[panel] cheroot en {bind}:{puerto} ({'HTTPS' if admin_panel.USE_HTTPS else 'HTTP'}, {hilos} hilos)", flush=True)
    try:
        servidor.start()
    except KeyboardInterrupt:
        servidor.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
