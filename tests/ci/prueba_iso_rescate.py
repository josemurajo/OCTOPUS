#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
Prueba de la imagen del USB de rescate (rescate/hacer_iso.sh): la arranca en máquinas virtuales como si fuera un
pendrive y espera a que salga «OCTOPUS: rescate listo».

  python tests/ci/prueba_iso_rescate.py octopus-rescate.iso
     1) PC moderno con «Arranque seguro» encendido (UEFI con las claves de Microsoft, como viene casi todo PC)
     2) PC moderno sin arranque seguro (UEFI)
     3) PC antiguo (BIOS)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

F = []


def chk(c, n, x=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else x)
    if not c:
        F.append(n)


def arrancar(iso, firmware, nombre):
    tmp = tempfile.mkdtemp()
    kvm = ["-enable-kvm", "-cpu", "host"] if os.access("/dev/kvm", os.W_OK) else []
    cmd = ["qemu-system-x86_64", "-m", "1536", "-nographic", "-no-reboot", *kvm,
           "-drive", f"file={iso},format=raw,if=virtio,readonly=on", "-nic", "user,model=virtio-net-pci"]
    if firmware:
        code, vars_, seguro = firmware
        v = os.path.join(tmp, "vars.fd")
        shutil.copy(vars_, v)
        cmd += ["-machine", "q35,smm=on" if seguro else "q35", "-drive", f"if=pflash,format=raw,readonly=on,file={code}",
                "-drive", f"if=pflash,format=raw,file={v}"]
        if seguro:
            cmd += ["-global", "driver=cfi.pflash01,property=secure,value=on"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    os.set_blocking(p.stdout.fileno(), False)
    salida, fin = b"", time.time() + (420 if kvm else 1200)
    while time.time() < fin and b"OCTOPUS: rescate listo" not in salida:
        t = p.stdout.read(65536)
        if t:
            salida += t
        elif p.poll() is not None:
            break
        else:
            time.sleep(1)
    time.sleep(3)
    try:
        salida += p.stdout.read(65536) or b""
    except Exception:
        pass
    p.kill()
    texto = salida.decode(errors="replace")
    chk("OCTOPUS: rescate listo" in texto, f"arranca: {nombre}", texto[-2500:])
    if firmware and firmware[2]:
        chk("OCTOPUS: arranque seguro encendido" in texto,
            "y de verdad con el arranque seguro encendido", "")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    iso = sys.argv[1]
    d = "/usr/share/OVMF/"
    if os.path.exists(d + "OVMF_CODE_4M.ms.fd") or os.path.exists(d + "OVMF_CODE_4M.secboot.fd"):
        code = d + ("OVMF_CODE_4M.ms.fd" if os.path.exists(d + "OVMF_CODE_4M.ms.fd") else "OVMF_CODE_4M.secboot.fd")
        arrancar(iso, (code, d + "OVMF_VARS_4M.ms.fd", True), "PC moderno con arranque seguro")
    arrancar(iso, (d + "OVMF_CODE_4M.fd", d + "OVMF_VARS_4M.fd", False), "PC moderno (UEFI)")
    arrancar(iso, None, "PC antiguo (BIOS)")
    print("FALLOS:", F or "ninguno")
    sys.exit(1 if F else 0)
