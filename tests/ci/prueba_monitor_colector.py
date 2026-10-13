#!/usr/bin/env python3
"""OCTOPUS - (pruebas de GitHub) el recolector de la monitorizacion en este sistema (Linux, Windows o Mac):
que saca procesador, memoria, discos, red, procesos, tiempo encendido, inventario y salud de discos con datos que tengan
sentido. Imprime lo que encuentra para poder revisarlo en el registro de GitHub."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agentes"))
import octopus_monitor  # noqa: E402

F = []


def chk(c, n, x=""):
    print(f"RESULT|{'PASS' if c else 'FAIL'}|{n}|{x}", flush=True)
    if not c:
        F.append(n)


m = octopus_monitor.Monitor()
t0 = time.time()
m.muestra()
t1 = time.time() - t0
time.sleep(2)
t0 = time.time()
d = m.muestra()
t2 = time.time() - t0
if m._lento_hilo:
    m._lento_hilo.join(timeout=400)
L = m.lento_cache
print(json.dumps({k: v for k, v in d.items() if k != "procesos"}, indent=1, default=str)[:4000])
print("LENTO:", json.dumps(L, indent=1, default=str)[:4000])
cpu = d.get("cpu") or {}
chk(isinstance(cpu.get("total"), (int, float)) and 0 <= cpu["total"] <= 100, "procesador total", cpu.get("total"))
chk(len(cpu.get("nucleos") or []) >= 1 and all(0 <= x <= 100 for x in cpu["nucleos"]), "procesador por núcleo", len(cpu.get("nucleos") or []))
ram = d.get("ram") or {}
chk(ram.get("total", 0) > 512 * 1024 ** 2 and 0 < ram.get("usada", 0) < ram["total"], "memoria", f"{ram.get('usada', 0) // 2**20} de {ram.get('total', 0) // 2**20} MB")
chk(any(x.get("total", 0) > 1024 ** 3 and 0 <= x.get("libre", -1) <= x["total"] for x in d.get("discos") or []), "espacio en disco",
    [x.get("montaje") for x in d.get("discos") or []])
chk(isinstance((d.get("red") or {}).get("rx_bs"), (int, float)), "red (bajada/subida)", (d.get("red") or {}).get("rx_bs"))
chk(isinstance(d.get("io"), dict) and len(d["io"]) > 0, "lectura y escritura de disco", d.get("io"))
procs = d.get("procesos") or []
chk(len(procs) >= 3 and all({"pid", "nombre", "cpu", "ram"} <= set(p) for p in procs), "procesos", len(procs))
chk(isinstance(d.get("uptime_s"), int) and d["uptime_s"] > 0, "tiempo encendido", d.get("uptime_s"))
inv = L.get("inventario") or {}
chk(bool(inv.get("cpu")) and bool(inv.get("sistema")), "inventario (procesador y sistema)", f"{inv.get('cpu')} / {inv.get('sistema')}")
chk(isinstance(L.get("discos_salud"), list), "salud de discos (lista, puede estar vacía en máquinas virtuales)", len(L.get("discos_salud") or []))
chk(t2 < 15, "una muestra tarda poco", f"{t2:.1f} s (la primera {t1:.1f} s)")
print("RESUMEN:", "TODO CORRECTO" if not F else "FALLOS: " + ", ".join(F))
sys.exit(1 if F else 0)
