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
    bateria muy gastada, memoria o procesador al limite mucho rato, equipo que ya no manda datos.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

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
        """)


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
        for t in ("monitor_equipos", "monitor_ultimo", "monitor_hist", "monitor_avisos"):
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
            "bateria": (d.get("bateria") or {}).get("porcentaje")}


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
                c.execute("INSERT INTO monitor_hist (system_id, t, nivel, cpu, ram, disco, temp, rx, tx, io, bateria) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (system_id, t, nivel, *r.values()))
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
    campos = ("cpu", "ram", "disco", "temp", "rx", "tx", "io", "bateria")
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
        q = "SELECT a.*, s.hostname FROM monitor_avisos a JOIN systems s ON s.id = a.system_id"
        filas = c.execute(q + (" WHERE a.system_id = ?" if system_id else "") + " ORDER BY a.desde",
                          (system_id,) if system_id else ()).fetchall()
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
