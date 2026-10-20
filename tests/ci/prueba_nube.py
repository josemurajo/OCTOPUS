# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Copia de la nube (lib/copia_nube.py) con Microsoft 365 y Google SIMULADOS (servidor local) y restic REAL.

Comprueba: saca el token, lista usuarios, baja el correo (.eml) y los archivos, lo guarda en el almacén, al repetir no
vuelve a bajar lo que no cambió (incremental), recupera una copia y los .eml salen idénticos. Necesita restic en el
PATH. Solo prueba la lógica; no toca ninguna nube real.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

T = Path(tempfile.mkdtemp(prefix="octopus_nube_"))
restic = shutil.which("restic")
if not restic:
    print("Falta restic en el PATH")
    sys.exit(1)

EML1 = b"From: ana@empresa.com\r\nSubject: Factura\r\n\r\nHola, adjunto la factura.\r\n"
EML2 = b"From: jefe@empresa.com\r\nSubject: Reunion\r\n\r\nManana a las 9.\r\n"
DOCX = b"PK\x03\x04 contenido de un documento de OneDrive " + b"x" * 500
GMAIL = b"From: cliente@gmail.com\r\nSubject: Pedido\r\n\r\nQuiero 3 cajas.\r\n"
import base64 as _b64
PETICIONES = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _j(self, obj, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def _b(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        PETICIONES.append(("POST", self.path))
        if "token" in self.path or "oauth2" in self.path:
            return self._j({"access_token": "tok-de-prueba", "expires_in": 3600})
        self._j({}, 404)

    def do_GET(self):
        p = self.path
        PETICIONES.append(("GET", p))
        # --- Microsoft Graph
        if p.startswith("/users?"):
            return self._j({"value": [{"id": "u1", "userPrincipalName": "ana@empresa.com", "mail": "ana@empresa.com"}]})
        if p.startswith("/users/u1/messages?"):
            if "receivedDateTime gt" in urllib_unquote(p):
                return self._j({"value": []})     # incremental: ya no hay nada nuevo
            return self._j({"value": [{"id": "m1", "receivedDateTime": "2026-10-01T10:00:00Z"},
                                      {"id": "m2", "receivedDateTime": "2026-10-02T11:00:00Z"}]})
        if p == "/users/u1/messages/m1/$value":
            return self._b(EML1)
        if p == "/users/u1/messages/m2/$value":
            return self._b(EML2)
        if p.startswith("/users/u1/drive/root/children"):
            return self._j({"value": [{"id": "d1", "name": "factura.docx", "file": {},
                                       "lastModifiedDateTime": "2026-10-01T09:00:00Z", "size": len(DOCX)}]})
        if p == "/users/u1/drive/items/d1/content":
            return self._b(DOCX)
        # --- Google
        if p.startswith("/gmail/v1/users/") and "/messages?" in p:
            return self._j({"messages": [{"id": "g1"}]})
        if p.startswith("/gmail/v1/users/") and p.endswith("format=raw"):
            return self._j({"raw": _b64.urlsafe_b64encode(GMAIL).decode()})
        if p.startswith("/drive/v3/files?"):
            return self._j({"files": [{"id": "f1", "name": "hoja.xlsx", "modifiedTime": "2026-10-01T08:00:00Z",
                                       "size": "123", "mimeType": "application/vnd.ms-excel"}]})
        if p.startswith("/drive/v3/files/f1"):
            return self._b(b"contenido de la hoja de Drive")
        self._j({}, 404)


def urllib_unquote(s):
    import urllib.parse
    return urllib.parse.unquote(s)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"
import urllib.request as _u, time as _t
for _ in range(50):
    try:
        _u.urlopen(BASE + "/espera", timeout=1)
        break
    except urllib.error.HTTPError:
        break        # responde (404): ya está listo
    except OSError:
        _t.sleep(0.1)
os.environ.update(OCTOPUS_GRAPH_BASE=BASE, OCTOPUS_MS_LOGIN=BASE, OCTOPUS_GOOGLE_BASE=BASE,
                  OCTOPUS_GOOGLE_TOKEN=f"{BASE}/token", OCTOPUS_DATA=str(T / "data"),
                  OCTOPUS_BOVEDA_DIR=str(T / "boveda"),
                  RESTIC_REPOSITORY=str(T / "boveda" / "octopus-backups"), RESTIC_PASSWORD="prueba-nube",
                  RESTIC_CACHE_DIR=str(T / "cache"))
(T / "boveda").mkdir(parents=True)
subprocess.run([restic, "init"], check=True, capture_output=True,
               env={**os.environ, "RESTIC_REPOSITORY": os.environ["RESTIC_REPOSITORY"]})

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "lib"))
import copia_nube as nube  # noqa: E402

F = []


def chk(c, n, x=""):
    print("OK  " if c else "MAL ", n, x)
    c or F.append(n)


env = nube.os.environ  # mantenimiento.leer_env usa el .env; aquí basta con el entorno
CFG = {"microsoft": {"tenant": "t1", "client_id": "c1", "client_secret": "s1"},
       "google": {"cuenta_servicio": {"client_email": "svc@proyecto.iam", "private_key": "x"},
                  "usuarios": ["cliente@empresa.com"]}}

r = nube.copiar(dict(env), CFG)
chk(r["status"] == "success", "primera copia: OK", r.get("message", ""))
d = T / "data" / "nube"
chk((d / "microsoft" / "ana@empresa.com" / "correo" / "m1.eml").read_bytes() == EML1, "Microsoft: baja el correo como .eml idéntico")
chk((d / "microsoft" / "ana@empresa.com" / "OneDrive" / "factura.docx").read_bytes() == DOCX, "Microsoft: baja el archivo de OneDrive")
chk((d / "google" / "cliente@empresa.com" / "Gmail" / "g1.eml").read_bytes() == GMAIL, "Google: baja Gmail como .eml")
chk((d / "google" / "cliente@empresa.com" / "Drive" / "hoja.xlsx").exists(), "Google: baja el archivo de Drive")
total_ms = sum(x["nuevos"] for serv in r["detalle"] if serv["servicio"] == "microsoft" for x in serv["detalle"])
chk(total_ms == 3, "primera copia: cuenta 3 elementos nuevos de Microsoft (2 correos + 1 archivo)", total_ms)

PETICIONES.clear()
r2 = nube.copiar(dict(env), CFG)
descargas = [p for m, p in PETICIONES if "$value" in p or "/content" in p or "format=raw" in p or "alt=media" in p]
chk(r2["status"] == "success" and not descargas, "segunda copia: no vuelve a bajar nada (incremental)", (r2.get("message",""), descargas[:3]))

cps = nube.copias(dict(env))
chk(len(cps) == 2, "aparecen las copias de la nube en el almacén", len(cps))
rr = nube.restaurar(dict(env), cps[0]["id"], destino=str(T / "rescate"))
eml = list((T / "rescate").rglob("m1.eml"))
chk(rr["status"] == "success" and eml and eml[0].read_bytes() == EML1, "recuperar: el correo sale idéntico", rr.get("message", ""))
chk(nube.restaurar(dict(env), "x;rm -rf /", destino=str(T))["status"] == "error", "copia con nombre raro: rechazada")

srv.shutdown()
shutil.rmtree(T, ignore_errors=True)
print("FALLOS:", F or "ninguno")
sys.exit(1 if F else 0)
