#!/usr/bin/env python3
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


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 5 and a[0] == "preparar":
        sys.exit(preparar(a[1], a[2], a[3], a[4]))
    if len(a) == 3 and a[0] == "probar":
        sys.exit(probar(a[1], a[2]))
    print(__doc__)
    sys.exit(2)
