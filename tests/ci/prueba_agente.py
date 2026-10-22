#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - prueba automatica del agente en un sistema real (la usan las pruebas de GitHub y sirve a mano).

  python tests/ci/prueba_agente.py preparar <linux|windows|macos> <equipo> <carpeta_datos> <carpeta_instalador>
      da de alta el equipo, crea datos de prueba y deja el instalador del panel descomprimido
  python tests/ci/prueba_agente.py probar <equipo> <carpeta_datos>
      espera a que el agente conecte y prueba: copia, la copia en el almacen, estropear y restaurar un archivo,
      restaurar una carpeta y listar copias
Requiere el servidor en marcha en este mismo equipo (python lib/servidor.py).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "lib"))
for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in linea and not linea.lstrip().startswith("#"):
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))
DB = os.environ.get("DB_PATH", "./data/admin_panel.db")
DB = DB if os.path.isabs(DB) else str((RAIZ / DB).resolve())

import ordenes  # noqa: E402
ordenes.init(DB)
FALLOS: list[str] = []


def resultado(ok: bool, nombre: str, detalle: str = "") -> None:
    print(f"RESULT|{'PASS' if ok else 'FAIL'}|{nombre}|{str(detalle)[:300]}", flush=True)
    if not ok:
        FALLOS.append(nombre)


def preparar(so: str, equipo: str, datos: str, destino: str) -> int:
    import alta_equipos
    d = Path(datos)
    (d / "critico").mkdir(parents=True, exist_ok=True)
    (d / "critico" / "config.txt").write_text("config original", encoding="utf-8")
    (d / "documento.txt").write_text("datos importantes", encoding="utf-8")
    conn = sqlite3.connect(DB)
    if not conn.execute("SELECT 1 FROM systems WHERE hostname = ?", (equipo,)).fetchone():
        conn.execute("INSERT INTO systems (hostname, ip_address, os_family, status, notes) VALUES (?, '127.0.0.1', ?, 'unknown', ?)",
                     (equipo, so, json.dumps({"rutas": [str(d)]})))
    conn.commit()
    conn.close()
    paquete = alta_equipos.paquete(equipo, so, [str(d)], ordenes.nuevo_token(equipo))
    Path(destino).mkdir(parents=True, exist_ok=True)
    zip_path = Path(destino) / "octopus.zip"
    zip_path.write_bytes(paquete)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(destino)
        print("Instalador del panel:", ", ".join(z.namelist()))
    return 0


def pedir(equipo: str, metodo: str, ruta: str, datos=None, segundos: float = 120) -> dict:
    return ordenes.pedir(equipo, metodo, ruta, datos, segundos)


def probar(equipo: str, datos: str) -> int:
    import agentes
    d = Path(datos)
    for _ in range(90):
        if ordenes.en_linea(equipo):
            break
        time.sleep(2)
    resultado(ordenes.en_linea(equipo), "agente conectado al servidor (HTTPS saliente)")
    if FALLOS:
        return 1
    r = pedir(equipo, "GET", "/health", segundos=30)
    resultado(r.get("status") == "ok", "agente responde por la cola de ordenes", json.dumps(r))
    r = pedir(equipo, "GET", "/info", segundos=30)
    resultado(r.get("status") == "success", "informacion del equipo", f"{r.get('os')} {r.get('os_version')} rutas={r.get('backup_paths')}")
    r = pedir(equipo, "POST", "/webhook/backup", {}, segundos=1200)
    snap = r.get("snapshot_id", "")
    resultado(r.get("status") == "success" and bool(snap), "copia de seguridad", (snap[:8] + " " + r.get("aviso", "")) if snap else r.get("message"))
    copias, error = agentes.copias_por_equipo(force=True)
    mias = copias.get(equipo.lower(), [])
    resultado(any(c["id"] == snap[:8] for c in mias), "la copia esta en el almacen del servidor", f"{len(mias)} copias ({error or 'ok'})")
    archivo = d / "critico" / "config.txt"
    archivo.write_text("ESTROPEADO POR LA PRUEBA", encoding="utf-8")
    r = pedir(equipo, "POST", "/webhook/restaurar-archivo", {"archivo": str(archivo)}, segundos=600)
    contenido = archivo.read_text(encoding="utf-8") if archivo.exists() else "(no existe)"
    resultado(r.get("status") == "success" and contenido == "config original", "archivo restaurado", f"contenido={contenido!r} {r.get('message', '')}")
    for f in (d / "critico").iterdir():
        f.unlink()
    r = pedir(equipo, "POST", "/webhook/restaurar-archivo", {"archivo": str(d / "critico")}, segundos=600)
    n = len(list((d / "critico").iterdir()))
    resultado(r.get("status") == "success" and n > 0, "carpeta restaurada", f"{n} elementos {r.get('message', '')}")
    r = pedir(equipo, "GET", "/snapshots", segundos=120)
    resultado(r.get("status") == "success" and r.get("count", 0) > 0, "el agente lista sus copias", f"{r.get('count')} copias")
    print(f"\nRESUMEN: {'TODO CORRECTO' if not FALLOS else 'FALLOS: ' + ', '.join(FALLOS)}")
    return 1 if FALLOS else 0


def completa(equipo: str, carpeta: str) -> int:
    """Copia completa del equipo como la pide el panel (activarla en el equipo + «Hacer la copia completa ahora») y
    recuperar de ella un archivo que NO esta en las carpetas de la copia diaria (sale al lado, sin sobrescribir).
    `carpeta` es la raiz de la copia completa que tiene el agente (OCTOPUS_RUTA_COMPLETA en la prueba)."""
    import agentes
    d = Path(carpeta)
    archivo = d / "fuera_de_la_copia_diaria.txt"
    resultado(archivo.is_file(), "archivo de prueba fuera de las carpetas de la copia diaria", str(archivo))
    conn = sqlite3.connect(DB)
    fila = conn.execute("SELECT id, notes FROM systems WHERE hostname = ?", (equipo,)).fetchone()
    notas = json.loads(fila[1] or "{}") if fila else {}
    notas["copia_completa"] = True
    conn.execute("UPDATE systems SET notes = ? WHERE hostname = ?", (json.dumps(notas), equipo))
    conn.commit()
    conn.close()
    time.sleep(8)   # el agente recibe sus ajustes con cada consulta de ordenes (cada pocos segundos)
    t0 = time.time()
    r = pedir(equipo, "POST", "/webhook/copia-completa", {}, segundos=3600)
    snap = r.get("snapshot_id", "")
    resultado(r.get("status") == "success" and bool(snap), "copia completa del equipo",
              f"{snap[:8]} en {time.time() - t0:.0f} s, rutas={r.get('paths')} {r.get('aviso', '')}".strip() if snap
              else str(r.get("message"))[-300:])
    if not snap:
        return 1
    copias, error = agentes.copias_por_equipo(force=True)
    mias = [c for c in copias.get(equipo.lower(), []) if c["id"] == snap[:8]]
    resultado(bool(mias), "la copia completa esta en el almacen del servidor", error or "")
    r = pedir(equipo, "POST", "/webhook/restaurar-archivo", {"archivo": str(archivo), "snapshot": snap}, segundos=900)
    aparte = sorted(d.glob("fuera_de_la_copia_diaria.txt.restaurado-*"))
    contenido = aparte[-1].read_text(encoding="utf-8") if aparte else "(no aparece)"
    resultado(r.get("status") == "success" and contenido == archivo.read_text(encoding="utf-8"),
              "recuperar un archivo desde la copia completa (se deja al lado, no se sobrescribe)",
              f"{aparte[-1].name if aparte else ''} {r.get('message', '')}".strip())
    print(f"\nRESUMEN: {'TODO CORRECTO' if not FALLOS else 'FALLOS: ' + ', '.join(FALLOS)}")
    return 1 if FALLOS else 0


def destino(equipo: str, datos: str, carpeta_destino: str) -> int:
    """Destinos de copia: el equipo copia DIRECTO a otra carpeta («además» y luego «en lugar de» el servidor),
    se recupera desde allí, y la clave de esas copias va en el kit."""
    import subprocess
    import agentes
    import config_manager
    import destinos
    cm = config_manager.ConfigManager(DB)
    cm.set_config("destinos", True, None)

    def poner(form):
        conn = sqlite3.connect(DB)
        fila = conn.execute("SELECT notes FROM systems WHERE hostname = ?", (equipo,)).fetchone()
        notas, error = destinos.guardar(DB, json.loads(fila[0] or "{}"), form)
        conn.execute("UPDATE systems SET notes = ? WHERE hostname = ?", (json.dumps(notas), equipo))
        conn.commit()
        conn.close()
        time.sleep(10)   # el agente recibe sus ajustes con cada consulta de órdenes
        return notas, error

    def en_destino(notas):
        d = destinos.para_agente(DB, notas)
        env = dict(os.environ, RESTIC_REPOSITORY=d["repo"], RESTIC_PASSWORD=d["password"])
        env.pop("RESTIC_CACERT", None)
        r = subprocess.run([agentes._restic_servidor()[0], "snapshots", "--json", "--no-lock"], env=env,
                           capture_output=True, text=True, timeout=300)
        return [x.get("short_id") for x in json.loads(r.stdout or "[]") or []]

    notas, error = poner({"tipo": "carpeta", "ruta": carpeta_destino, "modo": "ademas"})
    resultado(error is None, "guardar el destino «otra carpeta, además»", error or carpeta_destino)
    r = pedir(equipo, "POST", "/webhook/destino-probar", {}, segundos=300)
    resultado(r.get("status") == "success", "probar el destino desde el panel", r.get("message"))
    r = pedir(equipo, "POST", "/webhook/backup", {}, segundos=1800)
    snap, dest = r.get("snapshot_id", "")[:8], (r.get("destino") or {})
    central = [c["id"] for c in agentes.copias_por_equipo(force=True)[0].get(equipo.lower(), [])]
    resultado(r.get("status") == "success" and snap in central, "«además»: la copia va al servidor OCTOPUS", snap)
    resultado(dest.get("status") == "success" and dest.get("snapshot_id", "")[:8] in en_destino(notas),
              "«además»: y otra directa a la otra carpeta", dest)
    notas, error = poner({"tipo": "carpeta", "ruta": carpeta_destino, "modo": "en_lugar"})
    r = pedir(equipo, "POST", "/webhook/backup", {}, segundos=1800)
    snap2 = r.get("snapshot_id", "")[:8]
    central = [c["id"] for c in agentes.copias_por_equipo(force=True)[0].get(equipo.lower(), [])]
    resultado(r.get("status") == "success" and snap2 in en_destino(notas) and snap2 not in central,
              "«en lugar de»: la copia va directa a la otra carpeta y no pasa por el servidor", snap2)
    archivo = Path(datos) / "documento.txt"
    archivo.write_text("ESTROPEADO", encoding="utf-8")
    r = pedir(equipo, "POST", "/webhook/restaurar-archivo", {"archivo": str(archivo)}, segundos=600)
    resultado(r.get("status") == "success" and archivo.read_text(encoding="utf-8") == "datos importantes",
              "recuperar un archivo desde la otra carpeta", r.get("message", ""))
    r = pedir(equipo, "GET", "/snapshots", segundos=120)
    resultado(r.get("count", 0) >= 2, "el equipo lista sus copias del otro destino (las ve el panel)", r.get("count"))
    kit = destinos.para_kit(DB, [(equipo, notas)])
    resultado(destinos.para_agente(DB, notas)["password"] in kit, "la clave de esas copias va en el kit de recuperación")
    poner({"tipo": "octopus"})
    print(f"\nRESUMEN: {'TODO CORRECTO' if not FALLOS else 'FALLOS: ' + ', '.join(FALLOS)}")
    return 1 if FALLOS else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == "destino":
        sys.exit(destino(a[1], a[2], a[3]))
    if len(a) == 3 and a[0] == "completa":
        sys.exit(completa(a[1], a[2]))
    if len(a) == 5 and a[0] == "preparar":
        sys.exit(preparar(a[1], a[2], a[3], a[4]))
    if len(a) == 3 and a[0] == "probar":
        sys.exit(probar(a[1], a[2]))
    print(__doc__)
    sys.exit(2)
