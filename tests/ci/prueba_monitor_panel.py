#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
Prueba de la monitorización en el panel (sin equipos): con datos de mentira de un equipo comprueba los avisos nuevos
(gráfica caliente, pantallazos, programas que se cuelgan, cortafuegos, portátil sin cifrar, contraseñas, administradores
nuevos, piezas cambiadas, semanas sin reiniciar, Internet), el «¿por qué va lento?», el botón «Es correcto» y que el
propio servidor de OCTOPUS también se monitoriza.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
F = []


def chk(c, n, x=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else x, flush=True)
    if not c:
        F.append(n)


tmp = tempfile.mkdtemp()
os.environ.update(DB_PATH=os.path.join(tmp, "p.db"), OCTOPUS_DATA=os.path.join(tmp, "data"),
                  ADMIN_PASSWORD="ClaveInicialDePrueba-123", PANEL_HTTPS="0", OCTOPUS_BOVEDA_DIR=os.path.join(tmp, "b"),
                  OCTOPUS_AUTOARREGLO="no", OCTOPUS_MONITOR_SERVIDOR="no")
sys.path.insert(0, str(RAIZ / "lib"))
import admin_panel as a  # noqa: E402

a.app.config.update(TESTING=True)
cl = a.app.test_client()


def tok(h):
    m = re.search(r'name="csrf_token" value="([^"]+)"', h)
    return m.group(1) if m else ""


cl.post("/login", data={"csrf_token": tok(cl.get("/login").get_data(as_text=True)), "username": "admin",
                        "password": "ClaveInicialDePrueba-123"})
nueva = "OtraClaveSegura-2026!"
cl.post("/cuenta/contrasena", data={"csrf_token": tok(cl.get("/cuenta/contrasena").get_data(as_text=True)),
                                    "actual": "ClaveInicialDePrueba-123", "nueva": nueva, "repetir": nueva})
cl.post("/bienvenida", data={"csrf_token": tok(cl.get("/bienvenida").get_data(as_text=True)), "modo": "casa"})
a.config_manager.set_config("monitorizacion", True)
mon = a._mon
with a.get_db_connection() as cx:
    cx.execute("INSERT INTO systems (hostname, ip_address, os_family, status, notes) VALUES ('PORTATIL-ANA', '10.0.0.7', "
               "'windows', 'unknown', '{}')")
    sid = cx.execute("SELECT id FROM systems WHERE hostname='PORTATIL-ANA'").fetchone()[0]
mon.activar(sid, True, "prueba")

lento = {"inventario": {"cpu": "Intel i5", "ram_total": 16 * 1024 ** 3, "sistema": "Windows 11", "placa": "X", "serie": "S1"},
         "discos_salud": [{"modelo": "SSD 1", "serie": "AAA", "estado": "ok"}],
         "cortafuegos": {"activo": False, "apagados": ["Public"]}, "cifrado": {"que": "BitLocker", "activo": False},
         "fallos": {"reinicios": 1, "pantallazos": 2}, "cuelgues": [{"programa": "excel.exe", "veces": 7}],
         "accesos_fallidos": {"ultimas_24h": 35}, "administradores": ["ana"],
         "programas": [{"n": "Steam", "v": "1"}], "programas_total": 1, "inicio": [{"n": f"p{i}", "donde": "x"} for i in range(16)]}
muestra = {"cpu": {"total": 97.0}, "ram": {"total": 16 * 1024 ** 3, "usada": 15.5 * 1024 ** 3, "disponible": 0.5 * 1024 ** 3},
           "discos": [{"montaje": "C:", "total": 500 * 1024 ** 3, "libre": 10 * 1024 ** 3, "usado": 490 * 1024 ** 3}],
           "procesos": [{"pid": 1, "nombre": "chrome.exe", "cpu": 60.0, "ram": 6 * 1024 ** 3}],
           "bateria": {"porcentaje": 80}, "uptime_s": 40 * 86400,
           "gpu": [{"nombre": "RTX", "uso": 99, "temp": 93}],
           "internet": {"ok": True, "ms": 250, "ms_mediana": 260, "cortes_24h": 4, "comprobaciones": 200}, "lento": lento}
for _ in range(12):     # varios minutos de historial con la gráfica caliente
    mon.recibir(sid, json.loads(json.dumps(muestra)))
with mon._db() as c:
    c.execute("UPDATE monitor_hist SET gtemp = 93 WHERE system_id = ?", (sid,))
    ahora = int(time.time() // 60 * 60)
    for k in range(12):
        c.execute("INSERT OR REPLACE INTO monitor_hist (system_id, t, nivel, gtemp) VALUES (?, ?, 1, 93)", (sid, ahora - 60 * k))
mon.evaluar(sid)
cods = {x["codigo"] for x in mon.avisos(sid)}
for cod, que in (("OCT-MON-10", "gráfica caliente"), ("OCT-MON-11", "pantallazos y apagados de golpe"),
                 ("OCT-MON-12", "programa que se cuelga"), ("OCT-MON-13", "cortafuegos apagado"),
                 ("OCT-MON-14", "portátil sin cifrar"), ("OCT-MON-15", "muchas contraseñas mal"),
                 ("OCT-MON-17", "semanas sin reiniciar"), ("OCT-MON-19", "Internet va mal")):
    chk(cod in cods, f"aviso: {que} ({cod})", sorted(cods))
chk("OCT-MON-16" not in cods and "OCT-MON-18" not in cods, "la primera vez, lo que hay es lo normal (sin avisos)")

# cambian los administradores y las piezas
lento2 = dict(lento, administradores=["ana", "hacker"],
              inventario=dict(lento["inventario"], ram_total=8 * 1024 ** 3))
mon.recibir(sid, dict(json.loads(json.dumps(muestra)), lento=lento2))
cods = {x["codigo"]: x["detalle"] for x in mon.avisos(sid)}
chk("hacker" in cods.get("OCT-MON-16", ""), "aviso: administrador nuevo, con su nombre", cods.get("OCT-MON-16"))
chk("memoria: 16 → 8" in cods.get("OCT-MON-18", ""), "aviso: le han quitado memoria", cods.get("OCT-MON-18"))
h = cl.get(f"/monitorizacion/{sid}").get_data(as_text=True)
r = cl.post(f"/monitorizacion/{sid}/correcto", data={"csrf_token": tok(h)})
cods = {x["codigo"] for x in mon.avisos(sid)}
chk(r.status_code == 302 and "OCT-MON-16" not in cods and "OCT-MON-18" not in cods, "«Es correcto» quita esos avisos", cods)
mon.recibir(sid, dict(json.loads(json.dumps(muestra)), lento=lento2))
chk("OCT-MON-16" not in {x["codigo"] for x in mon.avisos(sid)}, "y no vuelven si nada cambia")

# ¿por qué va lento?
j = cl.get(f"/api/monitor/{sid}").get_json()
ex = " ".join(j.get("explica") or [])
chk("chrome.exe" in ex and "memoria" in ex.lower() and "procesador" in ex.lower() and "C:" in ex and "16 programas" in ex
    and "días sin reiniciarse" in ex, "«¿por qué va lento?» en frases", j.get("explica"))
chk(all(re.match(r"^[A-ZÁÉÍÓÚ¿]", x) for x in j.get("explica") or []), "frases que empiezan bien")
chk("Por qué suele pasar" in str(j.get("avisos")) or all(a_.get("causas") for a_ in j.get("avisos")), "cada aviso dice por qué suele pasar")
chk(all("PORTATIL-ANA" in a_["titulo"] or "{" not in a_["titulo"] for a_ in j.get("avisos")) and
    any("PORTATIL-ANA" in a_["titulo"] for a_ in j.get("avisos")), "los avisos dicen de qué equipo son",
    [a_["titulo"] for a_ in j.get("avisos")])
chk(mon.explicar({"cpu": {"total": 5}, "ram": {"total": 10, "usada": 2}}) == [], "si va bien, no se inventa nada")

# el propio servidor de OCTOPUS
sys.path.insert(0, str(RAIZ / "agentes"))
import octopus_monitor  # noqa: E402
a._servidor_monitor_una_vez(octopus_monitor)
time.sleep(2)
a._servidor_monitor_una_vez(octopus_monitor)
d0 = mon.ultimo(0) or {}
chk((d0.get("cpu") or {}).get("total") is not None and (d0.get("ram") or {}).get("total"), "el servidor de OCTOPUS se monitoriza solo",
    list(d0))
h = cl.get("/monitorizacion").get_data(as_text=True)
chk("Servidor OCTOPUS" in h, "aparece en la lista de Monitorización")
h = cl.get("/monitorizacion/0").get_data(as_text=True)
chk("Servidor OCTOPUS" in h and "es el ordenador donde está instalado OCTOPUS" in h, "tiene su pantalla (sin ficha de equipo)")
chk(cl.get("/api/monitor/0").status_code == 200, "y sus datos en directo")
with mon._db() as c:
    c.execute("INSERT OR REPLACE INTO monitor_avisos (system_id, codigo, detalle, desde, visto) VALUES (0, 'OCT-MON-03', 'x', 1, 1)")
t = cl.get("/avisos").get_data(as_text=True)
chk("Servidor OCTOPUS" in t, "sus avisos salen en Avisos")
print("FALLOS:", F or "ninguno")
sys.exit(1 if F else 0)
