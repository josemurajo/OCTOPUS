#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - ARRANQUE POR RED (dentro de su contenedor; lo enciende el panel: lib/admin_panel.py arranque_red).

Al encender un equipo y pulsar F12 → «red», arranca el USB de rescate de OCTOPUS desde el servidor, sin pendrive, y
ya sabe la dirección del servidor. Vale para PCs modernos (UEFI, también con «Arranque seguro») y antiguos (BIOS).

  - Proxy DHCP (dnsmasq): no reparte direcciones ni molesta al router; solo contesta a los equipos que arrancan
    por red diciéndoles qué cargar.
  - TFTP (dnsmasq): el cargador (shim + GRUB firmados de Debian, o GRUB para BIOS) y el núcleo.
  - HTTP: el sistema del rescate (más rápido que TFTP).
Todo sale de la misma imagen del USB de rescate (octopus-rescate.iso): se descarga una vez y se guarda.

Variables: OCTOPUS_IP (obligatoria), OCTOPUS_PUERTO_PANEL (8080), OCTOPUS_PXE_HTTP (8090), OCTOPUS_RESCATE_ISO (URL),
           OCTOPUS_PXE_ISO (ruta a una imagen ya descargada).
"""
import hashlib
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

DIR = Path(os.environ.get("OCTOPUS_PXE_DIR", "/srv/octopus-pxe"))
TFTP = DIR / "tftp"
ISO_URL = os.environ.get("OCTOPUS_RESCATE_ISO",
                         "https://github.com/josemurajo/OCTOPUS/releases/latest/download/octopus-rescate.iso")


def log(m):
    print(f"[arranque por red] {m}", flush=True)


def red_de(ip: str) -> str:
    """La red local en la que está esta dirección (p. ej. 192.168.1.0/24), mirando las tarjetas del anfitrión."""
    datos = json.loads(subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True).stdout or "[]")
    for t in datos:
        for a in t.get("addr_info", []):
            if a.get("local") == ip:
                return str(ipaddress.ip_interface(f"{ip}/{a['prefixlen']}").network)
    raise SystemExit(f"Este servidor no tiene la dirección {ip} (mira OCTOPUS_IP en install/.env).")


def conseguir_iso() -> Path:
    iso = Path(os.environ.get("OCTOPUS_PXE_ISO") or DIR / "octopus-rescate.iso")
    if iso.exists() and iso.stat().st_size > 50 * 1024 ** 2:
        return iso
    log(f"Descargando el rescate ({ISO_URL})...")
    tmp = iso.with_suffix(".parte")
    subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", str(tmp), ISO_URL], check=True)
    esperado = subprocess.run(["curl", "-fsSL", ISO_URL + ".sha256.txt"], capture_output=True, text=True).stdout.split()
    h = hashlib.sha256()
    with open(tmp, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    if esperado and esperado[0] != h.hexdigest():
        tmp.unlink()
        raise SystemExit("La imagen descargada no cuadra con su huella: no se usa.")
    tmp.rename(iso)
    return iso


def preparar(iso: Path, ip: str, puerto_panel: str, puerto_http: str) -> None:
    marca = DIR / "preparado_de.txt"
    huella = f"{iso.stat().st_size}-{int(iso.stat().st_mtime)}"
    if not (marca.exists() and marca.read_text() == huella and (TFTP / "live" / "vmlinuz").exists()):
        if TFTP.exists():
            shutil.rmtree(TFTP)
        TFTP.mkdir(parents=True)
        subprocess.run(["xorriso", "-osirrox", "on", "-indev", str(iso), "-extract", "/pxe", str(TFTP),
                        "-extract", "/live", str(TFTP / "live")], check=True, capture_output=True)
        subprocess.run(["chmod", "-R", "u+w,a+rX", str(TFTP)], check=True)
        marca.write_text(huella)
    # GRUB para BIOS antiguas, con la dirección de este servidor dentro: con «proxy DHCP» el PC no sabría de dónde
    # sacar el resto (preguntaría al router)
    bios = TFTP / "grub" / "i386-pc"
    if bios.exists():
        shutil.rmtree(bios)
    shutil.copytree("/usr/lib/grub/i386-pc", bios)
    subprocess.run(["grub-mkimage", "-O", "i386-pc-pxe", "-p", f"(tftp,{ip})/grub", "-o", str(bios / "core.0"),
                    "pxe", "tftp", "normal", "configfile", "linux", "echo", "test", "serial", "terminal"],
                   check=True, capture_output=True)
    menu = f"""set timeout=5
if serial --unit=0 --speed=115200; then
  terminal_input console serial
  terminal_output console serial
fi
menuentry "OCTOPUS - rescate (por red)" {{
  linux /live/vmlinuz boot=live components fetch=http://{ip}:{puerto_http}/live/filesystem.squashfs locales=es_ES.UTF-8 keyboard-layouts=es octopus.servidor=https://{ip}:{puerto_panel} console=ttyS0,115200 console=tty0
  initrd /live/initrd.img
}}
menuentry "Seguir arrancando desde el disco de este ordenador" {{
  exit
}}
"""
    # el GRUB firmado de Debian busca su menú en estos sitios (según venga de UEFI o de BIOS)
    for d in ("grub", "debian-installer/amd64/grub", "boot/grub"):
        (TFTP / d).mkdir(parents=True, exist_ok=True)
        (TFTP / d / "grub.cfg").write_text(menu)


def dnsmasq_conf(ip: str, red: str) -> str:
    return f"""port=0
log-dhcp
bind-dynamic
listen-address={ip}
dhcp-range={ipaddress.ip_network(red).network_address},proxy,{ipaddress.ip_network(red).netmask}
enable-tftp
tftp-root={TFTP}
dhcp-match=set:efi64,option:client-arch,7
dhcp-match=set:efi64,option:client-arch,9
pxe-prompt="OCTOPUS",1
pxe-service=tag:!efi64,x86PC,"OCTOPUS rescate",grub/i386-pc/core
pxe-service=tag:efi64,X86-64_EFI,"OCTOPUS rescate",bootx64.efi
pxe-service=tag:efi64,BC_EFI,"OCTOPUS rescate",bootx64.efi
"""


def main() -> int:
    ip = os.environ.get("OCTOPUS_IP", "").strip()
    if not ip:
        raise SystemExit("Falta OCTOPUS_IP")
    puerto_panel = os.environ.get("OCTOPUS_PUERTO_PANEL", "8080")
    puerto_http = os.environ.get("OCTOPUS_PXE_HTTP", "8090")
    red = red_de(ip)
    DIR.mkdir(parents=True, exist_ok=True)
    preparar(conseguir_iso(), ip, puerto_panel, puerto_http)
    conf = DIR / "dnsmasq.conf"
    conf.write_text(dnsmasq_conf(ip, red))
    log(f"Listo en la red {red}: los equipos que arranquen por red (F12) cargarán el rescate de OCTOPUS.")
    http = subprocess.Popen([sys.executable, "-m", "http.server", puerto_http, "--bind", ip, "--directory", str(TFTP)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return subprocess.run(["dnsmasq", "--no-daemon", "--conf-file=" + str(conf)]).returncode
    finally:
        http.terminate()


if __name__ == "__main__":
    sys.exit(main())
