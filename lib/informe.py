#!/usr/bin/env python3
"""
OCTOPUS Zero-Touch - Informe mensual (para el jefe o el cliente).

  python lib/informe.py [AAAA-MM]      imprime el informe del mes (por defecto, el mes actual)

En el panel: Ajustes -> "Ver el informe de este mes" (pagina lista para imprimir o guardar en PDF).
El dia 1, el mantenimiento nocturno envia por correo el informe del mes anterior (si esta activado).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mantenimiento as mant  # noqa: E402

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _limites(mes: str) -> tuple[datetime, datetime]:
    a, m = (int(x) for x in mes.split("-"))
    ini = datetime(a, m, 1).astimezone()
    fin = datetime(a + (m == 12), m % 12 + 1, 1).astimezone()
    return ini, fin


def mes_anterior(hoy: datetime | None = None) -> str:
    hoy = hoy or datetime.now()
    return f"{hoy.year - (hoy.month == 1)}-{(hoy.month - 2) % 12 + 1:02d}"


def nombre_mes(mes: str) -> str:
    a, m = mes.split("-")
    return f"{MESES[int(m) - 1]} de {a}"


def _parse(t: str):
    """Hora de restic o del panel ('2026-10-12T14:58:19.71Z', '...+02:00') a datetime con zona."""
    txt = str(t or "").strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(txt[:19])
    except ValueError:
        return None
    resto = txt[19:].lstrip(".0123456789")
    try:
        tz = datetime.fromisoformat("2000-01-01T00:00:00" + resto).tzinfo if resto else timezone.utc
    except ValueError:
        tz = timezone.utc
    return dt.replace(tzinfo=tz)


def datos(mes: str | None = None, env: dict | None = None) -> dict:
    env = env or mant.leer_env()
    mes = mes or datetime.now().strftime("%Y-%m")
    ini, fin = _limites(mes)
    # copias de cada equipo (directamente del almacen)
    copias: dict[str, list[datetime]] = {}
    repo, pwd = mant.repo_local(env)
    if repo and os.path.isdir(repo):
        r = mant.run([mant.restic_bin(), "snapshots", "--json", "--no-lock"], env=mant.restic_env(repo, pwd), timeout=600)
        try:
            for s in json.loads(r.stdout or "[]") or []:
                if "forense" in (s.get("tags") or []):
                    continue
                t = _parse(s.get("time", ""))
                if t:
                    copias.setdefault((s.get("hostname") or "").lower(), []).append(t)
        except ValueError:
            pass
    conn = sqlite3.connect(str(mant.db_path(env)))
    conn.row_factory = sqlite3.Row
    sistemas = conn.execute("SELECT id, hostname, os_family FROM systems ORDER BY hostname").fetchall()

    def contar(accion: str, host: str | None = None) -> int:
        q = "SELECT COUNT(*) FROM audit_logs WHERE action = ? AND timestamp >= ? AND timestamp < ?"
        args = [accion, ini.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                fin.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")]
        if host:
            q += " AND details LIKE ?"
            args.append(f"%{host}%")
        try:
            return conn.execute(q, args).fetchone()[0]
        except sqlite3.Error:
            return 0

    try:
        incidentes = [dict(r) for r in conn.execute(
            "SELECT id, hostname, detectado, motivo, estado FROM incidents ORDER BY detectado")]
    except sqlite3.Error:
        incidentes = []
    incidentes = [i for i in incidentes if (t := _parse(i["detectado"] or "")) and ini <= t < fin]
    pruebas = mant.leer_pruebas()
    equipos = []
    for s in sistemas:
        h = s["hostname"]
        todas = sorted(copias.get(h.lower(), []))
        del_mes = [t for t in todas if ini <= t < fin]
        p = pruebas.get(h.lower())
        equipos.append({
            "equipo": h, "sistema": s["os_family"] or "", "copias_mes": len(del_mes),
            "dias_con_copia": len({t.astimezone().date() for t in del_mes}),
            "ultima": todas[-1].astimezone().strftime("%d/%m/%Y %H:%M") if todas else "nunca",
            "prueba": ("correcta" if p["ok"] else "FALLO") + f" ({p['fecha'][8:10]}/{p['fecha'][5:7]}/{p['fecha'][:4]})" if p else "sin hacer",
            "prueba_ok": bool(p and p.get("ok")),
            "incidentes": sum(1 for i in incidentes if i["hostname"] == h),
        })
    conn.close()
    uso = None
    base = os.environ.get("OCTOPUS_BOVEDA_DIR") or mant.volumen_boveda()
    if base and os.path.isdir(base):
        du = shutil.disk_usage(base)
        uso = {"usado_gb": round(du.used / 2**30, 1), "total_gb": round(du.total / 2**30, 1),
               "porcentaje": round(du.used * 100 / du.total, 1)}
    hoy = datetime.now().astimezone()
    dias_mes = ((min(fin, hoy) - ini).days if hoy > ini else 0) or 1
    resumen = {
        "equipos": len(equipos),
        "copias": sum(e["copias_mes"] for e in equipos),
        "restauraciones": contar("RESTORE_OK"),
        "fallos_copia": contar("BACKUP_ERROR"),
        "incidentes": len(incidentes),
        "pruebas_ok": sum(1 for e in equipos if e["prueba_ok"]),
        "cobertura": round(100 * sum(min(e["dias_con_copia"], dias_mes) for e in equipos) / (dias_mes * len(equipos)))
        if equipos else 0,
    }
    return {"mes": mes, "nombre_mes": nombre_mes(mes), "generado": hoy.strftime("%d/%m/%Y %H:%M"),
            "dias_mes": dias_mes, "resumen": resumen, "equipos": equipos, "incidentes": incidentes, "almacen": uso,
            "mantenimiento": mant.leer_estado()}


def texto(d: dict) -> str:
    r = d["resumen"]
    lineas = [
        f"OCTOPUS Zero-Touch - Informe de {d['nombre_mes']}",
        f"Generado el {d['generado']}",
        "",
        f"Equipos protegidos .............. {r['equipos']}",
        f"Copias hechas ................... {r['copias']}",
        f"Dias con copia (todos los equipos) {r['cobertura']} %",
        f"Pruebas de recuperacion correctas {r['pruebas_ok']} de {r['equipos']}",
        f"Recuperaciones de archivos ...... {r['restauraciones']}",
        f"Copias fallidas ................. {r['fallos_copia']}",
        f"Ataques detectados .............. {r['incidentes']}",
    ]
    if d["almacen"]:
        a = d["almacen"]
        lineas.append(f"Espacio del almacen ............. {a['usado_gb']} de {a['total_gb']} GB ({a['porcentaje']} %)")
    lineas += ["", "Equipo | copias en el mes | dias con copia | ultima copia | prueba de recuperacion | ataques"]
    for e in d["equipos"]:
        lineas.append(f"{e['equipo']} | {e['copias_mes']} | {e['dias_con_copia']}/{d['dias_mes']} | {e['ultima']} | "
                      f"{e['prueba']} | {e['incidentes']}")
    if d["incidentes"]:
        lineas += ["", "Ataques del mes:"]
        for i in d["incidentes"]:
            lineas.append(f"  #{i['id']} {i['hostname']} - {str(i['detectado'])[:16]} - {i['motivo']} ({i['estado']})")
    return "\n".join(lineas) + "\n"


def enviar(env: dict, mes: str) -> dict:
    """Envia el informe por correo (y un resumen por Telegram). Lo llama el mantenimiento el dia 1."""
    try:
        from config_manager import ConfigManager
        from notifications import NotificationManager
        from telegram_integration import TelegramIntegration
        cm = ConfigManager(str(mant.db_path(env)))
        if not cm.get_config("informe_mensual"):
            return {"ok": True, "detalle": "Informe mensual desactivado en Ajustes"}
        d = datos(mes, env)
        t = texto(d)
        cfg = cm.get_config()
        enviado = False
        nm = NotificationManager(cm)
        para = [c for c in nm.destinatarios("informe", cfg) if c]
        if cfg.get("email_notifications") and para:
            enviado = all(nm.send_email(c, f"[OCTOPUS] Informe de {d['nombre_mes']}", t)[0] for c in para)
        r = d["resumen"]
        TelegramIntegration(cm).send_alert("medium", f"Informe de {d['nombre_mes']}: {r['equipos']} equipos, "
                                                     f"{r['copias']} copias, {r['cobertura']} % de dias con copia, "
                                                     f"{r['incidentes']} ataques.", level="high")
        return {"ok": True, "detalle": f"Informe de {d['nombre_mes']} " + ("enviado por correo" if enviado else
                                                                             "generado (correo sin configurar)")}
    except Exception as exc:
        return {"ok": False, "detalle": f"No se pudo enviar el informe: {exc}"}


if __name__ == "__main__":
    print(texto(datos(sys.argv[1] if len(sys.argv) > 1 else None)))
