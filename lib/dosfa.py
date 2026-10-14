#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Doble autenticacion (2FA) con una app del movil (Google Authenticator, Microsoft Authenticator, Authy...).

Codigos de 6 cifras que cambian cada 30 segundos (estandar TOTP, RFC 6238). Ademas:
  - 10 codigos de emergencia de un solo uso (se ensenan una vez al activar).
  - «Recordar este navegador 30 dias» (lo delicado pide el codigo igualmente).
  - El secreto de cada usuario se guarda cifrado con una clave aparte (data/dosfa.key), no en claro en la base de datos.
  - Un codigo ya usado no vale otra vez (si alguien lo ve por encima del hombro, no le sirve).

Si se pierde el movil y los codigos de emergencia (en la consola del servidor, como administrador):
    octopus.sh quitar-2fa <usuario>      (pide el codigo de recuperacion del kit de recuperacion descargado del panel)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PASO = 30                  # segundos por codigo
CIFRAS = 6
EMISOR = "OCTOPUS"
DIAS_RECORDAR = 30
N_EMERGENCIA = 10


# ------------------------------------------------------------------------------------------- TOTP (RFC 6238)
def nuevo_secreto() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _clave(secreto: str) -> bytes:
    s = secreto.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def codigo(secreto: str, instante: float | None = None, desfase: int = 0) -> str:
    paso = int((time.time() if instante is None else instante) // PASO) + desfase
    h = hmac.new(_clave(secreto), struct.pack(">Q", paso), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    n = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** CIFRAS)
    return str(n).zfill(CIFRAS)


def comprobar_totp(secreto: str, texto: str, ultimo_paso: int = 0) -> int:
    """Paso del codigo si vale (acepta el anterior y el siguiente por si el reloj va un poco desfasado); 0 si no.
    Un codigo de un paso ya usado (<= ultimo_paso) no vale otra vez."""
    t = "".join(c for c in (texto or "") if c.isdigit())
    if len(t) != CIFRAS:
        return 0
    ahora = int(time.time() // PASO)
    for d in (0, -1, 1):
        if ahora + d > ultimo_paso and hmac.compare_digest(codigo(secreto, desfase=d), t):
            return ahora + d
    return 0


def uri(usuario: str, secreto: str, servidor: str = "") -> str:
    from urllib.parse import quote
    etiqueta = quote(f"{EMISOR}{' ' + servidor if servidor else ''}:{usuario}")
    return f"otpauth://totp/{etiqueta}?secret={secreto}&issuer={quote(EMISOR)}&digits={CIFRAS}&period={PASO}"


def qr_svg(texto: str) -> str:
    """El codigo QR en SVG (se ve en el navegador sin descargar nada)."""
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    svg = img.to_string(encoding="unicode")
    return svg[svg.index("<svg"):]


# ------------------------------------------------------------------------------------------- secreto cifrado
def _ruta_clave(db_file: str) -> Path:
    return Path(db_file).resolve().parent / "dosfa.key"


def _fernet(db_file: str):
    from cryptography.fernet import Fernet
    ruta = _ruta_clave(db_file)
    if not ruta.exists():
        ruta.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(ruta), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(Fernet.generate_key())
    return Fernet(ruta.read_bytes().strip())


def cifrar(db_file: str, secreto: str) -> str:
    return _fernet(db_file).encrypt(secreto.encode()).decode()


def descifrar(db_file: str, guardado: str) -> str:
    return _fernet(db_file).decrypt(guardado.encode()).decode()


def _h(texto: str) -> str:
    return hashlib.sha256(("octopus-2fa|" + texto).encode()).hexdigest()


# ------------------------------------------------------------------------------------------- base de datos
def init(db_file: str) -> None:
    with sqlite3.connect(db_file, timeout=30) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)")]
        for col, ddl in (("totp_secreto", "TEXT"), ("totp_activo", "INTEGER DEFAULT 0"), ("totp_ultimo", "INTEGER DEFAULT 0"),
                         ("totp_emergencia", "TEXT")):
            if col not in cols:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        c.execute("CREATE TABLE IF NOT EXISTS dosfa_recordados (user_id INTEGER, huella TEXT, caduca TEXT, "
                  "PRIMARY KEY (user_id, huella))")
        c.execute("CREATE TABLE IF NOT EXISTS dosfa_recuperacion (id INTEGER PRIMARY KEY CHECK (id = 1), huella TEXT, creado TEXT)")


def _db(db_file):
    c = sqlite3.connect(db_file, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def activo(db_file: str, user_id: int) -> bool:
    with _db(db_file) as c:
        f = c.execute("SELECT totp_activo FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(f and f["totp_activo"])


def preparar(db_file: str, user_id: int) -> str:
    """Secreto nuevo pendiente de confirmar (aun no activo). Devuelve el secreto para el QR."""
    s = nuevo_secreto()
    with _db(db_file) as c:
        c.execute("UPDATE users SET totp_secreto = ?, totp_activo = 0, totp_ultimo = 0 WHERE id = ?",
                  (cifrar(db_file, s), user_id))
    return s


def secreto_pendiente(db_file: str, user_id: int) -> str | None:
    with _db(db_file) as c:
        f = c.execute("SELECT totp_secreto, totp_activo FROM users WHERE id = ?", (user_id,)).fetchone()
    if not f or not f["totp_secreto"] or f["totp_activo"]:
        return None
    return descifrar(db_file, f["totp_secreto"])


def _codigos_emergencia() -> list[str]:
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"   # sin letras que se confunden (l/1, o/0)
    return ["".join(secrets.choice(alfabeto) for _ in range(4)) + "-" + "".join(secrets.choice(alfabeto) for _ in range(4))
            for _ in range(N_EMERGENCIA)]


def confirmar(db_file: str, user_id: int, texto: str) -> list[str] | None:
    """Comprueba el primer codigo y activa. Devuelve los codigos de emergencia (para ensenarlos UNA vez) o None."""
    s = secreto_pendiente(db_file, user_id)
    if not s:
        return None
    paso = comprobar_totp(s, texto)
    if not paso:
        return None
    codigos = _codigos_emergencia()
    with _db(db_file) as c:
        c.execute("UPDATE users SET totp_activo = 1, totp_ultimo = ?, totp_emergencia = ? WHERE id = ?",
                  (paso, json.dumps([_h(x) for x in codigos]), user_id))
    return codigos


def nuevos_codigos(db_file: str, user_id: int) -> list[str]:
    codigos = _codigos_emergencia()
    with _db(db_file) as c:
        c.execute("UPDATE users SET totp_emergencia = ? WHERE id = ?", (json.dumps([_h(x) for x in codigos]), user_id))
    return codigos


def comprobar(db_file: str, user_id: int, texto: str) -> str:
    """'' si no vale; 'app' si es un codigo de la app; 'emergencia' si era un codigo de emergencia (y ya no vale mas)."""
    with _db(db_file) as c:
        f = c.execute("SELECT totp_secreto, totp_activo, totp_ultimo, totp_emergencia FROM users WHERE id = ?",
                      (user_id,)).fetchone()
        if not f or not f["totp_activo"] or not f["totp_secreto"]:
            return ""
        paso = comprobar_totp(descifrar(db_file, f["totp_secreto"]), texto, f["totp_ultimo"] or 0)
        if paso:
            c.execute("UPDATE users SET totp_ultimo = ? WHERE id = ?", (paso, user_id))
            return "app"
        t = (texto or "").strip().lower().replace(" ", "")
        if len(t) == 8 and "-" not in t:
            t = t[:4] + "-" + t[4:]
        lista = json.loads(f["totp_emergencia"] or "[]")
        if _h(t) in lista:
            lista.remove(_h(t))
            c.execute("UPDATE users SET totp_emergencia = ? WHERE id = ?", (json.dumps(lista), user_id))
            return "emergencia"
    return ""


def quedan_emergencia(db_file: str, user_id: int) -> int:
    with _db(db_file) as c:
        f = c.execute("SELECT totp_emergencia FROM users WHERE id = ?", (user_id,)).fetchone()
    return len(json.loads((f and f["totp_emergencia"]) or "[]"))


def quitar(db_file: str, user_id: int) -> None:
    with _db(db_file) as c:
        c.execute("UPDATE users SET totp_secreto = NULL, totp_activo = 0, totp_ultimo = 0, totp_emergencia = NULL, "
                  "sesion_gen = COALESCE(sesion_gen, 0) + 1 WHERE id = ?", (user_id,))
        c.execute("DELETE FROM dosfa_recordados WHERE user_id = ?", (user_id,))


# ------------------------------------------------------------------------------------------- recordar navegador
def recordar(db_file: str, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with _db(db_file) as c:
        c.execute("DELETE FROM dosfa_recordados WHERE caduca < ?", (datetime.now().isoformat(timespec="seconds"),))
        c.execute("INSERT OR REPLACE INTO dosfa_recordados VALUES (?, ?, ?)",
                  (user_id, _h(token), (datetime.now() + timedelta(days=DIAS_RECORDAR)).isoformat(timespec="seconds")))
    return token


def recordado(db_file: str, user_id: int, token: str) -> bool:
    if not token:
        return False
    with _db(db_file) as c:
        f = c.execute("SELECT caduca FROM dosfa_recordados WHERE user_id = ? AND huella = ?", (user_id, _h(token))).fetchone()
    return bool(f and f["caduca"] > datetime.now().isoformat(timespec="seconds"))


def olvidar_navegadores(db_file: str, user_id: int) -> None:
    with _db(db_file) as c:
        c.execute("DELETE FROM dosfa_recordados WHERE user_id = ?", (user_id,))


# ------------------------------------------------------------------------------------------- codigo de recuperacion (kit)
def nuevo_codigo_recuperacion(db_file: str) -> str:
    """Codigo que va SOLO en el kit descargado del panel. En el servidor se guarda solo su huella. Cada kit nuevo
    lo cambia (el de un kit anterior deja de valer)."""
    alfabeto = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    cod = "-".join("".join(secrets.choice(alfabeto) for _ in range(5)) for _ in range(5))
    with _db(db_file) as c:
        c.execute("INSERT OR REPLACE INTO dosfa_recuperacion (id, huella, creado) VALUES (1, ?, ?)",
                  (_h(cod), datetime.now().isoformat(timespec="seconds")))
    return cod


def comprobar_codigo_recuperacion(db_file: str, texto: str) -> bool:
    t = (texto or "").strip().upper().replace(" ", "")
    with _db(db_file) as c:
        f = c.execute("SELECT huella FROM dosfa_recuperacion WHERE id = 1").fetchone()
    return bool(f and hmac.compare_digest(f["huella"], _h(t)))


# ------------------------------------------------------------------------------------------- consola
def _db_por_defecto() -> str:
    import configuracion
    base = Path(__file__).resolve().parent.parent
    db = configuracion.leer_env().get("DB_PATH", "./data/admin_panel.db")
    return db if os.path.isabs(db) else str((base / db).resolve())


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "quitar":
        print(__doc__)
        return 2
    import getpass
    import registro
    db = _db_por_defecto()
    init(db)
    with _db(db) as c:
        u = c.execute("SELECT id, username FROM users WHERE username = ?", (argv[2],)).fetchone()
    if not u:
        print(f"No existe el usuario «{argv[2]}».")
        return 1
    if not activo(db, u["id"]):
        print(f"«{u['username']}» no tiene la doble autenticación activada.")
        return 0
    print("Para quitar la doble autenticación hace falta el CÓDIGO DE RECUPERACIÓN del último kit de recuperación")
    print("descargado desde el panel (Ajustes → Kit de recuperación). Se avisará a todos los administradores.")
    for intento in range(3):
        texto = getpass.getpass("Código de recuperación (no se ve al escribir): ")
        if comprobar_codigo_recuperacion(db, texto):
            break
        registro.escribir(db, None, "2FA_QUITAR_FALLIDO", f"{u['username']}: código de recuperación incorrecto (consola)")
        print("Ese código no es el del último kit." + (" Prueba otra vez." if intento < 2 else ""))
        time.sleep(2 + intento * 3)
    else:
        return 1
    quitar(db, u["id"])
    registro.escribir(db, None, "2FA_QUITADA", f"{u['username']}: quitada desde la consola del servidor con el código del kit")
    try:   # aviso a los administradores (correo y Telegram)
        import config_manager
        import notifications
        import telegram_integration
        cm = config_manager.ConfigManager(db)
        texto = (f"OCTOPUS: se ha quitado la doble autenticación del usuario «{u['username']}» desde la consola del "
                 f"servidor ({datetime.now():%d/%m/%Y %H:%M}). Si no has sido tú, revisa quién tiene acceso al servidor.")
        notifications.NotificationManager(cm).send_alert("acceso", texto)
        telegram_integration.TelegramIntegration(cm).send_alert("acceso", texto)
    except Exception:
        pass
    print(f"Hecho. «{u['username']}» entra solo con su contraseña y tendrá que volver a activar la doble autenticación.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
