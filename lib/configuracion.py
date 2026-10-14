# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS Zero-Touch - Configuracion del servidor (se ejecuta al arrancar el contenedor).

Crea lo que falte, sin tocar lo que ya existe:
  .env               claves generadas al azar (solo la primera vez) + migraciones de versiones antiguas
  data/tls           certificado HTTPS propio del panel
  boveda.htpasswd    usuario del almacen de copias (rest-server)
  ansible/config.json  configuracion base de los agentes
"""
from __future__ import annotations

import json
import os
import re
import secrets
import string
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def secreto(n: int = 32) -> str:
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(n))


def leer_env() -> dict:
    data = {}
    if ENV_FILE.is_file():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def fijar(clave: str, valor: str) -> None:
    lineas = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.is_file() else []
    lineas = [l for l in lineas if not l.startswith(clave + "=")] + [f"{clave}={valor}"]
    _escribir(ENV_FILE, "\n".join(lineas) + "\n")


def _escribir(ruta: Path, texto: str, modo: int = 0o600) -> None:
    ruta = Path(os.path.realpath(ruta))  # si es un enlace (contenedor: /app/.env -> /data/.env) se escribe el destino
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, modo)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(texto)
    os.replace(tmp, ruta)
    try:
        os.chmod(ruta, modo)
    except OSError:
        pass


def crear_env() -> bool:
    """Devuelve True si se ha creado ahora (primera instalacion)."""
    if ENV_FILE.is_file() and ENV_FILE.stat().st_size > 0:
        return False
    rest_pass = secreto(32)
    ip = os.environ.get("OCTOPUS_IP", "")
    _escribir(ENV_FILE, f"""# OCTOPUS Zero-Touch - configuracion del servidor (generada {time.strftime('%Y-%m-%d %H:%M')})
# Las claves se generan al azar. NO las pierdas: descarga el kit de recuperacion desde el panel (Ajustes).

# Direccion con la que los equipos llegan a este servidor (la fija el instalador; para equipos fuera de la
# oficina pon un nombre DNS o IP publica en OCTOPUS_PUBLIC_HOST y abre los puertos del panel y del almacen)
OCTOPUS_IP={ip}
OCTOPUS_PUBLIC_HOST=

# Panel
ADMIN_PASSWORD={secreto(24)}
ADMIN_EMAIL=admin@empresa.local
FLASK_SECRET_KEY={secreto(48)}
ADMIN_PORT=8080
DB_PATH=./data/admin_panel.db

# Almacen de copias (restic rest-server, modo solo-anadir)
REST_USER=octopus
REST_PASSWORD={rest_pass}
RESTIC_PASSWORD={secreto(32)}
RESTIC_REPOSITORY=rest:https://octopus:{rest_pass}@127.0.0.1:8000/octopus-backups
RESTIC_REPOSITORY_CUARENTENA=rest:https://octopus:{rest_pass}@127.0.0.1:8000/octopus-cuarentena
RESTIC_PASSWORD_CUARENTENA={secreto(32)}

# Agentes
OCTOPUS_AGENT_TOKEN={secreto(32)}

# Almacen externo (muy recomendado): cada noche se envia alli una copia del servidor y TODAS las copias de los
# equipos (solo lo nuevo). Si se pierde el disco del servidor, todo sigue alli. Ejemplos:
#   OFFSITE_RESTIC_REPOSITORY=sftp:usuario@otro-servidor:/copias/octopus
#   OFFSITE_RESTIC_REPOSITORY=s3:https://s3.amazonaws.com/mi-bucket/octopus  (+ OFFSITE_AWS_ACCESS_KEY_ID / OFFSITE_AWS_SECRET_ACCESS_KEY)
OFFSITE_RESTIC_REPOSITORY=
OFFSITE_RESTIC_PASSWORD=
# OFFSITE_COPIAR_EQUIPOS=no   para enviar al externo solo la copia del servidor (no las de los equipos)

# Avisos (se configuran desde el panel)
SMTP_ENABLED=false
TELEGRAM_ENABLED=false
""")
    return True


def migrar_env() -> None:
    """Instalaciones anteriores: rellena claves nuevas sin tocar las existentes."""
    env = leer_env()
    if not env.get("REST_USER"):
        fijar("REST_USER", "octopus")
    if not env.get("REST_PASSWORD"):
        m = re.match(r"rest:https?://[^:]+:([^@]+)@", env.get("RESTIC_REPOSITORY", ""))
        fijar("REST_PASSWORD", m.group(1) if m else secreto(32))
    env = leer_env()
    repo = env.get("RESTIC_REPOSITORY", "")
    if not repo.startswith("rest:"):
        fijar("RESTIC_REPOSITORY", f"rest:https://{env['REST_USER']}:{env['REST_PASSWORD']}@127.0.0.1:8000/octopus-backups")
    if not env.get("RESTIC_REPOSITORY_CUARENTENA"):
        fijar("RESTIC_REPOSITORY_CUARENTENA", leer_env()["RESTIC_REPOSITORY"].rsplit("/", 1)[0] + "/octopus-cuarentena")
    # el almacen va siempre cifrado (HTTPS) y en el propio servidor se le habla por 127.0.0.1
    for k in ("RESTIC_REPOSITORY", "RESTIC_REPOSITORY_CUARENTENA"):
        v = leer_env().get(k, "")
        nuevo = re.sub(r"^rest:http://", "rest:https://", re.sub(r"@[^@/]+:8000/", "@127.0.0.1:8000/", v))
        if nuevo != v:
            fijar(k, nuevo)
    fijar("RESTIC_CACERT", str((BASE_DIR / "data" / "tls" / "ca.crt").resolve()))
    for k, var in (("OCTOPUS_PUERTO_PANEL", "OCTOPUS_PUERTO_PANEL"), ("OCTOPUS_PUERTO_ALMACEN", "OCTOPUS_PUERTO_ALMACEN")):
        if os.environ.get(var) and leer_env().get(k) != os.environ[var]:
            fijar(k, os.environ[var])
    for k, n in (("RESTIC_PASSWORD_CUARENTENA", 32), ("OCTOPUS_AGENT_TOKEN", 32), ("FLASK_SECRET_KEY", 48)):
        if not env.get(k):
            fijar(k, secreto(n))
    if os.environ.get("OCTOPUS_IP") and not env.get("OCTOPUS_IP"):
        fijar("OCTOPUS_IP", os.environ["OCTOPUS_IP"])
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def htpasswd(ruta: Path) -> None:
    """Usuario del almacen (bcrypt, formato que entiende rest-server)."""
    env = leer_env()
    usuario, clave = env["REST_USER"], env["REST_PASSWORD"]
    try:
        import bcrypt
    except ImportError:  # solo en entornos de prueba sin bcrypt: formato {SHA} (rest-server tambien lo acepta)
        import base64
        import hashlib
        _escribir(ruta, f"{usuario}:{{SHA}}{base64.b64encode(hashlib.sha1(clave.encode()).digest()).decode()}\n")
        return
    if ruta.is_file():
        linea = ruta.read_text(encoding="utf-8").strip().split("\n")[0]
        if linea.startswith(usuario + ":"):
            h = linea.split(":", 1)[1].replace("$2y$", "$2b$", 1)
            try:
                if bcrypt.checkpw(clave.encode(), h.encode()):
                    return
            except ValueError:
                pass  # formato antiguo o estropeado ({SHA}, a medias...): se vuelve a crear abajo
    h = bcrypt.hashpw(clave.encode(), bcrypt.gensalt(rounds=10)).decode().replace("$2b$", "$2y$", 1)
    _escribir(ruta, f"{usuario}:{h}\n")


def _clave_rsa():
    from cryptography.hazmat.primitives.asymmetric import rsa
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def _guardar_clave(ruta: Path, clave) -> None:
    from cryptography.hazmat.primitives import serialization
    _escribir_bytes(ruta, clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                              serialization.NoEncryption()), 0o600)


def _escribir_bytes(ruta: Path, datos: bytes, modo: int = 0o644) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, modo)
    with os.fdopen(fd, "wb") as fh:
        fh.write(datos)
    os.replace(tmp, ruta)
    try:
        os.chmod(ruta, modo)
    except OSError:
        pass


def nombres_servidor() -> list[str]:
    """Nombres/IPs con los que se llega al servidor: deben ir en el certificado."""
    env = leer_env()
    nombres = ["DNS:localhost", "IP:127.0.0.1"]
    extra = ([env.get("OCTOPUS_IP"), env.get("OCTOPUS_PUBLIC_HOST")] + env.get("OCTOPUS_NOMBRES_EXTRA", "").split(",")
             + os.environ.get("OCTOPUS_NOMBRES_EXTRA", "").split(","))
    for h in extra:
        h = (h or "").strip()
        if h:
            nombres.append(("IP:" if re.match(r"^[0-9.]+$|^[0-9a-fA-F:]+:[0-9a-fA-F:]*$", h) else "DNS:") + h)
    return list(dict.fromkeys(nombres))


def certificado_tls() -> None:
    """Autoridad propia de OCTOPUS + certificado del servidor firmado por ella.
    Los agentes solo confian en esta autoridad. Si cambia la IP o el nombre del servidor se emite otro
    certificado con la misma autoridad y los equipos siguen confiando sin tocarlos.
    Se hace con la libreria `cryptography` (sin el programa openssl), asi funciona igual en Linux, Mac y Windows."""
    import datetime as _dt
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    tls = BASE_DIR / "data" / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    ca_crt, ca_key = tls / "ca.crt", tls / "ca.key"
    crt, key, san_file = tls / "panel.crt", tls / "panel.key", tls / "nombres.txt"
    ahora = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=5)
    nueva_ca = False
    if not (ca_crt.is_file() and ca_key.is_file()):
        clave_ca = _clave_rsa()
        nombre_ca = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OCTOPUS Autoridad privada")])
        cert_ca = (x509.CertificateBuilder().subject_name(nombre_ca).issuer_name(nombre_ca)
                   .public_key(clave_ca.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(ahora).not_valid_after(ahora + _dt.timedelta(days=3650))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                                crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(clave_ca.public_key()), critical=False)
                   .sign(clave_ca, hashes.SHA256()))
        _guardar_clave(ca_key, clave_ca)
        _escribir_bytes(ca_crt, cert_ca.public_bytes(serialization.Encoding.PEM))
        nueva_ca = True
    nombres = ",".join(nombres_servidor())
    vigente = crt.is_file() and key.is_file() and san_file.is_file() and san_file.read_text().strip() == nombres
    if vigente and not nueva_ca:
        return
    clave_ca = serialization.load_pem_private_key(ca_key.read_bytes(), password=None)
    cert_ca = x509.load_pem_x509_certificate(ca_crt.read_bytes())
    alt = []
    for n in nombres.split(","):
        tipo, _, valor = n.partition(":")
        if tipo == "IP":
            try:
                alt.append(x509.IPAddress(ipaddress.ip_address(valor)))
            except ValueError:
                continue
        elif valor:
            alt.append(x509.DNSName(valor))
    clave = _clave_rsa()
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OCTOPUS")]))
            .issuer_name(cert_ca.subject).public_key(clave.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(ahora).not_valid_after(ahora + _dt.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(clave_ca.public_key()), critical=False)
            .sign(clave_ca, hashes.SHA256()))
    _guardar_clave(key, clave)
    _escribir_bytes(crt, cert.public_bytes(serialization.Encoding.PEM))
    san_file.write_text(nombres)


def caducidad(crt: Path) -> int | None:
    """Dias que le quedan a un certificado (None si no se puede leer)."""
    import datetime as _dt
    from cryptography import x509
    try:
        cert = x509.load_pem_x509_certificate(crt.read_bytes())
    except (OSError, ValueError):
        return None
    fin = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=_dt.timezone.utc)
    return int((fin - _dt.datetime.now(_dt.timezone.utc)).total_seconds() // 86400)


def config_agentes() -> dict:
    """Base de la configuracion de cada agente (cada equipo recibe ademas su nombre y su propia clave)."""
    env = leer_env()
    servidor = env.get("OCTOPUS_PUBLIC_HOST") or env.get("OCTOPUS_IP", "")
    p_panel = env.get("OCTOPUS_PUERTO_PANEL", "8080")
    p_almacen = env.get("OCTOPUS_PUERTO_ALMACEN", "8000")

    def externo(url: str) -> str:
        return re.sub(r"@[^@/]+:8000/", f"@{servidor}:{p_almacen}/", url)

    ca = BASE_DIR / "data" / "tls" / "ca.crt"
    cfg = {
        "servidor": servidor,
        "ip_cerebro": servidor,
        "panel_url": f"https://{servidor}:{p_panel}",
        "ca_pem": ca.read_text(encoding="utf-8") if ca.is_file() else "",
        "password_restic": env.get("RESTIC_PASSWORD", ""),
        "restic_repository": externo(env.get("RESTIC_REPOSITORY", "")),
        "restic_repository_cuarentena": externo(env.get("RESTIC_REPOSITORY_CUARENTENA", "")),
        "password_cuarentena": env.get("RESTIC_PASSWORD_CUARENTENA", ""),
        "backup_paths": [],
    }
    _escribir(BASE_DIR / "ansible" / "config.json", json.dumps(cfg, indent=2))
    return cfg


def credenciales_iniciales(primera_vez: bool) -> None:
    if not primera_vez:
        return
    env = leer_env()
    host = env.get("OCTOPUS_PUBLIC_HOST") or env.get("OCTOPUS_IP") or "IP-del-servidor"
    _escribir(BASE_DIR / "data" / "CREDENCIALES_INICIALES.txt",
              f"OCTOPUS - acceso inicial\n\nPanel: https://{host}:{env.get('ADMIN_PORT', '8080')}\nUsuario: admin\n"
              f"Contrasena (de un solo uso): {env['ADMIN_PASSWORD']}\n\n"
              "El panel te pedira cambiarla al entrar. Descarga despues el KIT DE RECUPERACION (Ajustes).\n")


def preparar(htpasswd_ruta: Path) -> None:
    primera = crear_env()
    migrar_env()
    htpasswd(htpasswd_ruta)
    certificado_tls()
    config_agentes()
    credenciales_iniciales(primera)
