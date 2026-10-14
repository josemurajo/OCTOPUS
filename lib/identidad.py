#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Entrar al panel con los usuarios que ya tiene la empresa (Ajustes -> Funciones -> Usuarios de la empresa).

  - Active Directory / LDAP  (ldap3, sin programas aparte)
  - RADIUS                   (PAP, RFC 2865; cliente propio, sin dependencias)
  - OIDC                     (Microsoft 365 / Entra, Google, Authentik, Keycloak...: flujo con codigo + PKCE)

Reglas de seguridad:
  - Los usuarios locales de OCTOPUS (el administrador principal y los creados en Ajustes -> Usuarios) siempre entran
    con su contrasena local: un usuario de la empresa con el mismo nombre NUNCA puede suplantarlos.
  - El papel (administrador / solo recuperar / solo ver) sale de los grupos de la empresa en cada acceso.
    Quien no esta en ninguno de los grupos elegidos no entra.
  - Las contrasenas nunca se guardan; solo se usan para preguntar al servidor de la empresa.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import socket
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import funciones  # noqa: E402

ROLES_POR_GRUPO = (("grupo_admin", "admin"), ("grupo_recuperar", "recuperar"), ("grupo_lectura", "lectura"))


class ErrorIdentidad(Exception):
    """Mensaje claro para la pantalla de acceso (sin datos internos)."""


def _rol_por_grupos(proveedor: str, grupos: list[str]) -> str | None:
    """El papel mas alto de los grupos de la empresa a los que pertenece (None = ninguno)."""
    def corto(g: str) -> str:
        g = (g or "").strip()
        # "CN=OCTOPUS-Admin,OU=Grupos,DC=empresa,DC=local" -> "octopus-admin"
        if g.upper().startswith("CN="):
            g = g[3:].split(",", 1)[0]
        return g.lower()
    tiene = {corto(g) for g in grupos}
    for opcion, rol in ROLES_POR_GRUPO:
        nombre = str(funciones.opcion(proveedor, opcion) or "").strip().lower()
        if nombre and nombre in tiene:
            return rol
    return None


# ------------------------------------------------------------------------------------------------------- LDAP / AD
def _escapar_ldap(texto: str) -> str:
    """Escapa un valor para un filtro LDAP (RFC 4515): que nadie pueda colar un filtro con su nombre de usuario."""
    return "".join({"*": r"\2a", "(": r"\28", ")": r"\29", "\\": r"\5c", "\0": r"\00"}.get(c, c) for c in texto)


def ldap_entrar(usuario: str, password: str) -> dict:
    """{'usuario', 'correo', 'rol'} o ErrorIdentidad."""
    if not password:
        raise ErrorIdentidad("Escribe la contraseña.")    # LDAP acepta binds sin contraseña como anónimos: nunca
    try:
        import ldap3
        from ldap3.core.exceptions import LDAPException
    except ImportError:
        raise ErrorIdentidad("Falta la librería ldap3 en el servidor (reinstala OCTOPUS).") from None
    servidor = str(funciones.opcion("ldap", "servidor") or "").strip()
    base = str(funciones.opcion("ldap", "base") or "").strip()
    if not servidor or not base:
        raise ErrorIdentidad("El acceso con usuarios de la empresa no está terminado de configurar.")
    lector = str(funciones.opcion("ldap", "usuario_lectura") or "").strip()
    clave_lector = str(funciones.opcion("ldap", "password_lectura") or "")
    try:
        srv = ldap3.Server(servidor, get_info=ldap3.NONE, connect_timeout=8)
        if lector:
            busca = ldap3.Connection(srv, user=lector, password=clave_lector, auto_bind=True, receive_timeout=10)
        else:   # sin usuario de lectura: se busca con el propio usuario (formato usuario@dominio en AD)
            dominio = ".".join(p.split("=", 1)[1] for p in base.split(",") if p.strip().upper().startswith("DC="))
            busca = ldap3.Connection(srv, user=usuario if "@" in usuario or "\\" in usuario else f"{usuario}@{dominio}",
                                     password=password, auto_bind=True, receive_timeout=10)
        nombre = usuario.split("\\")[-1].split("@")[0]
        filtro = f"(|(sAMAccountName={_escapar_ldap(nombre)})(uid={_escapar_ldap(nombre)})(userPrincipalName={_escapar_ldap(usuario)}))"
        busca.search(base, filtro, attributes=["mail", "memberOf", "sAMAccountName", "uid"], size_limit=2)
        if len(busca.entries) != 1:
            raise ErrorIdentidad("Usuario o contraseña incorrectos.")
        e = busca.entries[0]
        dn = e.entry_dn
        busca.unbind()
        # comprobar la contraseña del propio usuario (aunque se haya buscado con el de lectura)
        yo = ldap3.Connection(srv, user=dn, password=password, receive_timeout=10)
        if not yo.bind():
            raise ErrorIdentidad("Usuario o contraseña incorrectos.")
        yo.unbind()
    except ErrorIdentidad:
        raise
    except LDAPException as exc:
        if "invalidCredentials" in str(exc) or "bind" in exc.__class__.__name__.lower():
            raise ErrorIdentidad("Usuario o contraseña incorrectos.") from None
        raise ErrorIdentidad("No se puede hablar con el servidor de usuarios de la empresa. Entra con el usuario local "
                             "de OCTOPUS.") from None
    grupos = [str(g) for g in (e.memberOf.values if "memberOf" in e else [])]
    rol = _rol_por_grupos("ldap", grupos)
    if not rol:
        raise ErrorIdentidad("Tu usuario de la empresa no está en ninguno de los grupos que pueden entrar a OCTOPUS.")
    correo = str(e.mail.value) if "mail" in e and e.mail.value else ""
    return {"usuario": nombre, "correo": correo, "rol": rol}


# ------------------------------------------------------------------------------------------------------- RADIUS
def _radius_paquete(usuario: str, password: str, secreto: bytes, ident: int, autenticador: bytes) -> bytes:
    def atributo(tipo: int, valor: bytes) -> bytes:
        return struct.pack("!BB", tipo, len(valor) + 2) + valor
    # User-Password (RFC 2865 5.2): la contraseña va mezclada con MD5(secreto + autenticador)
    clave = password.encode("utf-8")[:128]
    clave += b"\0" * (-len(clave) % 16 or (16 if not clave else 0))
    oculta, anterior = b"", autenticador
    for i in range(0, len(clave), 16):
        b = hashlib.md5(secreto + anterior).digest()
        trozo = bytes(x ^ y for x, y in zip(clave[i:i + 16], b))
        oculta += trozo
        anterior = trozo
    attrs = atributo(1, usuario.encode("utf-8")[:253]) + atributo(2, oculta) + atributo(4, socket.inet_aton("127.0.0.1"))
    # Message-Authenticator (RFC 3579): protege la peticion; muchos servidores modernos lo exigen (BlastRADIUS)
    sin_firma = attrs + atributo(80, b"\0" * 16)
    cab = struct.pack("!BBH", 1, ident, 20 + len(sin_firma)) + autenticador
    firma = hmac.new(secreto, cab + sin_firma, hashlib.md5).digest()
    return cab + attrs + atributo(80, firma)


def radius_entrar(usuario: str, password: str) -> dict:
    servidor = str(funciones.opcion("radius", "servidor") or "").strip()
    secreto = str(funciones.opcion("radius", "secreto") or "").encode()
    if not servidor or not secreto:
        raise ErrorIdentidad("El acceso por RADIUS no está terminado de configurar.")
    if not password:
        raise ErrorIdentidad("Escribe la contraseña.")
    puerto = int(funciones.opcion("radius", "puerto") or 1812)
    ident, autenticador = secrets.randbelow(256), os.urandom(16)
    paquete = _radius_paquete(usuario, password, secreto, ident, autenticador)
    try:
        destino = socket.getaddrinfo(servidor, puerto, socket.AF_UNSPEC, socket.SOCK_DGRAM)[0]
        with socket.socket(destino[0], socket.SOCK_DGRAM) as s:
            s.settimeout(4)
            for _ in range(3):
                s.sendto(paquete, destino[4])
                try:
                    resp, _ = s.recvfrom(4096)
                except socket.timeout:
                    continue
                if len(resp) < 20 or resp[1] != ident:
                    continue
                codigo, _, largo = struct.unpack("!BBH", resp[:4])
                # el servidor demuestra que conoce el secreto: MD5(cabecera + autenticador de la peticion + atributos + secreto)
                esperado = hashlib.md5(resp[:4] + autenticador + resp[20:largo] + secreto).digest()
                if not hmac.compare_digest(esperado, resp[4:20]):
                    raise ErrorIdentidad("El servidor RADIUS no ha contestado bien (¿secreto compartido distinto?).")
                if codigo == 2:
                    return {"usuario": usuario, "correo": "", "rol": str(funciones.opcion("radius", "rol") or "lectura")}
                raise ErrorIdentidad("Usuario o contraseña incorrectos.")
    except OSError:
        pass
    raise ErrorIdentidad("El servidor RADIUS no contesta (¿está encendido? ¿el secreto compartido es el mismo en los dos "
                         "lados?). Entra con el usuario local de OCTOPUS.")


# ------------------------------------------------------------------------------------------------------- OIDC
_DESCUBRIMIENTO: dict = {}


def _oidc_config() -> dict:
    import requests
    emisor = str(funciones.opcion("oidc", "emisor") or "").strip().rstrip("/")
    if not emisor.startswith("https://"):
        raise ErrorIdentidad("La dirección del proveedor (issuer) tiene que empezar por https://")
    if emisor not in _DESCUBRIMIENTO:
        r = requests.get(emisor + "/.well-known/openid-configuration", timeout=10)
        r.raise_for_status()
        cfg = r.json()
        if cfg.get("issuer", "").rstrip("/") != emisor:
            raise ErrorIdentidad("El proveedor dice ser otro (issuer distinto): revisa la dirección.")
        _DESCUBRIMIENTO[emisor] = cfg
    return _DESCUBRIMIENTO[emisor]


def oidc_inicio(vuelta: str) -> tuple[str, dict]:
    """(direccion a la que mandar al usuario, datos que guardar en su sesion)."""
    from urllib.parse import urlencode
    cfg = _oidc_config()
    estado, nonce, verificador = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    reto = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    q = {"response_type": "code", "client_id": funciones.opcion("oidc", "cliente"), "redirect_uri": vuelta,
         "scope": "openid email profile", "state": estado, "nonce": nonce,
         "code_challenge": reto, "code_challenge_method": "S256"}
    return cfg["authorization_endpoint"] + "?" + urlencode(q), {"estado": estado, "nonce": nonce,
                                                                "verificador": verificador, "vuelta": vuelta}


def oidc_vuelta(args: dict, guardado: dict) -> dict:
    import jwt
    import requests
    if not guardado or not secrets.compare_digest(str(args.get("state", "")), str(guardado.get("estado", ""))):
        raise ErrorIdentidad("El acceso ha caducado o no viene de aquí. Vuelve a pulsar el botón.")
    if args.get("error"):
        raise ErrorIdentidad("El proveedor no ha dejado entrar: " + str(args.get("error_description") or args["error"])[:150])
    cfg = _oidc_config()
    r = requests.post(cfg["token_endpoint"], timeout=15, data={
        "grant_type": "authorization_code", "code": args.get("code", ""), "redirect_uri": guardado["vuelta"],
        "client_id": funciones.opcion("oidc", "cliente"), "client_secret": funciones.opcion("oidc", "secreto"),
        "code_verifier": guardado["verificador"]})
    if r.status_code != 200:
        raise ErrorIdentidad("El proveedor no ha aceptado el acceso (revisa el ID y el secreto de cliente).")
    id_token = r.json().get("id_token", "")
    clave = jwt.PyJWKClient(cfg["jwks_uri"], timeout=10).get_signing_key_from_jwt(id_token)
    try:
        datos = jwt.decode(id_token, clave.key, algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"],
                           audience=funciones.opcion("oidc", "cliente"), issuer=cfg["issuer"], leeway=60)
    except jwt.PyJWTError:
        raise ErrorIdentidad("La respuesta del proveedor no es válida (firma, fecha o destinatario).") from None
    if not secrets.compare_digest(str(datos.get("nonce", "")), guardado["nonce"]):
        raise ErrorIdentidad("La respuesta del proveedor no corresponde a este acceso.")
    campo = str(funciones.opcion("oidc", "campo_grupos") or "groups")
    grupos = datos.get(campo) or []
    if isinstance(grupos, str):
        grupos = [grupos]
    rol = _rol_por_grupos("oidc", [str(g) for g in grupos])
    if not rol:
        raise ErrorIdentidad("Tu cuenta no está en ninguno de los grupos que pueden entrar a OCTOPUS.")
    usuario = str(datos.get("preferred_username") or datos.get("email") or datos.get("sub"))
    return {"usuario": usuario[:60], "correo": str(datos.get("email") or ""), "rol": rol}


# ------------------------------------------------------------------------------------------------------- comun
def entrar_con_contrasena(usuario: str, password: str) -> tuple[dict | None, str, str]:
    """Prueba los proveedores con usuario y contraseña encendidos. (datos, proveedor, error)."""
    error = ""
    for proveedor, f in (("ldap", ldap_entrar), ("radius", radius_entrar)):
        if funciones.activa(proveedor):
            try:
                return f(usuario, password), proveedor, ""
            except ErrorIdentidad as exc:
                error = str(exc)
    return None, "", error


def usuario_local(db_file: str, datos: dict, proveedor: str) -> tuple[int | None, str]:
    """El usuario del panel que corresponde (se crea o se actualiza su papel). (id, error)."""
    import sqlite3
    nombre = f"{datos['usuario']}"
    c = sqlite3.connect(db_file, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        u = c.execute("SELECT id, origen FROM users WHERE lower(username) = lower(?)", (nombre,)).fetchone()
        if u and (u["origen"] or "local") == "local":
            return None, ("Ya hay un usuario local de OCTOPUS con ese nombre: entra con su contraseña de OCTOPUS.")
        correo = datos.get("correo") or f"{nombre}@{proveedor}.octopus"
        if u:
            c.execute("UPDATE users SET role = ?, origen = ?, email = ? WHERE id = ?", (datos["rol"], proveedor, correo, u["id"]))
            uid = u["id"]
        else:
            if c.execute("SELECT 1 FROM users WHERE lower(email) = lower(?)", (correo,)).fetchone():
                correo = f"{nombre}@{proveedor}.octopus"
            # contraseña local imposible: estos usuarios solo entran por su proveedor
            cur = c.execute("INSERT INTO users (username, email, password_hash, role, must_change_password, origen) "
                            "VALUES (?, ?, ?, ?, 0, ?)", (nombre, correo, "!" + secrets.token_hex(16), datos["rol"], proveedor))
            uid = cur.lastrowid
        c.commit()
        return uid, ""
    finally:
        c.close()
