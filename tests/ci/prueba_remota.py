#!/usr/bin/env python3
"""
OCTOPUS - (pruebas) instalar OCTOPUS a distancia en un equipo, con el mismo codigo que el boton «Buscar equipos en la red»
(alta_grupo.alta + alta_grupo.instalar) y comprobar que el equipo queda conectado y responde.

Se ejecuta en el SERVIDOR, con sus ajustes cargados:
    OCTOPUS_PRUEBA_PASSWORD=...  python tests/ci/prueba_remota.py <ip> <so: windows|linux|macos> <usuario> <nombre>
La contrasena va en una variable de entorno (nunca en la linea de comandos ni en el registro).
"""
import os
import sqlite3
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / "lib"))

import alta_grupo     # noqa: E402
import configuracion  # noqa: E402
import ordenes        # noqa: E402

FALLOS = []


def resultado(ok, nombre, detalle=""):
    print(f"RESULT|{'PASS' if ok else 'FAIL'}|{nombre}|{detalle}", flush=True)
    if not ok:
        FALLOS.append(nombre)


def main(argv):
    if len(argv) != 5:
        print(__doc__)
        return 2
    ip, so, usuario, nombre = argv[1:]
    password = os.environ.get("OCTOPUS_PRUEBA_PASSWORD", "")
    if not password:
        print("Falta OCTOPUS_PRUEBA_PASSWORD (la contrasena del equipo de pruebas)")
        return 2
    env = configuracion.leer_env()
    db = env.get("DB_PATH", "./data/admin_panel.db")
    db = db if os.path.isabs(db) else str((BASE / db).resolve())
    ordenes.init(db)
    with sqlite3.connect(db) as c:          # empezar de cero si ya estaba de una prueba anterior
        c.execute("DELETE FROM systems WHERE hostname = ?", (nombre,))
    equipo = {"ip": ip, "nombre": nombre, "so": so, "ssh": True}
    resultado(alta_grupo.que_falta(equipo, usuario, password) == "", "se puede instalar a distancia (hay SSH y usuario)")
    sid = alta_grupo.alta(db, equipo, "Prueba SSH", "prueba remota")
    resultado(bool(sid), "dado de alta en el panel", f"id {sid}")
    pasos = []
    t0 = time.time()
    ok, msg = alta_grupo.instalar(db, sid, equipo, usuario, password, paso=lambda t: (pasos.append(t), print("   ", t, flush=True)))
    resultado(ok, "instalado por SSH y conectado al servidor", f"{int(time.time() - t0)} s: {msg}")
    resultado(len(pasos) >= 3, "va diciendo por donde va", " / ".join(pasos)[:200])
    resultado(password not in msg and all(password not in p for p in pasos), "la contrasena no aparece en ningun mensaje")
    if ok:
        r = None
        for _ in range(10):
            r = ordenes.pedir(nombre, "GET", "/health", None, 30)
            if r.get("status") == "ok":
                break
            time.sleep(3)
        resultado(isinstance(r, dict) and r.get("status") == "ok", "el equipo responde a las ordenes del servidor", str(r)[:150])
    with sqlite3.connect(db) as c:
        reg = [f[0] for f in c.execute("SELECT details FROM audit_logs ORDER BY id DESC LIMIT 20")]
    # (en las maquinas de pruebas el usuario y la contrasena pueden ser iguales: se quita el «usuario X» antes de mirar)
    limpio = [(d or "").replace(f"usuario {usuario}", "usuario ·") for d in reg]
    resultado(any(nombre in d for d in limpio) and not any(password in d for d in limpio),
              "queda en el registro de actividad, sin la contrasena")
    print("RESUMEN:", "TODO CORRECTO" if not FALLOS else "FALLOS: " + ", ".join(FALLOS))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
