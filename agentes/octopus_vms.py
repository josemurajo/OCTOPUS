#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Copias de las MÁQUINAS VIRTUALES de un equipo (lo usa el agente, zerotouch_agent.py).

Qué hace: busca las máquinas virtuales de este equipo y copia cada una ENTERA (todos sus discos y su configuración),
para poder levantarla otra vez si se pierde. Cada copia es COMPLETA (desde cualquiera se recupera la máquina entera),
pero en el almacén solo ocupa lo que ha cambiado desde la anterior (restic guarda una sola vez cada trozo igual).

  Hyper-V (Windows) ..... discos (.vhdx y sus diferenciales .avhdx, con toda la cadena) + su configuración, leídos con
                          una instantánea VSS: la máquina puede seguir encendida.
  KVM / libvirt (Linux) . encendida: instantánea externa solo de discos (congelando su sistema de archivos si tiene
                          qemu-guest-agent), se copian los discos quietos y se vuelven a unir (blockcommit). Apagada: se
                          copian tal cual. También se guarda su definición (XML).
  Proxmox (Linux) ....... vzdump en modo instantánea, directo al almacén (no necesita sitio libre en el disco).

Recuperar (restaurar): NUNCA toca la máquina original. Deja una copia aparte en una carpeta nueva y explica cómo
arrancarla (en libvirt deja además un XML listo con otro nombre y otra MAC, para que no choque con la original).

QUÉ TOCAR:
  - Otro hipervisor ........ una función _<nombre>_detectar() y otra _<nombre>_copiar(), y llamarlas en detectar()
                             y copiar().
  - Dónde se recupera ...... _destino_por_defecto() (o la variable OCTOPUS_VM_RESTAURAR en el equipo).
  - Cuánto se guardan ...... lib/mantenimiento.py (retención de la etiqueta «vm»).
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

SYSTEM = platform.system().lower()
LIBVIRT_URI = os.environ.get("OCTOPUS_LIBVIRT_URI", "qemu:///system")
HIPERVISORES = {"hyperv": "Hyper-V", "libvirt": "KVM / libvirt", "proxmox": "Proxmox"}


# ------------------------------------------------------------------------------------------------ utilidades
def _run(cmd, timeout=600, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def _virsh(*args, timeout=600):
    return _run(["virsh", "-c", LIBVIRT_URI, *args], timeout=timeout)


def _ps(script: str, timeout=300):
    exe = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
    return _run([exe, "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def _tam(rutas) -> int:
    total = 0
    for p in rutas:
        try:
            if os.path.isdir(p):
                for r, _d, fs in os.walk(p):
                    total += sum(os.path.getsize(os.path.join(r, f)) for f in fs)
            elif os.path.exists(p):
                total += os.path.getsize(p)
        except OSError:
            pass
    return total


def etiqueta(nombre: str) -> str:
    """El nombre de la máquina tal como va en la etiqueta de la copia (restic no admite comas en las etiquetas)."""
    return re.sub(r"[,\s]+", "_", str(nombre)).strip("_")[:80] or "sin_nombre"


def _estado(txt) -> str:
    t = str(txt or "").lower()
    if t.startswith(("running", "paused")):
        return "encendida"
    if t.startswith(("off", "shut", "stopped", "saved")):
        return "apagada"
    return t or "desconocido"


# ------------------------------------------------------------------------------------------------ detectar
def detectar() -> list[dict]:
    """Las máquinas virtuales de este equipo: [{id, nombre, hipervisor, estado, discos, config, tamano}]."""
    if SYSTEM == "windows":
        return _hyperv_detectar()
    if shutil.which("qm"):            # Proxmox (no usa libvirt)
        return _proxmox_detectar()
    if shutil.which("virsh"):
        return _libvirt_detectar()
    return []


_PS_DETECTAR = r"""
$ErrorActionPreference = 'Stop'
Import-Module Hyper-V -ErrorAction Stop
$r = @(Get-VM | ForEach-Object {
  $vm = $_
  $discos = @()
  foreach ($d in (Get-VMHardDiskDrive -VM $vm)) {
    $p = $d.Path
    while ($p) { $discos += $p; try { $p = (Get-VHD -Path $p).ParentPath } catch { $p = $null } }
  }
  [pscustomobject]@{ id = $vm.VMId.Guid; nombre = $vm.Name; estado = [string]$vm.State;
                     config = $vm.ConfigurationLocation; discos = $discos }
})
ConvertTo-Json -InputObject $r -Depth 4 -Compress
"""


def _hyperv_detectar() -> list[dict]:
    r = _ps(_PS_DETECTAR)
    if r.returncode != 0:
        return []                     # sin Hyper-V (o sin permisos): no hay máquinas que copiar
    return hyperv_desde_json(r.stdout)


def hyperv_desde_json(texto: str) -> list[dict]:
    try:
        datos = json.loads(texto or "[]")
    except ValueError:
        return []
    if isinstance(datos, dict):
        datos = [datos]
    vms = []
    for d in datos or []:
        vid, carpeta_cfg = str(d.get("id") or ""), str(d.get("config") or "")
        base = os.path.join(carpeta_cfg, "Virtual Machines", vid)
        config = [base + ext for ext in (".vmcx", ".vmrs", ".vmgs", ".xml") if os.path.exists(base + ext)]
        if os.path.isdir(base):
            config.append(base)
        discos = [p for p in dict.fromkeys(d.get("discos") or []) if p]
        vms.append({"id": vid, "nombre": str(d.get("nombre") or vid), "hipervisor": "hyperv",
                    "estado": _estado(d.get("estado")), "discos": discos, "config": config,
                    "tamano": _tam(discos + config)})
    return vms


def _libvirt_discos(nombre: str) -> list[dict]:
    """Discos de archivo de una máquina: [{objetivo: 'vda', ruta: '/var/lib/libvirt/images/x.qcow2'}]."""
    r = _virsh("domblklist", nombre, "--details", timeout=60)
    out = []
    for linea in (r.stdout or "").splitlines():
        p = linea.split(None, 3)
        if len(p) == 4 and p[0] == "file" and p[1] == "disk" and p[3].strip() not in ("-", ""):
            out.append({"objetivo": p[2], "ruta": p[3].strip()})
    return out


def _cadena(ruta: str) -> list[str]:
    """El disco y sus discos base (si es un qcow2 con «backing file»): hay que copiar toda la cadena."""
    if not shutil.which("qemu-img"):
        return [ruta]
    r = _run(["qemu-img", "info", "--backing-chain", "--output=json", "-U", ruta], timeout=120)
    try:
        lista = [i.get("filename") for i in json.loads(r.stdout or "[]") if i.get("filename")]
    except (ValueError, AttributeError):
        lista = []
    return lista or [ruta]


def _libvirt_detectar() -> list[dict]:
    r = _virsh("list", "--all", "--name", timeout=60)
    if r.returncode != 0:
        return []
    vms = []
    for nombre in [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]:
        discos = _libvirt_discos(nombre)
        rutas = [c for d in discos for c in _cadena(d["ruta"])]
        vms.append({"id": _virsh("domuuid", nombre, timeout=30).stdout.strip() or nombre, "nombre": nombre,
                    "hipervisor": "libvirt", "estado": _estado(_virsh("domstate", nombre, timeout=30).stdout.strip()),
                    "discos": list(dict.fromkeys(rutas)), "config": [], "tamano": _tam(rutas)})
    return vms


def _proxmox_detectar() -> list[dict]:
    r = _run(["qm", "list"], timeout=60)
    vms = []
    for linea in (r.stdout or "").splitlines()[1:]:
        p = linea.split()
        if len(p) >= 3 and p[0].isdigit():
            try:
                tam = int(float(p[4]) * 1024 ** 3) if len(p) > 4 else 0
            except ValueError:
                tam = 0
            vms.append({"id": p[0], "nombre": p[1], "hipervisor": "proxmox", "estado": _estado(p[2]),
                        "discos": [], "config": [], "tamano": tam})
    return vms


# ------------------------------------------------------------------------------------------------ copiar
def _resumen(stdout: str) -> str:
    snap = ""
    for linea in (stdout or "").splitlines():
        try:
            d = json.loads(linea)
        except ValueError:
            continue
        if d.get("message_type") == "summary":
            snap = d.get("snapshot_id", "")
    return snap


def _cmd_backup(ctx: dict, vm: dict, rutas, extra=()) -> list[str]:
    return [ctx["bin"], "backup", *rutas, "--tag", "octopus-agent", "--tag", "vm",
            "--tag", f"vm:{etiqueta(vm['nombre'])}", "--tag", f"hipervisor:{vm['hipervisor']}",
            "--host", ctx["host"], "--json", *ctx.get("opts", []), *extra]


def _restic_backup(ctx: dict, vm: dict, rutas, extra=()) -> dict:
    rutas = [r for r in rutas if os.path.exists(r)]
    if not rutas:
        return {"status": "error", "message": "No se encuentran los discos de la máquina"}
    r = _run(_cmd_backup(ctx, vm, rutas, extra), timeout=24 * 3600, env=ctx["env"])
    if r.returncode not in (0, 3):
        return {"status": "error", "message": (r.stderr or r.stdout or "").strip()[-600:]}
    res = {"status": "success", "snapshot_id": _resumen(r.stdout), "tamano": _tam(rutas)}
    if r.returncode == 3:
        res["aviso"] = "Algún archivo no se pudo leer"
    return res


def _hyperv_copiar(ctx: dict, vm: dict) -> dict:
    # VSS: los archivos se leen de una instantánea del volumen, así que la máquina puede estar encendida
    return _restic_backup(ctx, vm, vm["discos"] + vm["config"], extra=["--use-fs-snapshot"])


def _libvirt_copiar(ctx: dict, vm: dict) -> dict:
    carpeta = Path(ctx["dir"]) / "vms"
    carpeta.mkdir(parents=True, exist_ok=True)
    xml = carpeta / f"{etiqueta(vm['nombre'])}.xml"        # ruta FIJA: así la retención agrupa bien las copias
    x = _virsh("dumpxml", vm["nombre"], timeout=60)
    if x.returncode != 0:
        return {"status": "error", "message": "No se pudo leer la definición de la máquina: " + x.stderr.strip()[-300:]}
    xml.write_text(x.stdout, encoding="utf-8")
    discos = _libvirt_discos(vm["nombre"])
    if not discos:
        return {"status": "error", "message": "La máquina no tiene discos de archivo que copiar"}
    rutas = list(dict.fromkeys([c for d in discos for c in _cadena(d["ruta"])])) + [str(xml)]
    if vm["estado"] != "encendida":
        return _restic_backup(ctx, vm, rutas)

    # encendida: los discos pasan un momento a escribir en una capa temporal, se copian quietos y se vuelven a unir
    marca = datetime.now().strftime("%Y%m%d%H%M%S")
    capas = {d["objetivo"]: os.path.splitext(d["ruta"])[0] + f".octopus-{marca}.qcow2" for d in discos}
    specs = [a for o, c in capas.items() for a in ("--diskspec", f"{o},snapshot=external,file={c}")]
    base = ["snapshot-create-as", vm["nombre"], f"octopus-{marca}", "--disk-only", "--atomic", "--no-metadata"]
    aviso = ""
    r = _virsh(*base, "--quiesce", *specs, timeout=300)
    if r.returncode != 0:
        r = _virsh(*base, *specs, timeout=300)
        aviso = ("Copiada sin «congelar» el sistema de archivos de la máquina: instala qemu-guest-agent dentro "
                 "de ella para copias todavía más limpias")
    if r.returncode != 0:
        return {"status": "error", "message": "No se pudo hacer la instantánea de la máquina: " + r.stderr.strip()[-300:]}
    res = {"status": "error", "message": "La copia se interrumpió"}
    try:
        res = _restic_backup(ctx, vm, rutas)
    finally:
        fallos = []
        for objetivo, capa in capas.items():
            u = _virsh("blockcommit", vm["nombre"], objetivo, "--active", "--pivot", "--wait", timeout=6 * 3600)
            if u.returncode == 0:
                try:
                    os.remove(capa)
                except OSError:
                    pass
            else:
                fallos.append(f"{objetivo} ({capa}): {u.stderr.strip()[-200:]}")
        if fallos:
            # la máquina sigue funcionando, pero escribiendo en la capa temporal: hay que unirla a mano
            res = {"status": "error", "snapshot_id": res.get("snapshot_id", ""),
                   "message": "La copia se hizo, pero la máquina sigue sobre la capa temporal. Únela con "
                              f"«virsh blockcommit {vm['nombre']} <disco> --active --pivot»: " + "; ".join(fallos)}
    if aviso and res.get("status") == "success":
        res["aviso"] = aviso
    return res


def _proxmox_copiar(ctx: dict, vm: dict) -> dict:
    nombre = f"vzdump-qemu-{vm['id']}.vma"
    try:
        vz = subprocess.Popen(["vzdump", str(vm["id"]), "--mode", "snapshot", "--stdout", "--compress", "0"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        return {"status": "error", "message": f"No se pudo lanzar vzdump: {exc}"}
    cmd = _cmd_backup(ctx, vm, [], extra=["--stdin", "--stdin-filename", nombre])
    try:
        r = subprocess.run(cmd, stdin=vz.stdout, capture_output=True, text=True, timeout=24 * 3600, env=ctx["env"])
    finally:
        vz.stdout.close()
        rc_vz = vz.wait()
        err_vz = (vz.stderr.read() or b"").decode(errors="replace")
    snap = _resumen(r.stdout)
    if rc_vz != 0 or r.returncode != 0:
        if snap:   # copia a medias: se quita para que nadie la use para recuperar
            _run([ctx["bin"], "forget", snap], timeout=600, env=ctx["env"])
        return {"status": "error", "message": (err_vz.strip() or r.stderr.strip() or "vzdump falló")[-600:]}
    return {"status": "success", "snapshot_id": snap, "tamano": vm.get("tamano", 0)}


def copiar(ctx: dict, vm: dict) -> dict:
    """Copia completa de UNA máquina. ctx = {bin, env, host, opts, dir} (lo prepara el agente)."""
    fn = {"hyperv": _hyperv_copiar, "libvirt": _libvirt_copiar, "proxmox": _proxmox_copiar}.get(vm.get("hipervisor"))
    if not fn:
        return {"status": "error", "message": "Hipervisor no soportado"}
    res = fn(ctx, vm)
    res.update(nombre=vm["nombre"], hipervisor=vm["hipervisor"])
    return res


# ------------------------------------------------------------------------------------------------ copias hechas
def copias(ctx: dict) -> list[dict]:
    """Las copias de máquinas virtuales de este equipo que hay en el almacén (la más nueva primero)."""
    r = _run([ctx["bin"], "snapshots", "--json", "--host", ctx["host"], "--tag", "vm"], timeout=300, env=ctx["env"])
    try:
        snaps = json.loads(r.stdout or "[]") or []
    except ValueError:
        snaps = []
    out = []
    for s in snaps:
        tags = s.get("tags") or []
        nombre = next((t[3:] for t in tags if t.startswith("vm:")), "")
        hip = next((t[11:] for t in tags if t.startswith("hipervisor:")), "")
        out.append({"id": s.get("short_id") or s.get("id", "")[:8], "time": s.get("time"), "nombre": nombre,
                    "hipervisor": hip})
    out.sort(key=lambda c: c.get("time") or "", reverse=True)
    return out


# ------------------------------------------------------------------------------------------------ recuperar
def _destino_por_defecto(hipervisor: str) -> str:
    if os.environ.get("OCTOPUS_VM_RESTAURAR"):
        return os.environ["OCTOPUS_VM_RESTAURAR"]
    if hipervisor == "libvirt" and os.path.isdir("/var/lib/libvirt/images"):
        return "/var/lib/libvirt/images"
    if hipervisor == "proxmox" and os.path.isdir("/var/lib/vz/dump"):
        return "/var/lib/vz/dump"
    if SYSTEM == "windows":         # la unidad con más sitio libre
        mejor, libre = "C:\\", -1
        for letra in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            u = f"{letra}:\\"
            try:
                f = shutil.disk_usage(u).free
            except OSError:
                continue
            if f > libre:
                mejor, libre = u, f
        return mejor
    return "/var/tmp"


def xml_restaurada(xml_txt: str, nombre_nuevo: str, rutas: dict) -> str:
    """Definición libvirt para arrancar la copia SIN chocar con la original: otro nombre, sin UUID ni MAC (libvirt pone
    unos nuevos) y los discos apuntando a los archivos recuperados. rutas = {nombre_de_archivo: ruta_recuperada}."""
    raiz = ET.fromstring(xml_txt)
    n = raiz.find("name")
    if n is not None:
        n.text = nombre_nuevo
    u = raiz.find("uuid")
    if u is not None:
        raiz.remove(u)
    for disco in raiz.iter("disk"):
        src = disco.find("source")
        if src is not None and src.get("file") and os.path.basename(src.get("file")) in rutas:
            src.set("file", rutas[os.path.basename(src.get("file"))])
        bs = disco.find("backingStore")      # la cadena la lee libvirt del propio qcow2
        if bs is not None:
            disco.remove(bs)
    for iface in raiz.iter("interface"):
        mac = iface.find("mac")
        if mac is not None:
            iface.remove(mac)
    return ET.tostring(raiz, encoding="unicode")


def restaurar(ctx: dict, snapshot: str, nombre: str, hipervisor: str, destino: str | None = None) -> dict:
    """Recupera una copia en una carpeta NUEVA (la máquina original no se toca) y explica cómo arrancarla."""
    if not re.fullmatch(r"[0-9a-fA-F]{6,64}", str(snapshot or "")):
        return {"status": "error", "message": "Copia no válida"}
    base = destino or _destino_por_defecto(hipervisor)
    st = _run([ctx["bin"], "stats", "--json", "--mode", "restore-size", snapshot], timeout=900, env=ctx["env"])
    try:
        necesario = int(json.loads(st.stdout or "{}").get("total_size") or 0)
    except ValueError:
        necesario = 0
    try:
        libre = shutil.disk_usage(base).free
    except OSError:
        return {"status": "error", "message": f"No existe la carpeta de destino {base}"}
    if necesario and libre < necesario * 1.05:
        return {"status": "error", "message": f"No hay sitio en {base}: hacen falta {necesario // 1024 ** 3 + 1} GB y "
                                              f"quedan {libre // 1024 ** 3} GB. Libera espacio o elige otro destino."}
    carpeta = Path(base) / "OCTOPUS-restaurado" / f"{etiqueta(nombre)}-{datetime.now():%Y%m%d-%H%M}"
    carpeta.mkdir(parents=True, exist_ok=True)
    r = _run([ctx["bin"], "restore", snapshot, "--target", str(carpeta)], timeout=24 * 3600, env=ctx["env"])
    if r.returncode != 0:
        return {"status": "error", "message": (r.stderr or r.stdout).strip()[-600:]}
    archivos = [os.path.join(rr, f) for rr, _d, fs in os.walk(carpeta) for f in fs]
    res = {"status": "success", "carpeta": str(carpeta), "archivos": len(archivos)}
    if hipervisor == "libvirt":
        xml_orig = next((a for a in archivos if a.endswith(".xml")), None)
        if xml_orig:
            nuevo = f"{etiqueta(nombre)}-restaurada"
            discos = {os.path.basename(a): a for a in archivos if not a.endswith(".xml")}
            destino_xml = carpeta / f"{nuevo}.xml"
            destino_xml.write_text(xml_restaurada(Path(xml_orig).read_text(encoding="utf-8"), nuevo, discos),
                                   encoding="utf-8")
            res["instrucciones"] = (f"Para arrancarla (al lado de la original, con otro nombre y otra MAC): "
                                    f"virsh define {destino_xml} && virsh start {nuevo}")
    elif hipervisor == "hyperv":
        res["instrucciones"] = ("En el Administrador de Hyper-V: Acción → Importar máquina virtual → elige la carpeta "
                                f"{carpeta} → «Copiar la máquina virtual (crear un nuevo identificador único)».")
    elif hipervisor == "proxmox":
        vma = next((a for a in archivos if a.endswith(".vma")), "")
        res["instrucciones"] = f"Para crearla como máquina nueva: qmrestore {vma} <número libre, p. ej. 9001>"
    return res
