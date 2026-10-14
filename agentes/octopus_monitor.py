#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# Marca de autoría en base64 (se lee con `base64 -d`):
#   T0NUT1BVUyBaZXJvLVRvdWNoIC0gY3JlYWRvIHBvciBKb3PDqSBNdXJpbGxvIFJham8gKGh0dHBzOi8vZ2l0aHViLmNvbS9q
#   b3NlbXVyYWpvL09DVE9QVVMpLCAyMDI2LiBTb2Z0d2FyZSBsaWJyZSBBR1BMLTMuMC1vci1sYXRlcjogZXN0YSBhdHJpYnVj
#   acOzbiBkZWJlIGNvbnNlcnZhcnNlIChMSUNFTlNFLCBzZWNjacOzbiA3LmI7IHZlciBOT1RJQ0UpLg==
"""
OCTOPUS - Monitorizacion del equipo (va junto al agente; solo Python, sin instalar nada mas).

Recoge el uso de todo el equipo para el apartado «Monitorizacion» del panel:
  - rapido (cada pocos segundos): CPU total y por nucleo, memoria y swap, discos (espacio), lectura/escritura de disco,
    red (bajada/subida), temperaturas y ventiladores, bateria, procesos que mas gastan, tiempo encendido, usuarios.
  - lento (cada 10 min o mas): salud de los discos (SMART: desgaste, horas, temperatura, sectores malos), inventario
    (fabricante, modelo, numero de serie, BIOS, procesador, grafica, sistema), actualizaciones pendientes, antivirus,
    servicios parados y si hace falta reiniciar.

Uso suelto (para probar):  python octopus_monitor.py        -> imprime una muestra en JSON
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

SISTEMA = platform.system().lower()          # linux / windows / darwin
CREAR_SIN_VENTANA = 0x08000000 if SISTEMA == "windows" else 0


def _run(cmd: list[str], timeout: float = 20) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=CREAR_SIN_VENTANA,
                           encoding="utf-8", errors="replace")
        return r.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _leer(ruta: str | Path, defecto: str = "") -> str:
    try:
        return Path(ruta).read_text(errors="replace").strip()
    except OSError:
        return defecto


def _num(texto, defecto=None):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return defecto


# =============================================================================================== LINUX
class _Linux:
    FS_REALES = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "f2fs", "jfs",
                 "reiserfs", "hfsplus", "apfs"}

    def __init__(self):
        self.prev_cpu = None
        self.prev_io = None
        self.prev_red = None
        self.prev_proc = {}
        self.prev_t = None
        self.pagina = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        self.hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

    def _cpu_ticks(self):
        filas = {}
        for l in _leer("/proc/stat").splitlines():
            if l.startswith("cpu"):
                p = l.split()
                v = list(map(int, p[1:9]))
                inactivo = v[3] + v[4]
                filas[p[0]] = (sum(v), inactivo)
        return filas

    def rapido(self) -> dict:
        ahora = time.time()
        dt = (ahora - self.prev_t) if self.prev_t else None
        d: dict = {}
        # CPU
        c = self._cpu_ticks()
        if self.prev_cpu:
            def pct(k):
                t0, i0 = self.prev_cpu.get(k, (0, 0))
                t1, i1 = c.get(k, (0, 0))
                return round(100 * (1 - (i1 - i0) / (t1 - t0)), 1) if t1 > t0 else 0.0
            nucleos = sorted((k for k in c if k != "cpu"), key=lambda k: int(k[3:]))
            d["cpu"] = {"total": pct("cpu"), "nucleos": [pct(k) for k in nucleos]}
        self.prev_cpu = c
        carga = _leer("/proc/loadavg").split()
        if len(carga) >= 3:
            d.setdefault("cpu", {})["carga"] = [float(x) for x in carga[:3]]
        mhz = [_num(l.split(":")[1]) for l in _leer("/proc/cpuinfo").splitlines() if l.lower().startswith("cpu mhz")]
        if mhz:
            d.setdefault("cpu", {})["mhz"] = round(sum(mhz) / len(mhz))
        # memoria
        m = {}
        for l in _leer("/proc/meminfo").splitlines():
            k, _, v = l.partition(":")
            m[k] = int(v.split()[0]) * 1024 if v.split() else 0
        if m:
            total, disp = m.get("MemTotal", 0), m.get("MemAvailable", m.get("MemFree", 0))
            d["ram"] = {"total": total, "usada": total - disp, "disponible": disp, "cache": m.get("Cached", 0),
                        "swap_total": m.get("SwapTotal", 0), "swap_usada": m.get("SwapTotal", 0) - m.get("SwapFree", 0)}
        # discos (espacio)
        vistos, discos = set(), []
        for l in _leer("/proc/mounts").splitlines():
            p = l.split()
            if len(p) < 3 or p[2] not in self.FS_REALES or p[0] in vistos or "/snap/" in p[1]:
                continue
            vistos.add(p[0])
            try:
                s = os.statvfs(p[1])
            except OSError:
                continue
            total = s.f_blocks * s.f_frsize
            if total <= 0:
                continue
            libre = s.f_bavail * s.f_frsize
            discos.append({"montaje": p[1], "dispositivo": p[0], "fs": p[2], "total": total, "libre": libre,
                           "usado": total - s.f_bfree * s.f_frsize})
        d["discos"] = discos
        # lectura / escritura (discos enteros, no particiones)
        io = [0, 0]
        for l in _leer("/proc/diskstats").splitlines():
            p = l.split()
            if len(p) > 9 and re.fullmatch(r"(sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme\d+n\d+|mmcblk\d+)", p[2]):
                io[0] += int(p[5]) * 512
                io[1] += int(p[9]) * 512
        if self.prev_io and dt:
            d["io"] = {"lectura_bs": max(0, (io[0] - self.prev_io[0]) / dt), "escritura_bs": max(0, (io[1] - self.prev_io[1]) / dt)}
        self.prev_io = io
        # red
        red = {}
        for l in _leer("/proc/net/dev").splitlines()[2:]:
            nombre, _, datos = l.partition(":")
            nombre = nombre.strip()
            if nombre == "lo" or nombre.startswith(("veth", "docker", "br-", "virbr")):
                continue
            v = datos.split()
            if len(v) >= 9:
                red[nombre] = (int(v[0]), int(v[8]))
        if self.prev_red and dt:
            ifs = [{"nombre": n, "rx_bs": max(0, (rx - self.prev_red.get(n, (rx, tx))[0]) / dt),
                    "tx_bs": max(0, (tx - self.prev_red.get(n, (rx, tx))[1]) / dt)} for n, (rx, tx) in red.items()]
            d["red"] = {"rx_bs": sum(i["rx_bs"] for i in ifs), "tx_bs": sum(i["tx_bs"] for i in ifs), "interfaces": ifs}
        self.prev_red = red
        # temperaturas y ventiladores
        temps, vent = [], []
        for h in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            chip = _leer(h / "name", h.name)
            for t in sorted(h.glob("temp*_input")):
                v = _num(_leer(t))
                if v is None or v <= 0:
                    continue
                etiqueta = _leer(t.with_name(t.name.replace("_input", "_label")), "")
                temps.append({"nombre": f"{chip} {etiqueta}".strip(), "c": round(v / 1000, 1)})
            for f in sorted(h.glob("fan*_input")):
                v = _num(_leer(f))
                if v is not None:
                    vent.append({"nombre": f"{chip} {f.name.split('_')[0]}", "rpm": int(v)})
        if not temps:
            for z in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
                v = _num(_leer(z / "temp"))
                if v and v > 0:
                    temps.append({"nombre": _leer(z / "type", z.name), "c": round(v / 1000, 1)})
        d["temperaturas"], d["ventiladores"] = temps[:24], vent[:12]
        # bateria
        for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
            def v(n):
                return _num(_leer(b / n))
            lleno = v("energy_full") or v("charge_full")
            diseno = v("energy_full_design") or v("charge_full_design")
            ahora_c = v("energy_now") or v("charge_now")
            potencia = v("power_now") or v("current_now")
            estado = _leer(b / "status")
            minutos = None
            if potencia and ahora_c and estado == "Discharging":
                minutos = round(ahora_c / potencia * 60)
            elif potencia and ahora_c and lleno and estado == "Charging":
                minutos = round((lleno - ahora_c) / potencia * 60)
            d["bateria"] = {"porcentaje": v("capacity"), "estado": estado, "cargando": estado == "Charging",
                            "enchufado": estado in ("Charging", "Full", "Not charging"), "minutos": minutos,
                            "salud_pct": round(100 * lleno / diseno, 1) if lleno and diseno else None,
                            "ciclos": int(v("cycle_count")) if v("cycle_count") else None,
                            "fabricante": _leer(b / "manufacturer"), "modelo": _leer(b / "model_name")}
            break
        # procesos
        total_cpu = self._cpu_ticks().get("cpu", (0, 0))[0]
        procs, nuevos = [], {}
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            try:
                st = (p / "stat").read_text()
                nombre = st[st.index("(") + 1:st.rindex(")")]
                campos = st[st.rindex(")") + 2:].split()
                ticks = int(campos[11]) + int(campos[12])
                rss = int(campos[21]) * self.pagina
            except (OSError, ValueError, IndexError):
                continue
            nuevos[p.name] = (ticks, total_cpu)
            prev = self.prev_proc.get(p.name)
            cpu = 0.0
            if prev and total_cpu > prev[1]:
                cpu = 100 * (ticks - prev[0]) / (total_cpu - prev[1])
            procs.append({"pid": int(p.name), "nombre": nombre, "cpu": round(cpu, 1), "ram": rss})
        self.prev_proc = nuevos
        d["procesos"] = _top(procs)
        d["n_procesos"] = len(procs)
        d["uptime_s"] = int(_num(_leer("/proc/uptime").split(" ")[0], 0) or 0)
        d["usuarios"] = sorted({l.split()[0] for l in _run(["who"], 5).splitlines() if l.strip()})
        self.prev_t = ahora
        return d

    def lento(self) -> dict:
        d: dict = {"discos_salud": _smart_todos()}
        dmi = Path("/sys/class/dmi/id")
        cpu = next((l.split(":", 1)[1].strip() for l in _leer("/proc/cpuinfo").splitlines()
                    if l.lower().startswith(("model name", "hardware"))), platform.processor())
        os_nombre = next((l.split("=", 1)[1].strip('"') for l in _leer("/etc/os-release").splitlines()
                          if l.startswith("PRETTY_NAME=")), platform.platform())
        graficas = [l.split(":", 2)[-1].strip() for l in _run(["lspci"], 10).splitlines()
                    if re.search(r"VGA|3D|Display", l)] if shutil.which("lspci") else []
        d["inventario"] = {"fabricante": _leer(dmi / "sys_vendor"), "modelo": _leer(dmi / "product_name"),
                           "serie": _leer(dmi / "product_serial") or _leer(dmi / "board_serial"),
                           "bios": " ".join(x for x in (_leer(dmi / "bios_vendor"), _leer(dmi / "bios_version"),
                                                        _leer(dmi / "bios_date")) if x),
                           "placa": _leer(dmi / "board_name"), "cpu": cpu, "nucleos": os.cpu_count(),
                           "ram_total": _ram_total_linux(), "graficas": graficas, "sistema": os_nombre,
                           "nucleo_sistema": platform.release(), "arquitectura": platform.machine(),
                           "nombre": socket.gethostname(), "ips": _ips()}
        # actualizaciones pendientes
        pend = seg = None
        if shutil.which("apt-get"):
            salida = _run(["apt-get", "-s", "-o", "Debug::NoLocking=1", "upgrade"], 120)
            lineas = [l for l in salida.splitlines() if l.startswith("Inst ")]
            pend, seg = len(lineas), sum(1 for l in lineas if "security" in l.lower())
        elif shutil.which("dnf"):
            salida = _run(["dnf", "-q", "--cacheonly", "check-update"], 120)
            pend = sum(1 for l in salida.splitlines() if l and not l.startswith(("Obsoleting", " ")) and len(l.split()) >= 3)
            sec = _run(["dnf", "-q", "--cacheonly", "updateinfo", "list", "--security"], 120)
            seg = sum(1 for l in sec.splitlines() if l.strip())
        d["actualizaciones"] = {"pendientes": pend, "seguridad": seg,
                                "reinicio": Path("/var/run/reboot-required").exists() or Path("/run/reboot-required").exists()}
        if shutil.which("systemctl"):
            caidos = [l.split()[0] for l in _run(["systemctl", "--failed", "--no-legend", "--plain"], 20).splitlines() if l.strip()]
            d["servicios_caidos"] = caidos[:30]
        clam = shutil.which("clamscan") or shutil.which("clamd")
        d["antivirus"] = {"nombre": "ClamAV" if clam else "", "activo": bool(clam), "aplica": False}
        return d


def _ram_total_linux() -> int:
    for l in _leer("/proc/meminfo").splitlines():
        if l.startswith("MemTotal:"):
            return int(l.split()[1]) * 1024
    return 0


def _ips() -> list[str]:
    ips = set()
    try:
        for i in socket.getaddrinfo(socket.gethostname(), None):
            if ":" not in i[4][0] and not i[4][0].startswith("127."):
                ips.add(i[4][0])
    except OSError:
        pass
    try:   # la IP con la que se sale a la red (sin enviar nada)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ips)


def _top(procs: list[dict], n: int = 12) -> list[dict]:
    """Los que mas CPU y los que mas memoria gastan (sin repetir)."""
    por_cpu = sorted(procs, key=lambda p: (-p["cpu"], -p["ram"]))[:n]
    por_ram = sorted(procs, key=lambda p: -p["ram"])[:n]
    vistos, out = set(), []
    for p in por_cpu + por_ram:
        if p["pid"] not in vistos:
            vistos.add(p["pid"])
            out.append(p)
    return out


# =============================================================================================== SMART (Linux y Mac con smartctl)
def _smart_todos() -> list[dict]:
    if not shutil.which("smartctl"):
        return []
    try:
        lista = json.loads(_run(["smartctl", "--scan-open", "-j"], 30) or "{}").get("devices", [])
    except ValueError:
        return []
    out = []
    for dv in lista[:16]:
        try:
            j = json.loads(_run(["smartctl", "-j", "-a", "-d", dv.get("type", "auto"), dv["name"]], 60) or "{}")
        except (ValueError, KeyError):
            continue
        if not j.get("model_name") and not j.get("serial_number"):
            continue
        out.append(_smart_resumen(j, dv["name"]))
    return out


def _smart_resumen(j: dict, nombre: str) -> dict:
    attrs = {a.get("id"): a for a in (j.get("ata_smart_attributes") or {}).get("table", [])}
    nvme = j.get("nvme_smart_health_information_log") or {}
    rot = j.get("rotation_rate")
    tipo = "NVMe" if nvme else ("HDD" if rot and rot > 0 else "SSD")

    def raw(i):
        a = attrs.get(i)
        return (a or {}).get("raw", {}).get("value")
    desgaste = None
    if nvme:
        desgaste = nvme.get("percentage_used")
    else:
        for i in (231, 233, 177, 202, 169):     # vida restante / desgaste segun fabricante (valor normalizado 100 -> 0)
            a = attrs.get(i)
            if a and a.get("value") is not None and tipo != "HDD":
                desgaste = max(0, 100 - int(a["value"]))
                break
    escritos = None
    if nvme.get("data_units_written") is not None:
        escritos = nvme["data_units_written"] * 512000
    elif raw(241) is not None:
        escritos = raw(241) * 512 if raw(241) < 10 ** 13 else None
    reasignados = raw(5) or 0
    pendientes = raw(197) or 0
    incorregibles = raw(198) or 0
    errores_medio = nvme.get("media_errors", 0) or 0
    ok = (j.get("smart_status") or {}).get("passed")
    estado = "mal" if ok is False else ("atencion" if (reasignados or pendientes or incorregibles or errores_medio or
                                                       (desgaste is not None and desgaste >= 90) or
                                                       (nvme.get("available_spare") is not None and
                                                        nvme.get("available_spare", 100) <= nvme.get("available_spare_threshold", 10)))
                                       else "ok")
    temp = (j.get("temperature") or {}).get("current")
    return {"disco": nombre, "modelo": j.get("model_name", ""), "serie": j.get("serial_number", ""), "tipo": tipo,
            "capacidad": (j.get("user_capacity") or {}).get("bytes"), "estado": estado, "smart_ok": ok,
            "desgaste_pct": desgaste, "horas": (j.get("power_on_time") or {}).get("hours"),
            "encendidos": j.get("power_cycle_count"), "temperatura": temp, "reasignados": reasignados,
            "pendientes": pendientes, "incorregibles": incorregibles, "errores_medio": errores_medio,
            "escritos": escritos, "reserva_pct": nvme.get("available_spare")}


# =============================================================================================== WINDOWS
_PS_RAPIDO = r"""
$ErrorActionPreference='SilentlyContinue'
$o=@{}
$p=Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor
$o.cpu=@{ total=[double](($p|?{$_.Name -eq '_Total'}).PercentProcessorTime); nucleos=@($p|?{$_.Name -ne '_Total'}|sort {[int]$_.Name}|%{[double]$_.PercentProcessorTime}) }
$f=Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation -Filter "Name='_Total'"
if($f){ $o.cpu.mhz=[int]([double]$f.ProcessorFrequency*[double]$f.PercentofMaximumFrequency/100) }
$os=Get-CimInstance Win32_OperatingSystem
$pf=Get-CimInstance Win32_PageFileUsage
$o.ram=@{ total=[double]$os.TotalVisibleMemorySize*1024; disponible=[double]$os.FreePhysicalMemory*1024; usada=([double]$os.TotalVisibleMemorySize-[double]$os.FreePhysicalMemory)*1024;
  swap_total=[double](($pf|measure AllocatedBaseSize -Sum).Sum)*1048576; swap_usada=[double](($pf|measure CurrentUsage -Sum).Sum)*1048576 }
$o.uptime_s=[int]((Get-Date)-$os.LastBootUpTime).TotalSeconds
$o.discos=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3'|%{ @{montaje=$_.DeviceID; fs=$_.FileSystem; total=[double]$_.Size; libre=[double]$_.FreeSpace; usado=[double]$_.Size-[double]$_.FreeSpace; etiqueta=$_.VolumeName} })
$d=Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'"
$o.io=@{ lectura_bs=[double]$d.DiskReadBytesPersec; escritura_bs=[double]$d.DiskWriteBytesPersec; ocupado_pct=[double]$d.PercentDiskTime }
$n=@(Get-CimInstance Win32_PerfFormattedData_Tcpip_NetworkInterface|?{$_.Name -notmatch 'isatap|Teredo|Loopback|Pseudo'})
$o.red=@{ rx_bs=[double](($n|measure BytesReceivedPersec -Sum).Sum); tx_bs=[double](($n|measure BytesSentPersec -Sum).Sum); interfaces=@($n|%{@{nombre=$_.Name; rx_bs=[double]$_.BytesReceivedPersec; tx_bs=[double]$_.BytesSentPersec}}) }
$nc=[Environment]::ProcessorCount
$pr=@(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process|?{$_.Name -ne '_Total' -and $_.Name -ne 'Idle'})
$top=@($pr|sort PercentProcessorTime -Desc|select -First 12)+@($pr|sort WorkingSetPrivate -Desc|select -First 12)
$o.procesos=@($top|sort IDProcess -Unique|%{@{pid=[int]$_.IDProcess; nombre=($_.Name -replace '#\d+$',''); cpu=[math]::Round([double]$_.PercentProcessorTime/$nc,1); ram=[double]$_.WorkingSetPrivate}})
$o.n_procesos=$pr.Count
$t=@(Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature|%{@{nombre=($_.InstanceName -replace '^.*\\',''); c=[math]::Round([double]$_.CurrentTemperature/10-273.15,1)}}|?{$_.c -gt 0 -and $_.c -lt 120})
$o.temperaturas=$t
$b=Get-CimInstance Win32_Battery|select -First 1
if($b){
  $full=(Get-CimInstance -Namespace root/wmi BatteryFullChargedCapacity|select -First 1).FullChargedCapacity
  $des=(Get-CimInstance -Namespace root/wmi BatteryStaticData|select -First 1).DesignedCapacity
  $cyc=(Get-CimInstance -Namespace root/wmi BatteryCycleCount|select -First 1).CycleCount
  $st=Get-CimInstance -Namespace root/wmi BatteryStatus|select -First 1
  $min=$null; if($b.EstimatedRunTime -and $b.EstimatedRunTime -lt 71582788){ $min=[int]$b.EstimatedRunTime }
  $o.bateria=@{ porcentaje=[double]$b.EstimatedChargeRemaining; cargando=[bool]$st.Charging; enchufado=[bool]$st.PowerOnline; minutos=$min;
    salud_pct=$(if($full -and $des){[math]::Round(100*$full/$des,1)}else{$null}); ciclos=$(if($cyc){[int]$cyc}else{$null}); modelo=$b.Name; estado=[string]$b.BatteryStatus }
}
$u=(Get-CimInstance Win32_ComputerSystem).UserName
$o.usuarios=@($(if($u){$u}))
$o | ConvertTo-Json -Depth 5 -Compress
"""

_PS_LENTO = r"""
$ErrorActionPreference='SilentlyContinue'
$o=@{}
$cs=Get-CimInstance Win32_ComputerSystem; $bi=Get-CimInstance Win32_BIOS; $os=Get-CimInstance Win32_OperatingSystem
$cp=Get-CimInstance Win32_Processor|select -First 1; $bb=Get-CimInstance Win32_BaseBoard
$o.inventario=@{ fabricante=$cs.Manufacturer; modelo=$cs.Model; serie=$bi.SerialNumber; bios=("$($bi.Manufacturer) $($bi.SMBIOSBIOSVersion) $($bi.ReleaseDate)").Trim();
  placa=("$($bb.Manufacturer) $($bb.Product)").Trim(); cpu=($cp.Name -replace '\s+',' ').Trim(); nucleos=[int]$cp.NumberOfLogicalProcessors; nucleos_fisicos=[int]$cp.NumberOfCores;
  ram_total=[double]$cs.TotalPhysicalMemory; graficas=@(Get-CimInstance Win32_VideoController|%{$_.Name}); sistema="$($os.Caption) $($os.Version)";
  compilacion=$os.BuildNumber; arquitectura=$os.OSArchitecture; nombre=$env:COMPUTERNAME; dominio=$cs.Domain; ultimo_arranque=$os.LastBootUpTime.ToString('s');
  ips=@(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True'|%{$_.IPAddress}|?{$_ -notmatch ':'}) }
$sal=@()
foreach($pd in Get-PhysicalDisk){
  $r=$pd|Get-StorageReliabilityCounter
  $tipo=switch("$($pd.MediaType)"){ 'SSD'{if("$($pd.BusType)" -eq 'NVMe'){'NVMe'}else{'SSD'}} 'HDD'{'HDD'} default{"$($pd.BusType)"} }
  $est=switch("$($pd.HealthStatus)"){ 'Healthy'{'ok'} 'Warning'{'atencion'} 'Unhealthy'{'mal'} default{'ok'} }
  if($r.Wear -ge 90 -or $r.ReadErrorsUncorrected -gt 0 -or $r.WriteErrorsUncorrected -gt 0){ if($est -eq 'ok'){$est='atencion'} }
  $sal+=@{ disco="Disco $($pd.DeviceId)"; modelo=$pd.FriendlyName; serie="$($pd.SerialNumber)".Trim(); tipo=$tipo; capacidad=[double]$pd.Size; estado=$est;
    desgaste_pct=$(if($r.Wear -ne $null){[int]$r.Wear}else{$null}); horas=$(if($r.PowerOnHours){[int]$r.PowerOnHours}else{$null}); temperatura=$(if($r.Temperature){[int]$r.Temperature}else{$null});
    errores_lectura=[int]$r.ReadErrorsUncorrected; errores_escritura=[int]$r.WriteErrorsUncorrected; encendidos=$(if($r.StartStopCycleCount){[int]$r.StartStopCycleCount}else{$null}) }
}
$o.discos_salud=$sal
$mp=Get-MpComputerStatus
$av=@(Get-CimInstance -Namespace root/SecurityCenter2 AntiVirusProduct|%{$_.displayName})
$o.antivirus=@{ nombre=$(if($av.Count){$av -join ', '}elseif($mp){'Microsoft Defender'}else{''}); activo=[bool]($mp.AntivirusEnabled -or $av.Count); tiempo_real=[bool]$mp.RealTimeProtectionEnabled;
  firmas=$(if($mp.AntivirusSignatureLastUpdated){$mp.AntivirusSignatureLastUpdated.ToString('s')}else{$null}); aplica=$true }
$ign='gupdate|edgeupdate|sppsvc|RemoteRegistry|MapsBroker|TrustedInstaller|wuauserv|BITS|tiledatamodelsvc|gpsvc|sedsvc|WbioSrvc|CDPSvc|ShellHWDetection|UsoSvc|DoSvc|clr_optimization|stisvc|Intel|GoogleUpdater|WMPNetworkSvc|edgeupdatem|NetTcpPortSharing|DiagTrack|RtkAudio|uhssvc|wscsvc|SysMain'
$o.servicios_caidos=@(Get-CimInstance Win32_Service -Filter "StartMode='Auto' AND State<>'Running'"|?{$_.Name -notmatch $ign -and -not $_.DelayedAutoStart}|%{$_.DisplayName}|select -First 30)
$rb=(Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired') -or (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending')
$o.actualizaciones=@{ reinicio=[bool]$rb }
$o | ConvertTo-Json -Depth 6 -Compress
"""

_PS_ACTUALIZACIONES = r"""
$ErrorActionPreference='SilentlyContinue'
$s=(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
$r=$s.Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
$seg=0; foreach($u in $r.Updates){ if($u.MsrcSeverity -in 'Critical','Important'){ $seg++ } }
@{pendientes=[int]$r.Updates.Count; seguridad=$seg} | ConvertTo-Json -Compress
"""


class _Windows:
    def __init__(self):
        self.act = {"pendientes": None, "seguridad": None, "cuando": 0}

    def _ps(self, script: str, timeout: float = 60) -> dict:
        salida = _run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script], timeout)
        try:
            return json.loads(salida.strip().splitlines()[-1]) if salida.strip() else {}
        except (ValueError, IndexError):
            return {}

    def rapido(self) -> dict:
        d = self._ps(_PS_RAPIDO, 40)
        for k in ("temperaturas", "procesos", "discos", "usuarios"):
            if isinstance(d.get(k), dict):
                d[k] = [d[k]]
            d.setdefault(k, [])
        d["ventiladores"] = []
        d["procesos"] = _top(d.get("procesos") or [])
        return d

    def lento(self) -> dict:
        d = self._ps(_PS_LENTO, 120)
        if isinstance(d.get("discos_salud"), dict):
            d["discos_salud"] = [d["discos_salud"]]
        # buscar actualizaciones tarda (a veces un minuto): como mucho cada 6 horas
        if time.time() - self.act["cuando"] > 6 * 3600:
            a = self._ps(_PS_ACTUALIZACIONES, 300)
            if a:
                self.act = {**a, "cuando": time.time()}
        d.setdefault("actualizaciones", {}).update({k: self.act.get(k) for k in ("pendientes", "seguridad")})
        return d


# =============================================================================================== MAC
class _Mac:
    def __init__(self):
        self.prev_cpu = None
        self.prev_red = None
        self.prev_io = None
        self.prev_t = None
        self.act = {"pendientes": None, "cuando": 0}

    def _cpu_nucleos(self):
        """Ticks por nucleo con host_processor_info (lo mismo que usa el Monitor de Actividad)."""
        import ctypes
        import ctypes.util
        lib = ctypes.CDLL(ctypes.util.find_library("System"))
        lib.mach_host_self.restype = ctypes.c_uint
        n = ctypes.c_uint(0)
        info = ctypes.POINTER(ctypes.c_int)()
        cnt = ctypes.c_uint(0)
        if lib.host_processor_info(lib.mach_host_self(), 2, ctypes.byref(n), ctypes.byref(info), ctypes.byref(cnt)) != 0:
            return None
        return [(info[i * 4] + info[i * 4 + 1] + info[i * 4 + 3], info[i * 4 + 2]) for i in range(n.value)]   # (ocupado, libre)

    def rapido(self) -> dict:
        ahora = time.time()
        dt = (ahora - self.prev_t) if self.prev_t else None
        d: dict = {}
        try:
            c = self._cpu_nucleos()
        except Exception:
            c = None
        if c and self.prev_cpu and len(c) == len(self.prev_cpu):
            nuc = []
            for (o1, l1), (o0, l0) in zip(c, self.prev_cpu):
                tot = (o1 - o0) + (l1 - l0)
                nuc.append(round(100 * (o1 - o0) / tot, 1) if tot > 0 else 0.0)
            d["cpu"] = {"total": round(sum(nuc) / len(nuc), 1), "nucleos": nuc}
        self.prev_cpu = c
        carga = _run(["sysctl", "-n", "vm.loadavg"], 5).strip("{} \n").split()
        if len(carga) >= 3:
            d.setdefault("cpu", {})["carga"] = [_num(x, 0) for x in carga[:3]]
        total = int(_num(_run(["sysctl", "-n", "hw.memsize"], 5).strip(), 0) or 0)
        vm = _run(["vm_stat"], 5)
        pag = int(re.search(r"page size of (\d+)", vm).group(1)) if re.search(r"page size of (\d+)", vm) else 4096
        val = {k.strip(): int(v.strip().rstrip(".")) for k, v in re.findall(r"^(.+?):\s+(\d+)\.?$", vm, re.M)}
        disp = (val.get("Pages free", 0) + val.get("Pages inactive", 0) + val.get("Pages purgeable", 0)
                + val.get("Pages speculative", 0)) * pag
        sw = re.findall(r"(total|used) = ([\d.]+)M", _run(["sysctl", "-n", "vm.swapusage"], 5))
        swd = {k: float(v) * 1048576 for k, v in sw}
        d["ram"] = {"total": total, "disponible": disp, "usada": max(0, total - disp),
                    "swap_total": swd.get("total", 0), "swap_usada": swd.get("used", 0)}
        discos = []
        for m in ["/"] + [str(p) for p in Path("/Volumes").glob("*") if p.is_dir() and not p.is_symlink()]:
            try:
                s = os.statvfs(m)
            except OSError:
                continue
            tot = s.f_blocks * s.f_frsize
            if tot > 0:
                discos.append({"montaje": m, "total": tot, "libre": s.f_bavail * s.f_frsize, "usado": tot - s.f_bfree * s.f_frsize})
        d["discos"] = discos
        red = {}
        for l in _run(["netstat", "-ibn"], 10).splitlines()[1:]:
            p = l.split()
            if len(p) >= 10 and "<Link#" in p[2] and not p[0].startswith(("lo", "gif", "stf", "utun", "awdl", "llw", "bridge", "anpi", "ap")):
                red[p[0]] = (int(p[6]), int(p[9]))
        if self.prev_red and dt:
            ifs = [{"nombre": n, "rx_bs": max(0, (rx - self.prev_red.get(n, (rx, tx))[0]) / dt),
                    "tx_bs": max(0, (tx - self.prev_red.get(n, (rx, tx))[1]) / dt)} for n, (rx, tx) in red.items()]
            d["red"] = {"rx_bs": sum(i["rx_bs"] for i in ifs), "tx_bs": sum(i["tx_bs"] for i in ifs), "interfaces": ifs}
        self.prev_red = red
        mb = sum(_num(x, 0) for x in re.findall(r"\s([\d.]+)\s*$", _run(["iostat", "-Id"], 10), re.M))
        if self.prev_io is not None and dt:
            d["io"] = {"total_bs": max(0, (mb - self.prev_io) * 1048576 / dt)}
        self.prev_io = mb
        # bateria
        import plistlib
        try:
            bat = plistlib.loads(_run(["ioreg", "-rn", "AppleSmartBattery", "-a"], 10).encode() or b"")
            bat = bat[0] if isinstance(bat, list) and bat else None
        except Exception:
            bat = None
        if bat:
            maxc = bat.get("AppleRawMaxCapacity") or bat.get("NominalChargeCapacity") or bat.get("MaxCapacity")
            dis = bat.get("DesignCapacity")
            tr = bat.get("TimeRemaining") or bat.get("AvgTimeToEmpty")
            pct = bat.get("CurrentCapacity") if (bat.get("MaxCapacity") or 0) <= 100 else None
            if pct is None and bat.get("AppleRawCurrentCapacity") and maxc:
                pct = round(100 * bat["AppleRawCurrentCapacity"] / maxc)
            d["bateria"] = {"porcentaje": pct, "cargando": bool(bat.get("IsCharging")), "enchufado": bool(bat.get("ExternalConnected")),
                            "minutos": tr if tr and tr < 65535 else None,
                            "salud_pct": round(100 * maxc / dis, 1) if maxc and dis and maxc > 100 else None,
                            "ciclos": bat.get("CycleCount"), "temperatura": round(bat["Temperature"] / 100, 1) if bat.get("Temperature") else None}
        procs = []
        for l in _run(["ps", "-Aceo", "pid=,pcpu=,rss=,comm="], 10).splitlines():
            p = l.split(None, 3)
            if len(p) == 4:
                procs.append({"pid": int(p[0]), "cpu": round(_num(p[1], 0) / max(1, os.cpu_count() or 1), 1),
                              "ram": int(p[2]) * 1024, "nombre": p[3]})
        d["procesos"], d["n_procesos"] = _top(procs), len(procs)
        bt = re.search(r"sec = (\d+)", _run(["sysctl", "-n", "kern.boottime"], 5))
        d["uptime_s"] = int(time.time() - int(bt.group(1))) if bt else None
        d["usuarios"] = sorted({l.split()[0] for l in _run(["who"], 5).splitlines() if l.strip()})
        d["temperaturas"], d["ventiladores"] = [], []
        self.prev_t = ahora
        return d

    def lento(self) -> dict:
        d: dict = {}
        try:
            sp = json.loads(_run(["system_profiler", "SPHardwareDataType", "SPDisplaysDataType", "-json"], 90) or "{}")
        except ValueError:
            sp = {}
        hw = (sp.get("SPHardwareDataType") or [{}])[0]
        d["inventario"] = {"fabricante": "Apple", "modelo": hw.get("machine_name", "") + (f" ({hw.get('machine_model')})" if hw.get("machine_model") else ""),
                           "serie": hw.get("serial_number", ""), "bios": hw.get("boot_rom_version", ""),
                           "cpu": hw.get("chip_type") or hw.get("cpu_type", ""), "nucleos": os.cpu_count(),
                           "ram_total": int(_num(_run(["sysctl", "-n", "hw.memsize"], 5).strip(), 0) or 0),
                           "graficas": [g.get("sppci_model", "") for g in sp.get("SPDisplaysDataType", [])],
                           "sistema": f"macOS {platform.mac_ver()[0]}", "arquitectura": platform.machine(),
                           "nombre": socket.gethostname(), "ips": _ips()}
        sal = _smart_todos()
        if not sal:
            info = _run(["diskutil", "info", "disk0"], 20)
            m = re.search(r"SMART Status:\s+(.+)", info)
            if m:
                modelo = (re.search(r"Device / Media Name:\s+(.+)", info) or re.search(r"Media Name:\s+(.+)", info))
                estado = "ok" if "Verified" in m.group(1) else ("mal" if "Failing" in m.group(1) else "atencion")
                sal = [{"disco": "disk0", "modelo": modelo.group(1).strip() if modelo else "", "tipo": "SSD" if "Solid State:              Yes" in info or "Solid State: Yes" in info else "",
                        "estado": estado, "smart_ok": estado == "ok"}]
        d["discos_salud"] = sal
        if time.time() - self.act["cuando"] > 6 * 3600:
            out = _run(["softwareupdate", "-l"], 300)
            self.act = {"pendientes": len(re.findall(r"^\s*\* Label:", out, re.M)), "cuando": time.time()}
        fw = _run(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"], 10)
        d["actualizaciones"] = {"pendientes": self.act.get("pendientes"), "seguridad": None, "reinicio": False}
        d["antivirus"] = {"nombre": "XProtect (de Apple)", "activo": True, "aplica": False, "cortafuegos": "enabled" in fw.lower()}
        return d


# =============================================================================================== API
class Monitor:
    """Una instancia por agente: guarda lo necesario para calcular velocidades entre una muestra y la siguiente."""
    LENTO_CADA = 600

    def __init__(self):
        self.imp = {"linux": _Linux, "windows": _Windows, "darwin": _Mac}.get(SISTEMA, _Linux)()
        self.ultimo_lento = 0.0
        self.lento_cache: dict = {}
        self._lock = threading.Lock()
        self._lento_hilo = None

    def _lento(self):
        try:
            d = self.imp.lento()
            if d:
                self.lento_cache = d
        except Exception as exc:  # nunca tumbar al agente por la monitorizacion
            self.lento_cache = {**self.lento_cache, "error": str(exc)[:200]}

    def muestra(self) -> dict:
        with self._lock:
            try:
                d = self.imp.rapido()
            except Exception as exc:
                d = {"error": str(exc)[:200]}
        d["t"] = time.time()
        d["so"] = SISTEMA
        # lo lento va en un hilo aparte para no retrasar las muestras rapidas
        if time.time() - self.ultimo_lento > self.LENTO_CADA and not (self._lento_hilo and self._lento_hilo.is_alive()):
            self.ultimo_lento = time.time()
            self._lento_hilo = threading.Thread(target=self._lento, daemon=True)
            self._lento_hilo.start()
        if self.lento_cache:
            d["lento"] = self.lento_cache
        return d


if __name__ == "__main__":
    m = Monitor()
    m.muestra()
    time.sleep(1.5)
    if m._lento_hilo:
        m._lento_hilo.join(timeout=180)
    print(json.dumps(m.muestra(), indent=2, ensure_ascii=False, default=str))
