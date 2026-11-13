#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
Prueba del ARRANQUE POR RED (install/pxe) como en una oficina de verdad (Linux, root, con Docker y QEMU):

  - una red de mentira (puente br-octo, 10.77.0.0/24) con su ROUTER aparte, que reparte las direcciones (DHCP);
  - el contenedor de arranque por red de OCTOPUS en el «servidor» (10.77.0.1), en modo proxy: no reparte nada;
  - tres PCs virtuales que arrancan por red: moderno con «Arranque seguro», moderno sin él y antiguo (BIOS).
Cada uno tiene que llegar al rescate de OCTOPUS sabiendo ya la dirección del servidor.

  sudo python3 tests/ci/prueba_pxe.py octopus-rescate.iso
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
F = []
IP = "10.77.0.1"


def chk(c, n, x=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else x, flush=True)
    if not c:
        F.append(n)


def sh(cmd, check=True):
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, check=check, capture_output=True, text=True)


def montar_red():
    sh("ip link add br-octo type bridge && ip addr add 10.77.0.1/24 dev br-octo && ip link set br-octo up")
    # el router de la oficina, en su propio «aparato» (espacio de red aparte), dando direcciones por DHCP
    sh("ip netns add router && ip link add vr0 type veth peer name vr1 && ip link set vr0 netns router "
       "&& ip link set vr1 master br-octo && ip link set vr1 up "
       "&& ip netns exec router ip addr add 10.77.0.254/24 dev vr0 && ip netns exec router ip link set vr0 up "
       "&& ip netns exec router ip link set lo up")
    sh("iptables -I FORWARD -i br-octo -o br-octo -j ACCEPT", check=False)   # Docker cierra el reenvío por defecto
    router = subprocess.Popen(["ip", "netns", "exec", "router", "dnsmasq", "--no-daemon", "--port=0",
                               "--interface=vr0", "--bind-interfaces", "--dhcp-range=10.77.0.50,10.77.0.99,1h",
                               "--dhcp-authoritative", "--log-dhcp", "--pid-file=/run/router-dnsmasq.pid"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path("/etc/qemu").mkdir(exist_ok=True)
    Path("/etc/qemu/bridge.conf").write_text("allow br-octo\n")
    return router


def servidor_pxe(iso):
    sh(f"docker build -q -t octopus-pxe:1 {RAIZ / 'install' / 'pxe'}")
    sh("docker rm -f octopus-pxe", check=False)
    sh(f"docker run -d --name octopus-pxe --network host --cap-add NET_ADMIN --cap-add NET_RAW "
       f"--cap-add NET_BIND_SERVICE -e OCTOPUS_IP={IP} -e OCTOPUS_PXE_ISO=/iso/{Path(iso).name} "
       f"-v {Path(iso).parent}:/iso:ro octopus-pxe:1")
    fin = time.time() + 300
    while time.time() < fin:
        log = sh("docker logs octopus-pxe 2>&1", check=False).stdout
        if "Listo en la red 10.77.0.0/24" in log:
            chk(True, "el arranque por red se enciende en la red de la oficina (sin repartir direcciones)")
            return True
        if "octopus-pxe" not in sh("docker ps --format '{{.Names}}'", check=False).stdout:
            break
        time.sleep(3)
    chk(False, "el arranque por red se enciende", sh("docker logs octopus-pxe 2>&1", check=False).stdout[-2000:])
    return False


def arrancar(firmware, nombre):
    tmp = tempfile.mkdtemp()
    kvm = ["-enable-kvm", "-cpu", "host"] if os.access("/dev/kvm", os.W_OK) else []
    cmd = ["qemu-system-x86_64", "-m", "2048", "-nographic", "-no-reboot", *kvm,
           "-netdev", "bridge,id=n0,br=br-octo", "-device", "virtio-net-pci,netdev=n0,bootindex=1"]
    if firmware:
        code, vars_, seguro = firmware
        v = os.path.join(tmp, "vars.fd")
        shutil.copy(vars_, v)
        cmd += ["-machine", "q35,smm=on" if seguro else "q35",
                "-drive", f"if=pflash,format=raw,readonly=on,file={code}", "-drive", f"if=pflash,format=raw,file={v}"]
        if seguro:
            cmd += ["-global", "driver=cfi.pflash01,property=secure,value=on"]
    else:
        cmd += ["-boot", "n"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    os.set_blocking(p.stdout.fileno(), False)
    salida, fin = b"", time.time() + (600 if kvm else 1500)
    objetivo = f"OCTOPUS: arrancado por red desde https://{IP}:8080".encode()
    while time.time() < fin and objetivo not in salida:
        t = p.stdout.read(65536)
        if t:
            salida += t
        elif p.poll() is not None:
            break
        else:
            time.sleep(1)
    time.sleep(2)
    try:
        salida += p.stdout.read(65536) or b""
    except Exception:
        pass
    p.kill()
    texto = salida.decode(errors="replace")
    chk(objetivo in salida, f"arranca por red y ya sabe dónde está el servidor: {nombre}", texto[-3000:])
    if firmware and firmware[2]:
        chk("OCTOPUS: arranque seguro encendido" in texto, "y de verdad con el arranque seguro encendido")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    iso = os.path.abspath(sys.argv[1])
    router = montar_red()
    try:
        if servidor_pxe(iso):
            d = "/usr/share/OVMF/"
            code_sb = d + ("OVMF_CODE_4M.ms.fd" if os.path.exists(d + "OVMF_CODE_4M.ms.fd") else "OVMF_CODE_4M.secboot.fd")
            arrancar((code_sb, d + "OVMF_VARS_4M.ms.fd", True), "PC moderno con arranque seguro")
            arrancar((d + "OVMF_CODE_4M.fd", d + "OVMF_VARS_4M.fd", False), "PC moderno (UEFI)")
            arrancar(None, "PC antiguo (BIOS)")
        print(sh("docker logs octopus-pxe 2>&1 | tail -40", check=False).stdout)
    finally:
        router.kill()
        sh("docker rm -f octopus-pxe", check=False)
    print("FALLOS:", F or "ninguno")
    sys.exit(1 if F else 0)
