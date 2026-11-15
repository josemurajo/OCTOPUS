#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Monitorizacion de equipos (servidor): guarda lo que mandan los agentes, el historial y los avisos.

  - Viene apagada. Solo se monitoriza un equipo si se activa en el panel (Monitorizacion → Activar, o en su ficha)
    o desde la consola del servidor:
        octopus.sh monitorizacion estado
        octopus.sh monitorizacion activar <equipo|todos>      (pide confirmar que se ha informado a quien lo usa)
        octopus.sh monitorizacion pausar <equipo|todos>       (deja de recoger; guarda el historial)
        octopus.sh monitorizacion desinstalar <equipo|todos>  (borra su historial; pide escribir el nombre)
  - Mientras alguien mira la pantalla de un equipo, el agente manda cada 3 segundos; si no, cada minuto.
  - Historial: un punto por minuto durante 2 dias y un punto cada 15 minutos durante 90 dias.
  - Avisos (con codigo y que hacer): disco que falla o muy gastado, disco casi lleno, temperatura alta mantenida,
    bateria muy gastada, memoria o procesador al limite mucho rato, equipo que ya no manda datos, grafica caliente,
    pantallazos/reinicios inesperados, programas que se cuelgan, cortafuegos apagado, portatil sin cifrar, muchos
    intentos de contraseña, administradores nuevos, piezas cambiadas, semanas sin reiniciar e Internet que falla.
  - El propio servidor de OCTOPUS se monitoriza tambien (system_id 0, «Servidor OCTOPUS»), sin agente: lo recoge el
    panel (lib/admin_panel.py: _servidor_monitor_bucle).
  - explicar(): «¿por qué va lento?» en frases sencillas.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time

SERVIDOR = 0                   # el propio servidor de OCTOPUS (no está en la tabla de equipos)
NOMBRE_SERVIDOR = "Servidor OCTOPUS"
INTERVALO_VIVO = 3
INTERVALO_NORMAL = 60
VIVO_DURA = 90                 # segundos que dura el «en vivo» tras la ultima vez que alguien miro
_vivo: dict[int, float] = {}
_lock = threading.Lock()
_db_file = ""


def init(db_file: str) -> None:
    global _db_file
    _db_file = db_file
    with sqlite3.connect(db_file, timeout=30) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS monitor_equipos (system_id INTEGER PRIMARY KEY, activa INTEGER DEFAULT 1, desde TEXT,
                                                    por TEXT);
        CREATE TABLE IF NOT EXISTS monitor_ultimo (system_id INTEGER PRIMARY KEY, t REAL, datos TEXT, lento TEXT, lento_t REAL);
        CREATE TABLE IF NOT EXISTS monitor_hist (system_id INTEGER, t INTEGER, nivel INTEGER, cpu REAL, ram REAL,
                                                 disco REAL, temp REAL, rx REAL, tx REAL, io REAL, bateria REAL,
                                                 PRIMARY KEY (system_id, nivel, t));
        CREATE TABLE IF NOT EXISTS monitor_avisos (system_id INTEGER, codigo TEXT, detalle TEXT, desde REAL, visto REAL,
                                                   PRIMARY KEY (system_id, codigo));
        CREATE TABLE IF NOT EXISTS monitor_base (system_id INTEGER, clave TEXT, valor TEXT, PRIMARY KEY (system_id, clave));
        """)
        cols = {f[1] for f in c.execute("PRAGMA table_info(monitor_hist)")}
        for col in ("gpu", "gtemp"):
            if col not in cols:
                c.execute(f"ALTER TABLE monitor_hist ADD COLUMN {col} REAL")


def _db():
    c = sqlite3.connect(_db_file, timeout=30)
    c.row_factory = sqlite3.Row
    return c


# ----------------------------------------------------------------------------------------- activar / desactivar
def activa(system_id: int) -> bool:
    with _db() as c:
        f = c.execute("SELECT activa FROM monitor_equipos WHERE system_id = ?", (system_id,)).fetchone()
    return bool(f and f["activa"])


def activar(system_id: int, si: bool, quien: str = "") -> None:
    with _db() as c:
        c.execute("INSERT INTO monitor_equipos (system_id, activa, desde, por) VALUES (?, ?, datetime('now'), ?) "
                  "ON CONFLICT(system_id) DO UPDATE SET activa = excluded.activa, desde = excluded.desde, por = excluded.por",
                  (system_id, 1 if si else 0, quien))
        if not si:
            c.execute("DELETE FROM monitor_avisos WHERE system_id = ?", (system_id,))


def estado(system_id: int) -> str:
    """«desinstalada» (nunca activada o quitada del todo), «activa» o «pausada» (no recoge, pero guarda su historial)."""
    with _db() as c:
        f = c.execute("SELECT activa FROM monitor_equipos WHERE system_id = ?", (system_id,)).fetchone()
    return "desinstalada" if not f else "activa" if f["activa"] else "pausada"


def estados() -> dict[int, str]:
    with _db() as c:
        return {f[0]: "activa" if f[1] else "pausada" for f in c.execute("SELECT system_id, activa FROM monitor_equipos")}


def desinstalar(system_id: int) -> None:
    """Quita la monitorización de este equipo y BORRA todo lo que se había guardado de él."""
    with _db() as c:
        for t in ("monitor_equipos", "monitor_ultimo", "monitor_hist", "monitor_avisos", "monitor_base"):
            c.execute(f"DELETE FROM {t} WHERE system_id = ?", (system_id,))
    with _lock:
        _vivo.pop(system_id, None)


def activos() -> list[int]:
    with _db() as c:
        return [f[0] for f in c.execute("SELECT system_id FROM monitor_equipos WHERE activa = 1")]


def mirar(system_id: int) -> None:
    """Alguien esta mirando la pantalla de este equipo: que mande datos cada pocos segundos."""
    with _lock:
        _vivo[system_id] = time.time() + VIVO_DURA


def intervalo(system_id: int) -> int:
    with _lock:
        return INTERVALO_VIVO if _vivo.get(system_id, 0) > time.time() else INTERVALO_NORMAL


# ----------------------------------------------------------------------------------------- recibir y leer
def _resumen(d: dict) -> dict:
    """Los numeros que se guardan en el historial."""
    ram = d.get("ram") or {}
    discos = [x for x in d.get("discos") or [] if x.get("total")]
    temps = [t.get("c") for t in d.get("temperaturas") or [] if isinstance(t.get("c"), (int, float))]
    io = d.get("io") or {}
    return {"cpu": (d.get("cpu") or {}).get("total"),
            "ram": round(100 * ram["usada"] / ram["total"], 1) if ram.get("total") else None,
            "disco": max((round(100 * x["usado"] / x["total"], 1) for x in discos), default=None),
            "temp": max(temps) if temps else None,
            "rx": (d.get("red") or {}).get("rx_bs"), "tx": (d.get("red") or {}).get("tx_bs"),
            "io": (io.get("lectura_bs") or 0) + (io.get("escritura_bs") or 0) + (io.get("total_bs") or 0) if io else None,
            "bateria": (d.get("bateria") or {}).get("porcentaje"),
            "gpu": max((g["uso"] for g in d.get("gpu") or [] if isinstance(g.get("uso"), (int, float))), default=None),
            "gtemp": max((g["temp"] for g in d.get("gpu") or [] if isinstance(g.get("temp"), (int, float))), default=None)}


def _privacidad() -> tuple[bool, bool, int]:
    """(ver programas abiertos, ver quién tiene sesión, días de historial) según Ajustes -> Funciones."""
    try:
        import funciones as _f
        return (_f.opcion("monitorizacion", "procesos") != "no", _f.opcion("monitorizacion", "usuarios") == "si",
                int(_f.opcion("monitorizacion", "dias")))
    except Exception:
        return True, False, 90


def recibir(system_id: int, d: dict) -> dict:
    """Muestra que llega de un agente. Devuelve lo que el agente tiene que hacer (activa / cada cuanto)."""
    if not activa(system_id):
        return {"activa": False, "intervalo": 300}
    if d.get("inactivo"):
        return {"activa": True, "intervalo": 2}
    # limpiar: nada de textos enormes ni listas sin fin
    lento = d.pop("lento", None)
    d["procesos"] = (d.get("procesos") or [])[:30]
    # privacidad (Ajustes -> Funciones -> Monitorización): lo que no se quiere ver no se guarda nunca
    ver_procesos, ver_usuarios, dias = _privacidad()
    if not ver_procesos:
        d.pop("procesos", None); d["procesos_ocultos"] = True
    if not ver_usuarios:
        d.pop("usuarios", None); d["usuarios_ocultos"] = True
    ahora = time.time()
    datos = json.dumps(d, default=str)[:400_000]
    with _db() as c:
        if lento:
            c.execute("INSERT INTO monitor_ultimo (system_id, t, datos, lento, lento_t) VALUES (?, ?, ?, ?, ?) "
                      "ON CONFLICT(system_id) DO UPDATE SET t = excluded.t, datos = excluded.datos, "
                      "lento = excluded.lento, lento_t = excluded.lento_t",
                      (system_id, ahora, datos, json.dumps(lento, default=str)[:400_000], ahora))
        else:
            c.execute("INSERT INTO monitor_ultimo (system_id, t, datos) VALUES (?, ?, ?) "
                      "ON CONFLICT(system_id) DO UPDATE SET t = excluded.t, datos = excluded.datos", (system_id, ahora, datos))
        r = _resumen(d)
        for nivel, paso in ((1, 60), (15, 900)):
            t = int(ahora // paso * paso)
            ant = c.execute("SELECT * FROM monitor_hist WHERE system_id = ? AND nivel = ? AND t = ?", (system_id, nivel, t)).fetchone()
            if ant:   # varias muestras en el mismo minuto: el maximo (lo que importa es ver los picos)
                vals = {k: max(x for x in (ant[k], r[k]) if x is not None) if (ant[k] is not None or r[k] is not None) else None
                        for k in r if k != "bateria"}
                vals["bateria"] = r["bateria"] if r["bateria"] is not None else ant["bateria"]
                c.execute(f"UPDATE monitor_hist SET {', '.join(k + ' = ?' for k in vals)} WHERE system_id = ? AND nivel = ? AND t = ?",
                          (*vals.values(), system_id, nivel, t))
            else:
                c.execute(f"INSERT INTO monitor_hist (system_id, t, nivel, {', '.join(r)}) "
                          f"VALUES (?, ?, ?, {', '.join('?' for _ in r)})", (system_id, t, nivel, *r.values()))
        c.execute("DELETE FROM monitor_hist WHERE system_id = ? AND ((nivel = 1 AND t < ?) OR (nivel = 15 AND t < ?))",
                  (system_id, ahora - 2 * 86400, ahora - dias * 86400))
    evaluar(system_id)
    return {"activa": True, "intervalo": intervalo(system_id)}


def ultimo(system_id: int) -> dict | None:
    with _db() as c:
        f = c.execute("SELECT * FROM monitor_ultimo WHERE system_id = ?", (system_id,)).fetchone()
    if not f:
        return None
    d = json.loads(f["datos"] or "{}")
    d["recibido"] = f["t"]
    d["lento"] = json.loads(f["lento"]) if f["lento"] else {}
    d["lento_t"] = f["lento_t"]
    return d


def historial(system_id: int, horas: float) -> dict:
    nivel = 1 if horas <= 48 else 15
    desde = time.time() - horas * 3600
    with _db() as c:
        filas = c.execute("SELECT * FROM monitor_hist WHERE system_id = ? AND nivel = ? AND t >= ? ORDER BY t",
                          (system_id, nivel, desde)).fetchall()
    campos = ("cpu", "ram", "disco", "temp", "rx", "tx", "io", "bateria", "gpu", "gtemp")
    return {"t": [f["t"] for f in filas], **{k: [f[k] for f in filas] for k in campos}, "paso": 60 * nivel}


# ----------------------------------------------------------------------------------------- avisos
def _abrir(c, sid, codigo, detalle):
    c.execute("INSERT INTO monitor_avisos (system_id, codigo, detalle, desde, visto) VALUES (?, ?, ?, ?, ?) "
              "ON CONFLICT(system_id, codigo) DO UPDATE SET detalle = excluded.detalle, visto = excluded.visto",
              (sid, codigo, detalle, time.time(), time.time()))


def _cerrar(c, sid, codigo):
    c.execute("DELETE FROM monitor_avisos WHERE system_id = ? AND codigo = ?", (sid, codigo))


def _sostenido(c, sid, campo, umbral, minutos):
    """¿Ha estado por encima del umbral todos los minutos del rato pedido?"""
    filas = c.execute(f"SELECT {campo} FROM monitor_hist WHERE system_id = ? AND nivel = 1 AND t >= ? ORDER BY t",
                      (sid, time.time() - minutos * 60)).fetchall()
    vals = [f[0] for f in filas if f[0] is not None]
    return len(vals) >= max(3, minutos * 0.6) and min(vals) >= umbral


def evaluar(system_id: int) -> None:
    d = ultimo(system_id) or {}
    lento = d.get("lento") or {}
    with _db() as c:
        malos = [x for x in lento.get("discos_salud") or [] if x.get("estado") == "mal" or x.get("smart_ok") is False]
        (_abrir(c, system_id, "OCT-MON-01", ", ".join(f"{x.get('modelo') or x.get('disco')}" for x in malos))
         if malos else _cerrar(c, system_id, "OCT-MON-01"))
        gastados = [x for x in lento.get("discos_salud") or [] if (x.get("desgaste_pct") or 0) >= 90]
        (_abrir(c, system_id, "OCT-MON-02", ", ".join(f"{x.get('modelo')} ({x.get('desgaste_pct')} % gastado)" for x in gastados))
         if gastados else _cerrar(c, system_id, "OCT-MON-02"))
        llenos = [x for x in d.get("discos") or [] if x.get("total") and x.get("libre") is not None
                  and (x["libre"] / x["total"] < 0.05 or x["libre"] < 2 * 1024 ** 3) and x["total"] > 8 * 1024 ** 3]
        (_abrir(c, system_id, "OCT-MON-03", ", ".join(f"{x['montaje']} ({x['libre'] / 1024 ** 3:.1f} GB libres)" for x in llenos))
         if llenos else _cerrar(c, system_id, "OCT-MON-03"))
        (_abrir(c, system_id, "OCT-MON-04", "más de 90 °C durante 10 minutos") if _sostenido(c, system_id, "temp", 90, 10)
         else _cerrar(c, system_id, "OCT-MON-04"))
        sal = (d.get("bateria") or {}).get("salud_pct")
        (_abrir(c, system_id, "OCT-MON-05", f"guarda el {sal:.0f} % de cuando era nueva") if sal is not None and sal < 50
         else _cerrar(c, system_id, "OCT-MON-05"))
        (_abrir(c, system_id, "OCT-MON-06", "más del 95 % durante 30 minutos") if _sostenido(c, system_id, "ram", 95, 30)
         else _cerrar(c, system_id, "OCT-MON-06"))
        (_abrir(c, system_id, "OCT-MON-07", "más del 95 % durante 30 minutos") if _sostenido(c, system_id, "cpu", 95, 30)
         else _cerrar(c, system_id, "OCT-MON-07"))
        av = lento.get("antivirus") or {}
        (_abrir(c, system_id, "OCT-MON-09", av.get("nombre") or "") if av.get("aplica") and av.get("tiempo_real") is False
         else _cerrar(c, system_id, "OCT-MON-09"))
        _cerrar(c, system_id, "OCT-MON-08")
        _evaluar_mas(c, system_id, d, lento)


def _si(c, sid, codigo, cond, detalle=""):
    _abrir(c, sid, codigo, detalle) if cond else _cerrar(c, sid, codigo)


def _base(c, sid, clave, valor):
    """Lo que había la primera vez (o la última vez que alguien dijo «es correcto»). Devuelve (antes, es_nuevo)."""
    f = c.execute("SELECT valor FROM monitor_base WHERE system_id = ? AND clave = ?", (sid, clave)).fetchone()
    if f is None:
        c.execute("INSERT INTO monitor_base (system_id, clave, valor) VALUES (?, ?, ?)", (sid, clave, json.dumps(valor)))
        return valor, True
    return json.loads(f["valor"]), False


def piezas(lento: dict) -> dict:
    """Las piezas del equipo que no deberían cambiar solas (para saber si alguien ha quitado o cambiado algo)."""
    inv = lento.get("inventario") or {}
    return {"procesador": inv.get("cpu") or "", "memoria_gb": round((inv.get("ram_total") or 0) / 1024 ** 3),
            "discos": sorted(f"{x.get('modelo') or ''} {x.get('serie') or ''}".strip()
                             for x in lento.get("discos_salud") or [] if x.get("serie") or x.get("modelo")),
            "placa": inv.get("placa") or "", "serie": inv.get("serie") or ""}


def _evaluar_mas(c, sid, d, lento):
    _si(c, sid, "OCT-MON-10", _sostenido(c, sid, "gtemp", 88, 10), "más de 88 °C durante 10 minutos")
    fa = lento.get("fallos") or {}
    n_fallos = (fa.get("reinicios") or 0) + (fa.get("pantallazos") or 0)
    porque = explicar_fallos(lento)
    _si(c, sid, "OCT-MON-11", n_fallos > 0, ", ".join(x for x in (
        f"{fa.get('pantallazos')} pantallazo(s)" if fa.get("pantallazos") else "",
        f"{fa.get('reinicios')} apagado(s) de golpe" if fa.get("reinicios") else "") if x) + " en 7 días. "
        + " ".join(p for p in porque if not p.startswith("«"))[:400])
    malos = [x for x in lento.get("cuelgues") or [] if (x.get("veces") or 0) >= 5]
    _si(c, sid, "OCT-MON-12", bool(malos), " ".join(p for p in porque if p.startswith("«") and
                                                  any(f"«{x['programa']}»" in p for x in malos))[:400]
        or ", ".join(f"{x['programa']} ({x['veces']} veces)" for x in malos[:3]))
    fw = (lento.get("cortafuegos") or {})
    _si(c, sid, "OCT-MON-13", fw.get("activo") is False, ", ".join(fw.get("apagados") or []))
    cif = lento.get("cifrado") or {}
    portatil = bool((d.get("bateria") or {}).get("porcentaje") is not None)
    _si(c, sid, "OCT-MON-14", cif.get("activo") is False and portatil, cif.get("que") or "")
    n = (lento.get("accesos_fallidos") or {}).get("ultimas_24h") or 0
    _si(c, sid, "OCT-MON-15", n >= 20, f"{n} en las últimas 24 horas")
    if "administradores" in lento:
        ahora = sorted(lento.get("administradores") or [])
        antes, _ = _base(c, sid, "administradores", ahora)
        nuevos = [x for x in ahora if x not in antes]
        _si(c, sid, "OCT-MON-16", bool(nuevos), ", ".join(nuevos))
    if lento.get("inventario"):
        ahora = piezas(lento)
        antes, _ = _base(c, sid, "piezas", ahora)
        nombres = {"procesador": "procesador", "memoria_gb": "memoria", "discos": "discos", "placa": "placa base",
                   "serie": "número de serie"}
        cambios = [f"{nombres[k]}: {antes.get(k)} → {v}" for k, v in ahora.items()
                   if antes.get(k) not in (None, "", 0, []) and v not in (None, "", 0, []) and v != antes.get(k)]
        _si(c, sid, "OCT-MON-18", bool(cambios), "; ".join(str(x) for x in cambios)[:300])
    up = d.get("uptime_s") or 0
    _si(c, sid, "OCT-MON-17", up > 30 * 86400, f"{int(up // 86400)} días encendido")
    i = d.get("internet") or {}
    lento_red = (i.get("ms_mediana") or 0) >= 200
    _si(c, sid, "OCT-MON-19", (i.get("cortes_24h") or 0) >= 3 or lento_red or (i.get("comprobaciones", 0) >= 3 and i.get("ok") is False),
        ", ".join(x for x in (f"{i.get('cortes_24h')} cortes en 24 h" if i.get("cortes_24h") else "",
                              f"tarda {i.get('ms_mediana'):.0f} ms en responder" if lento_red else "",
                              "ahora mismo sin Internet" if i.get("ok") is False else "") if x))


# Los pantallazos azules de Windows dicen un código. Los más frecuentes, en cristiano (de dónde suele venir y qué hacer).
PANTALLAZOS = {
    "0x00000116": ("el controlador de la tarjeta gráfica", "actualiza el controlador de la gráfica desde la web del fabricante"),
    "0x00000117": ("el controlador de la tarjeta gráfica", "actualiza el controlador de la gráfica desde la web del fabricante"),
    "0x00000119": ("el controlador de la tarjeta gráfica", "actualiza el controlador de la gráfica desde la web del fabricante"),
    "0x0000001a": ("la memoria (RAM)", "pasa el «Diagnóstico de memoria de Windows»; si da errores, cambia la memoria"),
    "0x00000050": ("la memoria o un controlador", "pasa el «Diagnóstico de memoria de Windows» y actualiza Windows"),
    "0x0000000a": ("un controlador (a menudo el de la red o el wifi)", "actualiza Windows y los controladores"),
    "0x000000d1": ("un controlador (a menudo el de la red o el wifi)", "actualiza los controladores de red y wifi"),
    "0x0000007e": ("un controlador o una pieza de Windows", "actualiza Windows y los controladores"),
    "0x0000003b": ("un controlador (a menudo el de la gráfica)", "actualiza Windows y el controlador de la gráfica"),
    "0x0000001e": ("un controlador", "actualiza Windows y los controladores"),
    "0x0000009f": ("un controlador al suspender o despertar", "actualiza los controladores; mientras, apágalo en vez de suspenderlo"),
    "0x00000133": ("un controlador o el disco SSD", "actualiza los controladores y el programa interno (firmware) del SSD"),
    "0x00000124": ("una pieza del ordenador (calor, procesador o fuente de alimentación)",
                   "revisa la temperatura, limpia el polvo y quita el «overclock» si lo hay"),
    "0x0000007a": ("el disco", "haz copia ya y revisa la salud del disco (en esta misma pantalla)"),
    "0x000000f4": ("el disco o un proceso de Windows", "revisa la salud del disco y actualiza Windows"),
    "0x000000ef": ("Windows dañado", "en una consola de administrador: sfc /scannow"),
    "0x00000139": ("un controlador o la memoria", "actualiza los controladores y pasa el diagnóstico de memoria"),
    "0x000000c2": ("un controlador", "actualiza los controladores (o quita el último programa instalado)"),
    "0x00000019": ("un controlador o la memoria", "actualiza los controladores y pasa el diagnóstico de memoria"),
}


def explicar_fallos(lento: dict) -> list[str]:
    """Por qué se ha caído o colgado algo, en frases sencillas."""
    out = []
    fa = lento.get("fallos") or {}
    vistos = set()
    for cod in fa.get("codigos") or []:
        cod = str(cod).lower()
        if cod in vistos:
            continue
        vistos.add(cod)
        if cod in PANTALLAZOS:
            de, que = PANTALLAZOS[cod]
            out.append(f"Pantallazo {cod}: suele venir de {de}. Qué hacer: {que}.")
        else:
            out.append(f"Pantallazo {cod}: busca ese código en Internet o enséñaselo a un técnico.")
    if fa.get("reinicios"):
        out.append(f"Se apagó de golpe {fa['reinicios']} vez/veces sin pantallazo: suele ser un corte de luz, el botón "
                   "de apagado o la fuente de alimentación.")
    for c in lento.get("cuelgues") or []:
        if (c.get("veces") or 0) < 2:
            continue
        prog, mod = c.get("programa") or "?", (c.get("modulo") or "").strip()
        ml = mod.lower()
        if mod == "(no responde)":
            por = "se quedó colgado (sin responder)"
        elif re.match(r"^(nv|amd|ati|ig|intel).*\.dll$", ml):
            por = "por el controlador de la tarjeta gráfica: actualízalo"
        elif not mod or ml == prog.lower():
            por = "por un fallo del propio programa: actualízalo"
        elif ml in ("ntdll.dll", "kernelbase.dll", "ucrtbase.dll", "msvcrt.dll"):
            por = "por un fallo interno (a menudo un complemento o archivos del programa dañados): actualízalo o reinstálalo"
        else:
            por = f"por una pieza llamada «{mod}» (a menudo un complemento): quita complementos o reinstala"
        out.append(f"«{prog}» se cerró {c['veces']} veces {por}.")
    return out


def aceptar_cambios(system_id: int) -> None:
    """«Es correcto»: los administradores y las piezas de ahora pasan a ser lo normal de este equipo."""
    with _db() as c:
        c.execute("DELETE FROM monitor_base WHERE system_id = ?", (system_id,))
        for cod in ("OCT-MON-16", "OCT-MON-18"):
            _cerrar(c, system_id, cod)
    evaluar(system_id)


def _gb(b):
    return f"{b / 1024 ** 3:.1f} GB" if b else "?"


def explicar(d: dict) -> list[str]:
    """«¿Por qué va lento?»: lo que ahora mismo puede estar frenando el equipo, en frases que entiende cualquiera."""
    if not d:
        return []
    out = []
    procs = d.get("procesos") or []
    top_cpu = max(procs, key=lambda p: p.get("cpu") or 0, default=None)
    top_ram = max(procs, key=lambda p: p.get("ram") or 0, default=None)
    cpu = (d.get("cpu") or {}).get("total")
    if cpu is not None and cpu >= 85:
        out.append(f"El procesador va al {cpu:.0f} %" + (f": lo está usando sobre todo «{top_cpu['nombre']}» "
                   f"({top_cpu['cpu']:.0f} %)." if top_cpu and (top_cpu.get("cpu") or 0) >= 15 else "."))
    ram = d.get("ram") or {}
    if ram.get("total"):
        p = 100 * ram["usada"] / ram["total"]
        if p >= 90:
            out.append(f"La memoria está casi llena ({p:.0f} %)" + (f": «{top_ram['nombre']}» usa {_gb(top_ram['ram'])}."
                       if top_ram and top_ram.get("ram") else ".") + " Cierra programas o pestañas que no uses.")
        if ram.get("swap_total") and ram.get("swap_usada", 0) / ram["swap_total"] > 0.5 and p >= 80:
            out.append("Está usando el disco como memoria de reserva: eso lo hace ir mucho más lento.")
    io = d.get("io") or {}
    if (io.get("ocupado_pct") or 0) >= 90:
        out.append("El disco está trabajando a tope (copiando, actualizando o un antivirus revisando).")
    for x in d.get("discos") or []:
        if x.get("total") and x.get("libre") is not None and x["libre"] / x["total"] < 0.08 and x["total"] > 8 * 1024 ** 3:
            out.append(f"El disco {x['montaje']} está casi lleno ({_gb(x['libre'])} libres): con poco sitio todo va más lento.")
    temps = [t.get("c") for t in d.get("temperaturas") or [] if isinstance(t.get("c"), (int, float))]
    if temps and max(temps) >= 90:
        out.append(f"Está muy caliente ({max(temps):.0f} °C): para enfriarse, el ordenador se frena solo.")
    for g in d.get("gpu") or []:
        if (g.get("temp") or 0) >= 88:
            out.append(f"La tarjeta gráfica está muy caliente ({g['temp']:.0f} °C).")
        elif (g.get("uso") or 0) >= 97:
            out.append("La tarjeta gráfica va al 100 % (normal si estás jugando; si no, algo la está usando).")
    i = d.get("internet") or {}
    if i.get("ok") is False:
        out.append("Ahora mismo no hay Internet: lo que use Internet irá mal.")
    elif (i.get("ms_mediana") or 0) >= 200:
        out.append(f"Internet tarda en responder ({i['ms_mediana']:.0f} ms): las webs y los juegos en línea irán lentos.")
    L = d.get("lento") or {}
    if len(L.get("inicio") or []) >= 15:
        out.append(f"Se abren {len(L['inicio'])} programas solos al encender: el arranque y el día a día van más lentos.")
    up = d.get("uptime_s") or 0
    if up > 14 * 86400:
        out.append(f"Lleva {int(up // 86400)} días sin reiniciarse: reiniciar de vez en cuando lo deja más ágil.")
    if (L.get("actualizaciones") or {}).get("reinicio"):
        out.append("Tiene actualizaciones esperando a que se reinicie.")
    return out


def revisar_silencio() -> None:
    """Equipos monitorizados que llevan mas de 30 min sin mandar nada (lo llama el vigilante del panel)."""
    with _db() as c:
        for sid in activos():
            f = c.execute("SELECT t FROM monitor_ultimo WHERE system_id = ?", (sid,)).fetchone()
            if f and time.time() - f["t"] > 1800:
                c.execute("INSERT OR IGNORE INTO monitor_avisos (system_id, codigo, detalle, desde, visto) VALUES (?, 'OCT-MON-08', '', ?, ?)",
                          (sid, time.time(), time.time()))


def avisos(system_id: int | None = None) -> list[dict]:
    with _db() as c:
        q = (f"SELECT a.*, COALESCE(s.hostname, '{NOMBRE_SERVIDOR}') AS hostname FROM monitor_avisos a "
             f"LEFT JOIN systems s ON s.id = a.system_id")
        filas = c.execute(q + (" WHERE a.system_id = ?" if system_id is not None else
                               f" WHERE s.id IS NOT NULL OR a.system_id = {SERVIDOR}") + " ORDER BY a.desde",
                          (system_id,) if system_id is not None else ()).fetchall()
    return [{"system_id": f["system_id"], "hostname": f["hostname"], "codigo": f["codigo"], "detalle": f["detalle"],
             "desde": f["desde"]} for f in filas]


# ----------------------------------------------------------------------------------------- consola del servidor
def main(argv: list[str]) -> int:
    import os
    import sys
    from seguridad import _db_por_defecto
    orden = argv[1] if len(argv) > 1 else "estado"
    que = argv[2] if len(argv) > 2 else ""
    informado = "--informado" in argv
    if orden not in ("estado", "activar", "pausar", "desinstalar") or (orden != "estado" and not que):
        print(__doc__)
        return 2
    db = _db_por_defecto()
    init(db)
    import config_manager
    import funciones
    import registro
    cm = config_manager.ConfigManager(db)
    funciones.usar(cm)
    with _db() as c:
        equipos = [dict(f) for f in c.execute("SELECT id, hostname FROM systems ORDER BY hostname")]
    if orden == "estado":
        est = estados()
        print("Monitorización:", "encendida" if funciones.activa("monitorizacion") else "APAGADA (viene así de serie)")
        for e in equipos:
            print(f"  {e['hostname']:<28} {est.get(e['id'], 'desinstalada')}")
        return 0
    elegidos = equipos if que == "todos" else [e for e in equipos if (e["hostname"] or "").lower() == que.lower()]
    if not elegidos:
        print(f"No hay ningún equipo «{que}». Mira los nombres con: octopus.sh monitorizacion estado")
        return 1
    nombres = ", ".join(e["hostname"] for e in elegidos)
    tty = sys.stdin.isatty()
    if orden == "activar" and not informado:
        if not tty:
            print("Falta confirmar que se ha informado a quien usa el equipo: añade --informado"); return 2
        r = input(f"¿Has informado a quien usa {nombres} (o no lo usa nadie)? Lo pide la ley de protección de datos. [s/N] ")
        if r.strip().lower() not in ("s", "si", "sí"):
            print("No se ha activado."); return 1
    if orden == "desinstalar":
        esperado = "todos" if que == "todos" else elegidos[0]["hostname"]
        if tty:
            r = input(f"Se borrará todo el historial de monitorización de {nombres}. Para confirmarlo escribe «{esperado}»: ")
        else:
            r = os.environ.get("OCTOPUS_CONFIRMAR", "")
        if r.strip().lower() != esperado.lower():
            print("No se ha desinstalado (no coincide)."); return 1
    if orden == "activar" and not funciones.activa("monitorizacion"):
        cm.set_config("monitorizacion", True)
        print("Monitorización encendida en el servidor.")
    for e in elegidos:
        if orden == "activar":
            activar(e["id"], True, "consola del servidor")
        elif orden == "pausar":
            activar(e["id"], False, "consola del servidor")
        else:
            desinstalar(e["id"])
    accion = {"activar": "MONITOR_ON", "pausar": "MONITOR_PAUSA", "desinstalar": "MONITOR_DESINSTALADA"}[orden]
    registro.escribir(db, None, accion, f"Desde la consola del servidor: {nombres}"
                      + (" (confirma que ha informado a quien lo usa)" if orden == "activar" else ""))
    print({"activar": "Activada", "pausar": "En pausa", "desinstalar": "Desinstalada y borrado su historial"}[orden] + ":", nombres)
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    sys.exit(main(sys.argv))
