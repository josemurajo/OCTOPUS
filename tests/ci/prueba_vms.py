# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Copias de máquinas virtuales (agentes/octopus_vms.py) con hipervisores SIMULADOS y restic DE VERDAD.

Se simulan virsh (KVM/libvirt) y qm/vzdump (Proxmox) con scripts falsos; las copias, el almacén y la recuperación son
reales. Comprueba: detectar, copiar encendida (instantánea + unir) y apagada, la capa temporal se quita, sin
qemu-guest-agent avisa, si no se puede unir lo dice, el disco recuperado es idéntico, el XML recuperado no choca con la
original, falta de sitio, Proxmox por tubería y copia a medias borrada, y el formato de Hyper-V.
Necesita restic en el PATH (en GitHub lo instala tests/ci/herramientas.sh). Solo Linux/Mac.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent.parent / "agentes"))
import octopus_vms as vms  # noqa: E402

F = []


def chk(c, n, x=""):
    print("OK  " if c else "MAL ", n, x)
    c or F.append(n)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


T = Path(tempfile.mkdtemp(prefix="octopus_vms_"))
BIN, BINPX, IMG, ESTADO = T / "bin", T / "bin_proxmox", T / "imagenes", T / "estado.json"
for d in (BIN, BINPX, IMG):
    d.mkdir()
discos = {"web01": IMG / "web01.qcow2", "apagada01": IMG / "apagada01.img"}
for n, p in discos.items():
    p.write_bytes(os.urandom(3 * 1024 * 1024))

VIRSH = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a[:1] == ["-c"]:
    a = a[2:]
E = __ESTADO__
st = json.load(open(E)) if os.path.exists(E) else {}
DOM = {"web01": ("running", "__D1__"), "apagada01": ("shut off", "__D2__")}
cmd = a[0]
if cmd == "list":
    print("\n".join(DOM)); sys.exit(0)
dom = a[1]
if cmd == "domstate":
    print(DOM[dom][0]); sys.exit(0)
if cmd == "domuuid":
    print("uuid-" + dom); sys.exit(0)
if cmd == "domblklist":
    print(" Type   Device   Target   Source\n------------------------------------")
    print(f" file   disk     vda      {DOM[dom][1]}")
    print(" file   cdrom    sda      -"); sys.exit(0)
if cmd == "dumpxml":
    print(f"<domain type='kvm'><name>{dom}</name><uuid>uuid-{dom}</uuid><devices>"
          f"<disk type='file' device='disk'><source file='{DOM[dom][1]}'/><target dev='vda'/></disk>"
          f"<interface type='network'><mac address='52:54:00:aa:bb:cc'/><source network='default'/></interface>"
          f"</devices></domain>"); sys.exit(0)
if cmd == "snapshot-create-as":
    if "--quiesce" in a and os.environ.get("SIN_AGENTE"):
        print("error: Guest agent is not responding", file=sys.stderr); sys.exit(1)
    capa = a[a.index("--diskspec") + 1].split("file=", 1)[1]
    open(capa, "wb").write(b"capa temporal")
    st.setdefault("capas", []).append(capa); json.dump(st, open(E, "w")); sys.exit(0)
if cmd == "blockcommit":
    if os.environ.get("FALLA_UNIR"):
        print("error: block commit failed", file=sys.stderr); sys.exit(1)
    st["unidas"] = st.get("unidas", 0) + 1; json.dump(st, open(E, "w")); sys.exit(0)
print("orden desconocida", a, file=sys.stderr); sys.exit(2)
'''
VIRSH = (VIRSH.replace("__ESTADO__", repr(str(ESTADO))).replace("__D1__", str(discos["web01"]))
         .replace("__D2__", str(discos["apagada01"])))
(BIN / "virsh").write_text(VIRSH)
CONTENIDO_PX = T / "vzdump_contenido.bin"
CONTENIDO_PX.write_bytes(os.urandom(2 * 1024 * 1024))
(BINPX / "qm").write_text("#!/bin/sh\necho '      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID'\n"
                          "echo '       101 erp                  running    4096              32.00 1234'\n")
(BINPX / "vzdump").write_text(f"#!/bin/sh\n[ -n \"$FALLA_VZDUMP\" ] && {{ head -c 1000 {CONTENIDO_PX}; echo roto >&2; exit 5; }}\n"
                              f"cat {CONTENIDO_PX}\n")
for f in list(BIN.iterdir()) + list(BINPX.iterdir()):
    f.chmod(0o755)

restic = shutil.which("restic")
if not restic:
    print("Falta restic en el PATH")
    sys.exit(1)
REPO = T / "almacen"
env = {**os.environ, "RESTIC_REPOSITORY": str(REPO), "RESTIC_PASSWORD": "prueba-vms", "RESTIC_CACHE_DIR": str(T / "cache")}
subprocess.run([restic, "init"], env=env, check=True, capture_output=True)
ctx = {"bin": restic, "env": env, "host": "anfitrion-prueba", "opts": [], "dir": str(T / "estado_agente")}
PATH0 = os.environ["PATH"]

# ---------------------------------------------------------------- KVM / libvirt
os.environ["PATH"] = f"{BIN}:{PATH0}"
lista = vms.detectar()
por = {v["nombre"]: v for v in lista}
chk(set(por) == {"web01", "apagada01"} and all(v["hipervisor"] == "libvirt" for v in lista), "libvirt: detecta las 2 máquinas")
chk(por["web01"]["estado"] == "encendida" and por["apagada01"]["estado"] == "apagada", "estado encendida/apagada")
chk(por["web01"]["discos"] == [str(discos["web01"])] and por["web01"]["tamano"] >= 3 * 1024 * 1024, "discos y tamaño (el cdrom no cuenta)")

r1 = vms.copiar(ctx, por["web01"])
st = json.loads(ESTADO.read_text())
chk(r1["status"] == "success" and r1.get("snapshot_id"), "encendida: copiada", r1.get("message", ""))
chk(st.get("unidas") == 1 and not any(os.path.exists(c) for c in st.get("capas", [])), "encendida: se une y se quita la capa temporal")
chk(not r1.get("aviso"), "con qemu-guest-agent: sin aviso")
r2 = vms.copiar(ctx, por["apagada01"])
chk(r2["status"] == "success" and json.loads(ESTADO.read_text()).get("unidas") == 1, "apagada: copiada sin instantánea")

os.environ["SIN_AGENTE"] = "1"
r3 = vms.copiar(ctx, por["web01"])
del os.environ["SIN_AGENTE"]
chk(r3["status"] == "success" and "qemu-guest-agent" in r3.get("aviso", ""), "sin qemu-guest-agent: copia igual y avisa")

os.environ["FALLA_UNIR"] = "1"
r4 = vms.copiar(ctx, por["web01"])
del os.environ["FALLA_UNIR"]
capas = json.loads(ESTADO.read_text())["capas"]
chk(r4["status"] == "error" and "blockcommit" in r4.get("message", "") and os.path.exists(capas[-1]),
    "si no se puede unir: lo dice con la orden para arreglarlo y NO borra la capa en uso")
os.remove(capas[-1])

cs = vms.copias(ctx)
chk(len(cs) == 4 and {c["nombre"] for c in cs} == {"web01", "apagada01"} and all(c["hipervisor"] == "libvirt" for c in cs),
    "lista de copias hechas con su máquina y tipo", len(cs))

DEST = T / "recuperar"
DEST.mkdir()
snap = r1["snapshot_id"][:8]
huella_original = sha(discos["web01"])
rr = vms.restaurar(ctx, snap, "web01", "libvirt", destino=str(DEST))
chk(rr["status"] == "success", "recuperar: termina", rr.get("message", ""))
recup = [Path(a) for a in Path(rr["carpeta"]).rglob("web01.qcow2")]
chk(recup and sha(recup[0]) == sha(discos["web01"]), "el disco recuperado es idéntico al original")
xmlr = next(Path(rr["carpeta"]).glob("web01-restaurada.xml"), None)
txt = xmlr.read_text() if xmlr else ""
chk(xmlr and "<name>web01-restaurada</name>" in txt and "<uuid>" not in txt and "52:54:00" not in txt
    and str(recup[0]) in txt, "XML listo: otro nombre, sin UUID ni MAC, disco recuperado")
chk("virsh define" in rr.get("instrucciones", ""), "explica cómo arrancarla")
chk(discos["web01"].exists() and sha(discos["web01"]) == huella_original, "la máquina original no se toca")

real = vms.shutil.disk_usage
vms.shutil.disk_usage = lambda p: namedtuple("u", "total used free")(10, 10, 1)
rs = vms.restaurar(ctx, snap, "web01", "libvirt", destino=str(DEST))
vms.shutil.disk_usage = real
chk(rs["status"] == "error" and "sitio" in rs["message"], "sin sitio: no empieza y lo explica")
chk(vms.restaurar(ctx, "x; rm -rf /", "web01", "libvirt")["status"] == "error", "copia con nombre raro: rechazada")

# ---------------------------------------------------------------- Proxmox
os.environ["PATH"] = f"{BINPX}:{PATH0}"
lp = vms.detectar()
chk(len(lp) == 1 and lp[0]["hipervisor"] == "proxmox" and lp[0]["id"] == "101" and lp[0]["estado"] == "encendida",
    "Proxmox: detecta la máquina 101")
rp = vms.copiar(ctx, lp[0])
chk(rp["status"] == "success", "Proxmox: copiada por tubería (sin disco intermedio)", rp.get("message", ""))
antes = len(vms.copias(ctx))
os.environ["FALLA_VZDUMP"] = "1"
rpf = vms.copiar(ctx, lp[0])
del os.environ["FALLA_VZDUMP"]
chk(rpf["status"] == "error" and len(vms.copias(ctx)) == antes, "vzdump falla: error y la copia a medias se borra")
rpr = vms.restaurar(ctx, rp["snapshot_id"][:8], "erp", "proxmox", destino=str(DEST))
vma = list(Path(rpr.get("carpeta", "/nada")).rglob("vzdump-qemu-101.vma"))
chk(rpr["status"] == "success" and vma and sha(vma[0]) == sha(CONTENIDO_PX) and "qmrestore" in rpr.get("instrucciones", ""),
    "Proxmox: recupera el volcado idéntico y explica qmrestore")
os.environ["PATH"] = PATH0

# ---------------------------------------------------------------- Hyper-V (formato de lo que devuelve PowerShell)
uno = vms.hyperv_desde_json(json.dumps({"id": "abc", "nombre": "DC01", "estado": "Running", "config": "C:\\VMs",
                                        "discos": ["C:\\VMs\\dc01.avhdx", "C:\\VMs\\dc01.vhdx"]}))
chk(len(uno) == 1 and uno[0]["estado"] == "encendida" and uno[0]["discos"] == ["C:\\VMs\\dc01.avhdx", "C:\\VMs\\dc01.vhdx"],
    "Hyper-V: una máquina (con su cadena de discos)")
dos = vms.hyperv_desde_json(json.dumps([{"id": "a", "nombre": "A", "estado": "Off", "config": "", "discos": []},
                                        {"id": "b", "nombre": "B", "estado": "Saved", "config": "", "discos": []}]))
chk([v["estado"] for v in dos] == ["apagada", "apagada"] and vms.hyperv_desde_json("") == [], "Hyper-V: varias, y nada si no hay")
chk(vms.etiqueta("Mi servidor, nuevo") == "Mi_servidor_nuevo", "nombres con espacios y comas valen como etiqueta")

shutil.rmtree(T, ignore_errors=True)
print("FALLOS:", F or "ninguno")
sys.exit(1 if F else 0)
