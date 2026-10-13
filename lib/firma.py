#!/usr/bin/env python3
"""
OCTOPUS - Comprobar que una version descargada es la oficial (lo usa el actualizador cuando no hay ssh-keygen,
por ejemplo en Windows).

Hace lo mismo que `ssh-keygen -Y verify`: comprueba la firma SSH (formato SSHSIG, clave ed25519) del MANIFIESTO con
la clave de publicacion de ESTA instalacion, y despues que cada archivo descargado tiene la huella SHA-256 que dice
el MANIFIESTO y que no sobra ni falta ninguno.

  python firma.py verificar <clave.pub> <carpeta>     -> codigo 0 si todo es correcto; si no, explica por que
  python firma.py version-mayor <nueva> <actual>      -> codigo 0 si la nueva es mas nueva
"""
from __future__ import annotations

import base64
import hashlib
import os
import struct
import sys
from pathlib import Path

ESPACIO = b"octopus-version"


def _cadena(datos: bytes, pos: int) -> tuple[bytes, int]:
    if pos + 4 > len(datos):
        raise ValueError("firma cortada")
    n = struct.unpack(">I", datos[pos:pos + 4])[0]
    if pos + 4 + n > len(datos):
        raise ValueError("firma cortada")
    return datos[pos + 4:pos + 4 + n], pos + 4 + n


def _s(b: bytes) -> bytes:
    return struct.pack(">I", len(b)) + b


def clave_publica(texto: str) -> bytes:
    """El blob de la clave publica (formato OpenSSH «ssh-ed25519 AAAA... comentario»)."""
    for linea in texto.splitlines():
        partes = linea.strip().split()
        if len(partes) >= 2 and partes[0] == "ssh-ed25519":
            return base64.b64decode(partes[1])
    raise ValueError("la clave de publicacion no es una clave ssh-ed25519")


def verificar_firma(pub_texto: str, mensaje: bytes, firma_armada: str) -> None:
    """Lanza ValueError si la firma no es valida para esa clave y ese mensaje."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    lineas = [l.strip() for l in firma_armada.strip().splitlines()]
    if not lineas or lineas[0] != "-----BEGIN SSH SIGNATURE-----" or lineas[-1] != "-----END SSH SIGNATURE-----":
        raise ValueError("el archivo de firma no tiene el formato de ssh-keygen")
    blob = base64.b64decode("".join(lineas[1:-1]))
    if blob[:6] != b"SSHSIG":
        raise ValueError("no es una firma SSHSIG")
    version = struct.unpack(">I", blob[6:10])[0]
    if version != 1:
        raise ValueError(f"version de firma no soportada ({version})")
    pos = 10
    pub_firma, pos = _cadena(blob, pos)
    espacio, pos = _cadena(blob, pos)
    reservado, pos = _cadena(blob, pos)
    hash_alg, pos = _cadena(blob, pos)
    firma, pos = _cadena(blob, pos)
    esperada = clave_publica(pub_texto)
    if pub_firma != esperada:
        raise ValueError("la version esta firmada con OTRA clave, no con la de publicacion de OCTOPUS")
    if espacio != ESPACIO:
        raise ValueError("la firma es para otro uso (espacio de nombres distinto)")
    if hash_alg not in (b"sha512", b"sha256"):
        raise ValueError("algoritmo de huella no soportado")
    tipo, p2 = _cadena(firma, 0)
    bruta, _ = _cadena(firma, p2)
    if tipo != b"ssh-ed25519":
        raise ValueError("tipo de firma no soportado (solo ed25519)")
    t, p3 = _cadena(esperada, 0)
    clave_bytes, _ = _cadena(esperada, p3)
    h = (hashlib.sha512 if hash_alg == b"sha512" else hashlib.sha256)(mensaje).digest()
    firmado = b"SSHSIG" + _s(espacio) + _s(reservado) + _s(hash_alg) + _s(h)
    try:
        Ed25519PublicKey.from_public_bytes(clave_bytes).verify(bruta, firmado)
    except InvalidSignature as exc:
        raise ValueError("la firma NO es valida (el MANIFIESTO se ha cambiado despues de firmarlo)") from exc


def comprobar_carpeta(pub_texto: str, carpeta: Path) -> None:
    """Firma del MANIFIESTO + huella de cada archivo + que no sobre ni falte ninguno. Lanza ValueError si algo falla."""
    manifiesto = carpeta / "MANIFIESTO"
    firma = carpeta / "MANIFIESTO.sig"
    if not manifiesto.is_file() or not firma.is_file():
        raise ValueError("la version publicada no esta firmada todavia")
    datos = manifiesto.read_bytes()
    verificar_firma(pub_texto, datos, firma.read_text(encoding="utf-8"))
    esperados = {}
    for linea in datos.decode("utf-8").splitlines():
        if not linea.strip():
            continue
        huella, _, nombre = linea.partition(" ")
        nombre = nombre[1:] if nombre[:1] in (" ", "*") else nombre
        if len(huella) != 64 or not nombre or nombre.startswith("/") or ".." in Path(nombre).parts:
            raise ValueError(f"linea del MANIFIESTO no valida: {linea[:80]}")
        esperados[nombre] = huella.lower()
    en_disco = set()
    for raiz, _, archivos in os.walk(carpeta):
        for a in archivos:
            rel = Path(raiz, a).relative_to(carpeta).as_posix()
            if rel not in ("MANIFIESTO", "MANIFIESTO.sig"):
                en_disco.add(rel)
    sobran = sorted(en_disco - set(esperados))
    faltan = sorted(set(esperados) - en_disco)
    if sobran:
        raise ValueError(f"la version descargada trae archivos que no estan firmados: {', '.join(sobran[:5])}")
    if faltan:
        raise ValueError(f"faltan archivos de la version firmada: {', '.join(faltan[:5])}")
    for nombre, huella in esperados.items():
        if hashlib.sha256((carpeta / nombre).read_bytes()).hexdigest() != huella:
            raise ValueError(f"el archivo {nombre} no coincide con lo firmado")


def _num(v: str) -> tuple:
    return tuple(int("".join(c for c in p if c.isdigit()) or 0) for p in v.strip().lstrip("vV").split("."))


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "verificar":
        try:
            comprobar_carpeta(Path(argv[2]).read_text(encoding="utf-8"), Path(argv[3]))
        except (OSError, ValueError) as exc:
            print(f"NO: {exc}")
            return 1
        print("OK: firma correcta y todos los archivos coinciden")
        return 0
    if len(argv) == 4 and argv[1] == "version-mayor":
        return 0 if _num(argv[2]) > _num(argv[3]) else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
