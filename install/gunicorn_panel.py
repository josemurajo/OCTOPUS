# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS Zero-Touch - configuracion de gunicorn para el panel web (servidor de produccion).
# La usa el servicio octopus-panel:  gunicorn -c install/gunicorn_panel.py admin_panel:app
# Lee el .env del proyecto: ADMIN_BIND, ADMIN_PORT, PANEL_HTTPS, PANEL_TLS_CERT, PANEL_TLS_KEY.
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env = {}
try:
    with open(os.path.join(_ROOT, ".env"), encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                _env[k.strip()] = v.strip().strip('"').strip("'")
except OSError:
    pass


def _v(key, default):
    return os.environ.get(key) or _env.get(key) or default


chdir = os.path.join(_ROOT, "lib")
bind = f"{_v('ADMIN_BIND', '0.0.0.0')}:{_v('ADMIN_PORT', '8080')}"
# Un solo proceso con varios hilos: las tareas en segundo plano (copias, respuesta a incidentes) y el
# bloqueo de intentos de acceso viven en memoria y deben ser compartidos.
workers = 1
worker_class = "gthread"
threads = int(_v("PANEL_THREADS", "32"))
timeout = 300
graceful_timeout = 30
accesslog = None  # sin registro de cada peticion (los agentes preguntan cada pocos segundos)
errorlog = "-"
forwarded_allow_ips = _v("PANEL_PROXY_IPS", "127.0.0.1")

_cert = _v("PANEL_TLS_CERT", os.path.join(_ROOT, "data", "tls", "panel.crt"))
_key = _v("PANEL_TLS_KEY", os.path.join(_ROOT, "data", "tls", "panel.key"))
if _v("PANEL_HTTPS", "1") == "1" and os.path.isfile(_cert) and os.path.isfile(_key):
    certfile = _cert
    keyfile = _key
