# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# El limite de peticiones protege el login sin estorbar: recargar el login no cuenta, enviar muchas veces si,
# y un administrador que mira la monitorizacion en directo (cientos de peticiones por hora) nunca se queda fuera.
import os, re, sys, tempfile

d = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(d, "limite.db"))
os.environ.setdefault("OCTOPUS_DATA", os.path.join(d, "datos"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib"))
import admin_panel as a  # noqa: E402

assert a.Limiter is not None, "flask-limiter no esta instalado: el limite de peticiones estaria apagado"
a.app.config["TESTING"] = False
# Esta prueba es del LIMITE DE PETICIONES (una capa). El bloqueo de atacantes por IP es OTRA capa (su propia
# prueba es prueba_seguridad). Aqui se apaga para no mezclar las dos: si no, los intentos fallidos bloquearian la IP.
a.config_manager.set_config("bloqueo_atacantes", False, None)
fallos = []


def chk(c, n, x=""):
    print("OK  " if c else "MAL ", n, x)
    c or fallos.append(n)


def cliente(ip):
    c = a.app.test_client()
    c.environ_base["REMOTE_ADDR"] = ip
    return c


c = cliente("10.9.8.7")
r = [c.get("/login").status_code for _ in range(20)]
chk(429 not in r, "recargar la pagina de entrar 20 veces: no bloquea", set(r))


def enviar(c):
    t = re.search(r'name="csrf_token" value="([^"]+)"', c.get("/login").get_data(as_text=True)).group(1)
    return c.post("/login", data={"csrf_token": t, "username": "nadie", "password": "x"})


r = [enviar(c).status_code for _ in range(12)]
chk(429 not in r[:10] and r[-1] == 429, "mas de 10 envios por minuto desde una direccion: 429", r)
chk("Demasiados intentos" in enviar(c).get_data(as_text=True), "el 429 se explica en castellano")
c2 = cliente("10.9.8.8")
with c2.session_transaction() as s:
    s["user_id"] = 1
r = [c2.get("/api/monitor/resumen").status_code for _ in range(400)]
chk(429 not in r, "con sesion: 400 peticiones (monitorizacion en directo) sin limite", set(r))
c3 = cliente("10.9.8.9")
r = [c3.get("/inicio").status_code for _ in range(320)]
chk(429 in r, "sin sesion: mas de 300 peticiones por hora se cortan", set(r))
c4 = cliente("127.0.0.1")
r = [enviar(c4).status_code for _ in range(15)]
chk(429 not in r, "el propio servidor nunca se limita", set(r))
print("FALLOS:", fallos or "ninguno")
sys.exit(1 if fallos else 0)
