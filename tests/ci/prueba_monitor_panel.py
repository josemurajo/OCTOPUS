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
a._aa.ESTADO_FILE = Path(tmp) / "autoarreglos.json"     # que la prueba no use (ni deje) estado en la carpeta del programa
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

# pantallazos y cuelgues explicados
fx = mon.explicar_fallos({"fallos": {"pantallazos": 2, "reinicios": 1, "codigos": ["0x00000116", "0x00000116", "0x0000abcd"]},
                          "cuelgues": [{"programa": "EXCEL.EXE", "modulo": "raro_addin.dll", "veces": 6},
                                       {"programa": "juego.exe", "modulo": "nvwgf2umx.dll", "veces": 3},
                                       {"programa": "app.exe", "modulo": "(no responde)", "veces": 2}]})
t = " ".join(fx)
chk("tarjeta gráfica" in t and t.count("0x00000116") == 1 and "0x0000abcd" in t, "pantallazo explicado (y sin repetir)", fx)
chk("corte de luz" in t, "apagado de golpe explicado")
chk("raro_addin.dll" in t and "complemento" in t and "juego.exe" in t and "controlador de la tarjeta gráfica" in t
    and "colgado" in t, "programas que se cuelgan, con el porqué", fx)

# copia fallida: primero se repite en silencio; solo hay mensaje si también falla al repetirla
mensajes, arreglos = [], []
_orig = (a._mandar_mensajes, a._avisos, a._equipos_con_estado, a._ejecutar_arreglo)
a._mandar_mensajes = lambda m: mensajes.extend(m)
aviso_copia = dict(a._av.ficha("OCT-EQ-04", equipo="PORTATIL-ANA"), id=sid, equipo="PORTATIL-ANA", riesgo=None, detalle="")
a._avisos = lambda lista: [dict(aviso_copia)]
a._equipos_con_estado = lambda *x, **k: [{"sys": {"id": sid}, "est": {"online": True}}]
a._ejecutar_arreglo = lambda cod, acc, row, uid, usr, al_terminar=None: arreglos.append(al_terminar)
a._autoarreglo_ciclo()
chk(len(arreglos) == 1 and not mensajes, "copia fallida: se repite sola sin mandar mensaje", mensajes)
arreglos[0](True, "copia hecha")
chk(not mensajes, "si al repetirla sale bien, no se molesta a nadie", mensajes)
a._aa.limpiar_viejos(set())
arreglos.clear()
a._autoarreglo_ciclo()
if arreglos:
    arreglos[0](False, "la copia volvió a fallar")
chk(len(mensajes) == 1 and "volvió a fallar" in str(mensajes), "si vuelve a fallar, entonces sí se avisa (una vez)", mensajes)
txt_m = str(mensajes)
chk("Por qué no he podido" in txt_m and "Cómo lo arreglas tú" in txt_m, "y dice por qué no ha podido y cómo arreglarlo", txt_m)
a._autoarreglo_ciclo()
chk(len(mensajes) == 1, "y no se repite el mensaje", len(mensajes))
a._mandar_mensajes, a._avisos, a._equipos_con_estado, a._ejecutar_arreglo = _orig

# el aviso de una copia que falló NO se va al darle a «Solucionar»: sigue (arreglándose) hasta que sale bien
from datetime import datetime as _dtm, timezone as _tz, timedelta as _td
ag = a.agentes
fila = a._get_system(sid)
ahora_j = _dtm.now(_tz.utc)
with ag._jobs_lock:
    ag.JOBS.clear()
    ag.JOBS["j1"] = {"id": "j1", "system_id": sid, "equipo": "PORTATIL-ANA", "tipo": "copia", "estado": "error",
                     "mensaje": "se perdió la conexión", "que": "Copia en curso...", "inicio": ahora_j - _td(hours=1),
                     "fin": ahora_j - _td(minutes=50)}
    ag.JOBS["j2"] = {"id": "j2", "system_id": sid, "equipo": "PORTATIL-ANA", "tipo": "copia", "estado": "en_curso",
                     "mensaje": "Copia en curso...", "que": "Copia en curso...", "inicio": ahora_j - _td(minutes=40), "fin": None}
with a.app.test_request_context():
    av_eq = [x for x in a._avisos(a._equipos_con_estado()) if x["codigo"] == "OCT-EQ-04" and x["id"] == sid]
chk(av_eq and av_eq[0].get("en_marcha", {}).get("minutos", 0) >= 39, "mientras se repite, el aviso sigue (arreglándose)", av_eq)
h = cl.get("/avisos").get_data(as_text=True)
chk("Arreglándose ahora" in h and 'name="desatascar"' in h and "Solucionar" in h, "y el botón sigue ahí para desatascarlo")
pedidos = []
import ordenes as _ordm
_ordm.pedir = lambda eq, m, ruta, d, t: pedidos.append(ruta) or {"status": "success"}
lanzados = []
a.agentes.lanzar_copia = lambda row, on_done=None, **k: lanzados.append(1)
meta = re.search(r'name="csrf-token" content="([^"]+)"', h).group(1)    # la tarjeta del aviso lo recibe por JavaScript
r = cl.post("/avisos/solucionar", data={"csrf_token": meta, "codigo": "OCT-EQ-04", "system_id": str(sid), "desatascar": "1"})
chk("/webhook/parar-copia" in pedidos and ag.JOBS["j2"]["estado"] == "error" and lanzados,
    "«Solucionar» con algo colgado: lo para en el equipo y lo empieza otra vez", (pedidos, ag.JOBS["j2"]["estado"]))
with ag._jobs_lock:
    ag.JOBS["j3"] = {"id": "j3", "system_id": sid, "equipo": "PORTATIL-ANA", "tipo": "copia", "estado": "ok",
                     "mensaje": "Copia terminada", "que": "Copia en curso...", "inicio": _dtm.now(_tz.utc), "fin": _dtm.now(_tz.utc)}
with a.app.test_request_context():
    av_eq = [x for x in a._avisos(a._equipos_con_estado()) if x["codigo"] == "OCT-EQ-04" and x["id"] == sid]
chk(not av_eq, "cuando sale bien, el aviso se quita solo", av_eq)

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
