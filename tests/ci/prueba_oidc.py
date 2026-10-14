#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""OCTOPUS - (pruebas de GitHub) entrar con OIDC contra un proveedor simulado: firma, emisor, destinatario, nonce,
estado, PKCE, grupos -> papel, y que un token falso o caducado no entra."""
import base64
import hashlib
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import funciones  # noqa: E402
import identidad  # noqa: E402

EMISOR = "https://login.ejemplo.test/tenant"
CLIENTE = "octopus-panel"
clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
V = {"oidc.emisor": EMISOR, "oidc.cliente": CLIENTE, "oidc.secreto": "s3", "oidc.campo_grupos": "groups",
     "oidc.grupo_admin": "OCTOPUS-Admin", "oidc.grupo_recuperar": "OCTOPUS-Recuperar", "oidc.grupo_lectura": "OCTOPUS-Lectura"}
funciones._leer = lambda k: V.get(k)
F = []


def chk(c, n, x=""):
    print("PASS" if c else "FAIL", n, x)
    c or F.append(n)


class R:
    def __init__(self, j, code=200):
        self._j, self.status_code = j, code

    def json(self):
        return self._j

    def raise_for_status(self):
        pass


CFG = {"issuer": EMISOR, "authorization_endpoint": EMISOR + "/authorize", "token_endpoint": EMISOR + "/token",
       "jwks_uri": EMISOR + "/keys"}
estado = {}


def token(**cambios):
    d = {"iss": EMISOR, "aud": CLIENTE, "sub": "123", "preferred_username": "ana@empresa.com", "email": "ana@empresa.com",
         "groups": ["Todos", "OCTOPUS-Admin"], "nonce": estado["nonce"], "iat": int(time.time()), "exp": int(time.time()) + 300}
    firmar = cambios.pop("_clave", clave)
    d.update(cambios)
    return jwt.encode({k: v for k, v in d.items() if v is not None}, firmar, algorithm="RS256", headers={"kid": "k1"})


class Llave:
    key = clave.public_key()


class Cliente:
    def __init__(self, *a, **k):
        pass

    def get_signing_key_from_jwt(self, t):
        return Llave()


import requests  # noqa: E402

pedido = {}
requests.get = lambda url, timeout=10: R(CFG)
siguiente = {}


def post(url, data=None, timeout=15):
    pedido.update(data)
    return R({"id_token": siguiente["t"]})


requests.post = post
jwt.PyJWKClient = Cliente

url, guardado = identidad.oidc_inicio("https://192.168.1.10:8080/login/empresa/vuelta")
q = parse_qs(urlparse(url).query)
estado.update(guardado)
chk(url.startswith(CFG["authorization_endpoint"]) and q["code_challenge_method"] == ["S256"], "manda al proveedor con PKCE")
reto = base64.urlsafe_b64encode(hashlib.sha256(guardado["verificador"].encode()).digest()).rstrip(b"=").decode()
chk(q["code_challenge"] == [reto] and q["state"] == [guardado["estado"]] and q["nonce"] == [guardado["nonce"]], "reto, estado y nonce")


def vuelta(t, state=None, **extra):
    siguiente["t"] = t
    try:
        return identidad.oidc_vuelta({"state": state or guardado["estado"], "code": "abc", **extra}, guardado), ""
    except identidad.ErrorIdentidad as exc:
        return None, str(exc)


d, e = vuelta(token())
chk(d and d["rol"] == "admin" and d["usuario"] == "ana@empresa.com", "token bueno: entra como administrador", e)
chk(pedido.get("code_verifier") == guardado["verificador"], "manda el verificador PKCE al canjear")
d, e = vuelta(token(groups=["OCTOPUS-Lectura"]))
chk(d and d["rol"] == "lectura", "grupo de lectura: solo ver")
d, e = vuelta(token(groups="OCTOPUS-Recuperar"))
chk(d and d["rol"] == "recuperar", "grupos como texto suelto")
d, e = vuelta(token(groups=["Todos"]))
chk(not d and "grupos" in e, "sin grupo: no entra", e)
d, e = vuelta(token(_clave=otra))
chk(not d and "no es válida" in e, "firmado con otra clave: no entra", e)
d, e = vuelta(token(iss="https://malo.test"))
chk(not d, "otro emisor: no entra", e)
d, e = vuelta(token(aud="otra-app"))
chk(not d, "para otra aplicación: no entra", e)
d, e = vuelta(token(exp=int(time.time()) - 3600))
chk(not d, "caducado: no entra", e)
d, e = vuelta(token(nonce="otro"))
chk(not d and "no corresponde" in e, "nonce distinto (repetición): no entra", e)
d, e = vuelta(token(), state="falso")
chk(not d and "caducado" in e, "estado falso (CSRF): no entra", e)
d, e = vuelta(token(), error="access_denied")
chk(not d and "access_denied" in e, "el proveedor dice que no")
try:
    identidad.oidc_vuelta({"state": "x", "code": "abc"}, None)
    chk(False, "sin sesión guardada: no entra")
except identidad.ErrorIdentidad:
    chk(True, "sin sesión guardada: no entra")
V["oidc.emisor"] = "http://inseguro.test"
try:
    identidad.oidc_inicio("x")
    chk(False, "proveedor sin https: se rechaza")
except identidad.ErrorIdentidad as exc:
    chk("https" in str(exc), "proveedor sin https: se rechaza")
print("FALLOS:", F or "ninguno")
sys.exit(1 if F else 0)
