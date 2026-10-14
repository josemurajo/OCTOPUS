#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Buscar equipos en la red (el «radar» de la v1, ahora desde el panel).

Barre las redes elegidas probando unos pocos puertos típicos (sin herramientas externas ni permisos especiales):
  22 SSH (Linux, Mac y Windows con SSH), 445/135/139 Windows, 3389 escritorio remoto de Windows,
  5985 WinRM (Windows), 548 compartir archivos de Mac.
Con lo que responde intenta saber el sistema (por el saludo del SSH y los puertos) y el nombre (NetBIOS en Windows,
DNS inverso). Marca los equipos que ya tienen OCTOPUS. Nunca prueba contraseñas: eso solo se hace al instalar,
con las que escriba el usuario.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import struct
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PUERTOS = (22, 445, 135, 139, 3389, 5985, 548)
MAX_EQUIPOS_POR_RED = 1024          # como mucho una /22 por red, para que el barrido no tarde demasiado
ESCANEOS: dict[str, dict] = {}       # trabajos en memoria (el panel funciona en un solo proceso)
_lock = threading.Lock()


def _puerto_ssh() -> int:
    """Puerto SSH de los equipos (22; se puede cambiar con OCTOPUS_SSH_PUERTO, el mismo que usa la instalacion a distancia)."""
    try:
        return int(os.environ.get("OCTOPUS_SSH_PUERTO", "22"))
    except ValueError:
        return 22


def redes_propuestas(env: dict) -> list[str]:
    """Las redes del propio servidor (/24 de cada IP suya)."""
    redes = []
    candidatos = [env.get("OCTOPUS_IP", "")] + [x.strip() for x in env.get("OCTOPUS_NOMBRES_EXTRA", "").split(",")]
    for c in candidatos:
        try:
            ip = ipaddress.ip_address(c)
        except ValueError:
            continue
        if ip.version == 4 and not ip.is_loopback:
            red = str(ipaddress.ip_network(f"{ip}/24", strict=False))
            if red not in redes:
                redes.append(red)
    return redes


def validar_red(texto: str) -> str:
    """'192.168.1.0/24', '192.168.1.0-24', '192.168.1.*' o una IP suelta -> red normalizada. ValueError si no vale."""
    t = (texto or "").strip().replace(" ", "")
    if not t:
        raise ValueError("vacía")
    if t.endswith(".*"):
        t = t[:-2] + ".0/24"
    if "/" not in t:
        t += "/32"
    try:
        red = ipaddress.ip_network(t, strict=False)
    except ValueError:
        raise ValueError("no es una red válida (escríbela así: 192.168.1.0/24, 192.168.1.* o una IP)") from None
    if red.version != 4:
        raise ValueError("solo redes IPv4")
    if not red.is_private:
        raise ValueError(f"{red} no es una red privada (de oficina o casa)")
    if red.num_addresses > MAX_EQUIPOS_POR_RED:
        raise ValueError(f"{red} es demasiado grande (como mucho /22, {MAX_EQUIPOS_POR_RED} direcciones)")
    return str(red)


def _abierto(ip: str, puerto: int, espera: float = 0.6) -> bool:
    try:
        with socket.create_connection((ip, puerto), timeout=espera):
            return True
    except OSError:
        return False


def _saludo_ssh(ip: str, puerto: int | None = None) -> str:
    try:
        with socket.create_connection((ip, puerto or _puerto_ssh()), timeout=1.5) as s:
            s.settimeout(1.5)
            return s.recv(200).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _nombre_netbios(ip: str) -> str:
    """Pregunta el nombre a un equipo Windows (NetBIOS, UDP 137). '' si no contesta."""
    consulta = struct.pack(">HHHHHH", 0x0A0B, 0, 1, 0, 0, 0) + b"\x20" + b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + \
        b"\x00" + struct.pack(">HH", 0x21, 1)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            s.sendto(consulta, (ip, 137))
            datos, _ = s.recvfrom(1024)
        n = datos[56]
        for i in range(n):
            ent = datos[57 + i * 18: 57 + (i + 1) * 18]
            nombre, tipo, flags = ent[:15].decode("ascii", "replace").strip(), ent[15], ent[16]
            if tipo == 0x00 and not (flags & 0x80):   # nombre del equipo (no de grupo)
                return nombre
    except (OSError, IndexError):
        pass
    return ""


def _nombre_dns(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except (OSError, UnicodeError):
        return ""


def _sistema(puertos: set, saludo: str) -> tuple[str, str]:
    """(linux|windows|macos|, explicación)"""
    s = saludo.lower()
    if "windows" in s or puertos & {445, 135, 3389, 5985}:
        return "windows", "Windows" + (" (con SSH)" if 22 in puertos else "")
    for distro in ("ubuntu", "debian", "raspbian", "fedora", "centos", "rocky", "alma", "red hat", "suse", "arch"):
        if distro in s:
            return "linux", f"Linux ({distro.title()})"
    if 548 in puertos:
        return "macos", "Mac"
    if 22 in puertos:
        return "linux", "Linux o Mac (no se puede saber seguro)"
    return "", "desconocido"


def _nombre_valido(n: str) -> str:
    import re
    n = re.sub(r"[^A-Za-z0-9._-]", "-", n or "").strip("-.")
    return n[:63]


def _examinar(ip: str) -> dict | None:
    ssh = _puerto_ssh()
    abiertos = {p for p in PUERTOS if p != 22 and _abierto(ip, p)}
    ssh_en = next((x for x in dict.fromkeys((22, ssh)) if _abierto(ip, x)), None)
    if ssh_en:
        abiertos.add(22)                     # 22 = "tiene SSH", sea en el puerto normal o en el configurado
    if not abiertos:
        return None
    saludo = _saludo_ssh(ip, ssh_en) if ssh_en else ""
    so, texto_so = _sistema(abiertos, saludo)
    nombre = (_nombre_netbios(ip) if so == "windows" else "") or _nombre_dns(ip)
    return {"ip": ip, "nombre": _nombre_valido(nombre) or "equipo-" + ip.replace(".", "-"), "nombre_detectado": bool(nombre),
            "so": so, "sistema": texto_so, "puertos": sorted(abiertos), "ssh": 22 in abiertos,
            "a_distancia": 22 in abiertos}


def empezar(redes: list[str], conocidos: dict, propias: set) -> str:
    """Empieza un barrido en segundo plano. conocidos: {ip: nombre del equipo ya dado de alta}."""
    ips = []
    for r in redes:
        red = ipaddress.ip_network(r, strict=False)
        for h in (list(red.hosts()) if red.num_addresses > 2 else list(red)):
            if str(h) not in propias and str(h) not in ips:
                ips.append(str(h))
    eid = uuid.uuid4().hex[:10]
    with _lock:
        ESCANEOS[eid] = {"id": eid, "redes": redes, "total": len(ips), "hechos": 0, "estado": "en_curso",
                         "encontrados": [], "inicio": time.time(), "fin": None, "grupos": {}, "trabajos": []}

    def uno(ip):
        try:
            r = _examinar(ip)
        except Exception:
            r = None
        with _lock:
            e = ESCANEOS[eid]
            e["hechos"] += 1
            if r:
                r["ya_tiene"] = conocidos.get(ip)
                e["encontrados"].append(r)

    def todo():
        with ThreadPoolExecutor(max_workers=128) as pool:
            list(pool.map(uno, ips))
        with _lock:
            e = ESCANEOS[eid]
            e["encontrados"].sort(key=lambda x: tuple(int(p) for p in x["ip"].split(".")))
            e.update(estado="hecho", fin=time.time())
    threading.Thread(target=todo, daemon=True).start()
    return eid


def ver(eid: str) -> dict | None:
    with _lock:
        e = ESCANEOS.get(eid)
        return None if e is None else {**e, "encontrados": [dict(x) for x in e["encontrados"]],
                                       "grupos": {k: list(v) for k, v in e["grupos"].items()},
                                       "trabajos": list(e["trabajos"])}


def guardar(eid: str, **cambios) -> None:
    with _lock:
        if eid in ESCANEOS:
            ESCANEOS[eid].update(cambios)
