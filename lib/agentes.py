# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Cliente de los agentes instalados en los equipos.

Las ordenes no se envian directamente al equipo: se dejan en la cola (lib/ordenes.py) y el agente
las recoge por HTTPS. Asi funciona con cualquier IP y sin puertos abiertos en los equipos.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

AGENT_PORT = int(os.environ.get("OCTOPUS_AGENT_PORT", "9999"))

_cache = {}
_cache_lock = threading.Lock()
CACHE_SECONDS = 20

# Trabajos en segundo plano (copias) -> se consultan desde el panel
JOBS = {}
_jobs_lock = threading.Lock()


def parse_time(value):
    """Convierte la hora de restic ('2026-10-09T19:33:20.1234+00:00') a datetime con zona."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    txt = str(value).strip().replace("Z", "+00:00")
    main, _, rest = txt.partition(".")
    tz = ""
    if rest:
        for sep in ("+", "-"):
            if sep in rest:
                tz = sep + rest.split(sep, 1)[1]
                break
    elif len(main) > 19:
        tz = main[19:]
        main = main[:19]
    try:
        dt = datetime.fromisoformat(main[:19] + tz)
    except ValueError:
        try:
            dt = datetime.strptime(main[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Agente:
    """Habla con el agente de un equipo a traves de la cola de ordenes."""

    def __init__(self, equipo, port=None, timeout=8):
        self.equipo = equipo
        self.timeout = timeout

    def _req(self, method, path, data=None, timeout=None):
        import ordenes
        return ordenes.pedir(self.equipo, method, path, data if method == "POST" else None, timeout or self.timeout)

    def snapshots(self):
        return self._req("GET", "/snapshots", timeout=90)

    def info(self):
        return self._req("GET", "/info", timeout=20)

    def backup(self):
        return self._req("POST", "/webhook/backup", timeout=6 * 3600)

    def copia_completa(self):
        return self._req("POST", "/webhook/copia-completa", timeout=12 * 3600)

    def bd(self):
        return self._req("GET", "/bd", timeout=90)

    def copia_bd(self, solo=None):
        return self._req("POST", "/webhook/copia-bd", {"solo": list(solo or [])}, timeout=12 * 3600)

    def restaurar_bd(self, snapshot, motor, nombre, instancia):
        return self._req("POST", "/webhook/restaurar-bd", {"snapshot": snapshot, "motor": motor, "nombre": nombre,
                                                           "instancia": instancia}, timeout=12 * 3600)

    def vms(self):
        return self._req("GET", "/vms", timeout=90)

    def copia_vms(self, solo=None):
        return self._req("POST", "/webhook/copia-vms", {"solo": list(solo or [])}, timeout=24 * 3600)

    def restaurar_vm(self, snapshot, nombre, hipervisor):
        return self._req("POST", "/webhook/restaurar-vm",
                         {"snapshot": snapshot, "nombre": nombre, "hipervisor": hipervisor}, timeout=24 * 3600)

    def restore(self, path, snapshot="latest", destino="original"):
        return self._req("POST", "/webhook/restaurar-archivo",
                         {"archivo": path, "snapshot": snapshot, "destino": destino}, timeout=3600)


def ip_de(system):
    """Identidad con la que se habla con el agente (su nombre: la cola de ordenes va por equipo)."""
    return system["hostname"]


_copias_cache = {"t": 0.0, "datos": {}, "error": None}
_copias_lock = threading.Lock()


def _restic_servidor():
    """restic en el propio servidor contra el almacen: se lee directamente del disco si se puede."""
    import subprocess
    env = dict(os.environ)
    boveda = os.environ.get("OCTOPUS_BOVEDA_DIR", "")
    try:   # si en el panel se pasaron las copias a otro disco (modo casa), mirar allí
        elegida = open(os.path.join(os.environ.get("OCTOPUS_DATA", "/data"), "boveda_ruta.txt"), encoding="utf-8").read().strip()
        boveda = elegida or boveda
    except OSError:
        pass
    repo_disco = os.path.join(boveda, "octopus-backups")
    if boveda and os.path.isdir(repo_disco):
        env["RESTIC_REPOSITORY"] = repo_disco
    env.setdefault("RESTIC_PASSWORD", os.environ.get("RESTIC_PASSWORD", ""))
    import mantenimiento as _m
    return _m.restic_bin(), env, subprocess


def copias_por_equipo(force=False):
    """Copias de TODOS los equipos con una sola consulta al almacen (cache de 30 s)."""
    with _copias_lock:
        if not force and time.time() - _copias_cache["t"] < 30:
            return _copias_cache["datos"], _copias_cache["error"]
        restic, env, subprocess = _restic_servidor()
        datos, error = {}, None
        try:
            r = subprocess.run([restic, "snapshots", "--json", "--no-lock"], env=env, capture_output=True,
                               text=True, timeout=120)
            if r.returncode == 0:
                for c in json.loads(r.stdout or "[]") or []:
                    t = parse_time(c.get("time"))
                    datos.setdefault((c.get("hostname") or "").lower(), []).append(
                        {"id": c.get("short_id") or c.get("id", "")[:8], "time": t, "paths": c.get("paths") or [],
                         "tags": c.get("tags") or []})
                for lista in datos.values():
                    lista.sort(key=lambda c: c["time"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            else:
                error = (r.stderr or "No se pudo leer el almacen")[-300:]
        except Exception as exc:  # restic ausente, tiempo agotado...
            error = str(exc)
        _copias_cache.update(t=time.time(), datos=datos, error=error)
        return datos, error


def notas_equipo(system) -> dict:
    """Ajustes guardados del equipo (columna notes, en JSON): rutas, horas_sin_copia..."""
    try:
        n = json.loads(system["notes"] or "{}") if "notes" in system.keys() else {}
        return n if isinstance(n, dict) else {}
    except (ValueError, TypeError):
        return {}


def horas_sin_copia(system) -> float:
    """Horas sin copia a partir de las cuales el equipo pasa a 'Copia antigua' y se avisa.
    Se puede ajustar por equipo (un portatil puede pasar dias fuera); si no, ALERTA_SIN_COPIA_HORAS (26)."""
    try:
        h = float(notas_equipo(system).get("horas_sin_copia") or 0)
    except (TypeError, ValueError):
        h = 0
    if h <= 0:
        try:
            h = float(os.environ.get("ALERTA_SIN_COPIA_HORAS", "26"))
        except ValueError:
            h = 26
    return h


# Lo pone el panel: refresca en segundo plano la lista de copias de un equipo que copia a OTRO destino
# (esas copias no están en el almacén del servidor: se las pregunta al equipo). Ver lib/destinos.py.
refrescar_destino = None


def estado_equipo(system, force=False):
    """Estado resumido de un equipo para el panel (con cache corta para que las paginas vayan rapido)."""
    import ordenes
    key = system["id"]
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not force and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    conectado = ordenes.en_linea(system["hostname"])
    todas, error = copias_por_equipo(force)
    copias = [c for c in todas.get(system["hostname"].lower(), []) if "forense" not in c["tags"]]
    notas = notas_equipo(system)
    try:
        import destinos
        if destinos.en_lugar(notas):
            copias = [c for c in destinos.lista_copias(notas.get("destino_copias")) if "forense" not in c["tags"]]
            if refrescar_destino and conectado and (force or time.time() - float(notas.get("destino_copias_t") or 0) > 1800):
                refrescar_destino(system)
    except Exception:
        pass
    info = {}
    try:
        info = json.loads(system["agent_info"] or "{}") if "agent_info" in system.keys() else {}
    except (ValueError, TypeError):
        info = {}
    est = {"online": conectado, "copias": copias, "ultima": copias[0]["time"] if copias else None,
           "error": None if conectado else "El equipo no está conectado", "info": info, "en_tunel": False}
    if error and not copias:
        est["error"] = error
    # Semaforo: ok / atencion / problema
    if not est["online"]:
        est["nivel"], est["texto"] = "problema", "Sin conexión"
    elif not est["ultima"]:
        est["nivel"], est["texto"] = "atencion", "Aún sin copias"
    elif (datetime.now(timezone.utc) - est["ultima"]).total_seconds() > horas_sin_copia(system) * 3600:
        est["nivel"], est["texto"] = "atencion", "Copia antigua"
    else:
        est["nivel"], est["texto"] = "ok", "Protegido"
    with _cache_lock:
        _cache[key] = (now, est)
    return est


def invalidar(system_id=None):
    with _copias_lock:
        _copias_cache["t"] = 0.0
    with _cache_lock:
        if system_id is None:
            _cache.clear()
        else:
            _cache.pop(system_id, None)


def _lanzar(system, tipo, mensaje, llamada, al_terminar, on_done=None):
    """Trabajo largo en segundo plano (copia, recuperación...) que se ve en la ficha del equipo."""
    job_id = uuid.uuid4().hex[:10]
    with _jobs_lock:
        for j in JOBS.values():
            if j["system_id"] == system["id"] and j["estado"] == "en_curso":
                return j["id"]
        JOBS[job_id] = {"id": job_id, "system_id": system["id"], "equipo": system["hostname"], "tipo": tipo,
                        "estado": "en_curso", "mensaje": mensaje, "inicio": datetime.now(timezone.utc), "fin": None}
    sid = system["id"]

    def _run():
        r = llamada()
        ok = r.get("status") == "success"
        with _jobs_lock:
            JOBS[job_id].update(estado="ok" if ok else "error", fin=datetime.now(timezone.utc),
                                mensaje=al_terminar(r) if ok else (r.get("message") or "Error desconocido"))
        invalidar(sid)
        if on_done:
            try:
                on_done(sid, ok, r)
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def lanzar_copia(system, on_done=None, completa=False, vms=False, bd=False):
    """Lanza la copia (la normal, la completa, la de sus máquinas virtuales o la de sus bases de datos) en segundo plano."""
    ag = Agente(ip_de(system))
    if bd:
        return _lanzar(system, "copia_bd", "Copia de las bases de datos en curso...", ag.copia_bd,
                       lambda r: "Bases de datos copiadas: " + ", ".join(b.get("nombre", "?") for b in r.get("bases", [])),
                       on_done)
    if vms:
        return _lanzar(system, "copia_vms", "Copia de las máquinas virtuales en curso (puede tardar horas)...",
                       ag.copia_vms, lambda r: "Máquinas virtuales copiadas: " + ", ".join(
                           v.get("nombre", "?") for v in r.get("vms", [])), on_done)
    if completa:
        return _lanzar(system, "copia", "Copia completa del equipo en curso (puede tardar horas)...",
                       ag.copia_completa, lambda r: "Copia completa terminada", on_done)
    return _lanzar(system, "copia", "Copia en curso...", ag.backup, lambda r: "Copia terminada", on_done)


def lanzar_restauracion_bd(system, snapshot, motor, nombre, instancia, on_done=None):
    """Recupera una base de datos como base NUEVA en el equipo (la original no se toca)."""
    return _lanzar(system, "recuperacion_bd", f"Recuperando la base de datos {nombre}...",
                   lambda: Agente(ip_de(system)).restaurar_bd(snapshot, motor, nombre, instancia),
                   lambda r: r.get("instrucciones") or f"{nombre} recuperada como {r.get('base_nueva')}", on_done)


def copia_bd_en_servidor(system, snapshot):
    """Datos de una copia de base de datos de este equipo leída en el servidor (para descargarla): (ruta, nombre)."""
    restic, env, subprocess = _restic_servidor()
    r = subprocess.run([restic, "snapshots", "--json", "--no-lock", "--tag", "bd"], env=env, capture_output=True,
                       text=True, timeout=300)
    try:
        snaps = json.loads(r.stdout or "[]") or []
    except ValueError:
        snaps = []
    s = next((x for x in snaps if (x.get("short_id") == snapshot or x.get("id", "").startswith(snapshot))
              and (x.get("hostname") or "").lower() == system["hostname"].lower()), None)
    if not s or not s.get("paths"):
        return None, None
    ruta = s["paths"][0]
    if len(ruta) > 1 and ruta[1] == ":":                       # Windows (C:\...) -> como lo guarda restic (/C/...)
        ruta = "/" + ruta[0] + ruta[2:].replace("\\", "/")
    return ruta, ruta.replace("\\", "/").rsplit("/", 1)[-1]


def volcar_bd_en_servidor(snapshot, ruta):
    """Proceso que va soltando el archivo de la copia (para mandarlo al navegador sin cargarlo entero en memoria)."""
    restic, env, subprocess = _restic_servidor()
    return subprocess.Popen([restic, "dump", "--no-lock", snapshot, ruta], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)


def lanzar_restauracion_vm(system, snapshot, nombre, hipervisor, on_done=None):
    """Recupera una máquina virtual en una carpeta aparte del equipo (la original no se toca)."""
    return _lanzar(system, "recuperacion", f"Recuperando la máquina virtual {nombre} (puede tardar)...",
                   lambda: Agente(ip_de(system)).restaurar_vm(snapshot, nombre, hipervisor),
                   lambda r: f"{nombre} recuperada en {r.get('carpeta')}. {r.get('instrucciones', '')}".strip(), on_done)


def trabajos_de(system_id=None, limit=10):
    with _jobs_lock:
        jobs = [dict(j) for j in JOBS.values() if system_id is None or j["system_id"] == system_id]
    jobs.sort(key=lambda j: j["inicio"], reverse=True)
    return jobs[:limit]


def _ruta_en_copia(path, windows):
    """Ruta tal y como restic la guarda (C:\\x\\y -> /C/x/y en Windows)."""
    p = str(path).replace("\\", "/") if windows else str(path)
    if windows and len(p) >= 2 and p[1] == ":":
        p = "/" + p[0].upper() + p[2:]
    return p.rstrip("/") or "/"


def listar_en_servidor(system, snapshot, path):
    """Explora una copia directamente en el servidor: funciona aunque el equipo este apagado o perdido."""
    copias, _ = copias_por_equipo()
    mias = copias.get(system["hostname"].lower(), [])
    copia = next((c for c in mias if c["id"] == snapshot or (snapshot == "latest" and c is mias[0])), None)
    if not copia:
        return {"status": "error", "message": "Esa copia no es de este equipo"}
    windows = (system["os_family"] or "").lower() == "windows"
    folder = _ruta_en_copia(path, windows)
    bases = [_ruta_en_copia(p, windows) for p in copia["paths"]]
    if not any(folder == b or folder.startswith(b.rstrip("/") + "/") for b in bases):
        return {"status": "error", "message": "Esa carpeta no forma parte de esta copia"}
    restic, env, subprocess = _restic_servidor()
    r = subprocess.run([restic, "ls", "--json", "--no-lock", copia["id"], folder], env=env,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return {"status": "error", "message": (r.stderr or r.stdout)[-300:]}
    items = []
    for line in (r.stdout or "").splitlines():
        try:
            node = json.loads(line)
        except ValueError:
            continue
        if node.get("struct_type") != "node":
            continue
        npath = node.get("path", "")
        if (npath.rsplit("/", 1)[0] or "/") != folder:
            continue
        if node.get("name") in SENUELOS:   # los archivos señuelo no se enseñan
            continue
        if windows and len(npath) > 2 and npath[0] == "/":
            vista = npath[1] + ":" + npath[2:].replace("/", "\\")
        else:
            vista = npath
        items.append({"name": node.get("name"), "type": node.get("type"), "size": node.get("size", 0),
                      "mtime": node.get("mtime"), "path": vista})
    items.sort(key=lambda x: (x["type"] != "dir", (x["name"] or "").lower()))
    return {"status": "success", "path": path, "items": items}


SENUELOS = {".octopus_no_tocar.docx", "~octopus_no_tocar.docx"}   # archivos trampa de los agentes (no se enseñan)


def buscar_en_servidor(system, texto, exacta=None, max_copias=None, max_rutas=40):
    """Busca un archivo o carpeta por su nombre (o parte) en las copias de un equipo, directamente en el servidor.
    Devuelve cada ruta encontrada con sus versiones (de que copia, fecha, tamano), la mas reciente primero.
    Con exacta=<ruta> solo devuelve esa ruta (para elegir de cuando recuperarla)."""
    texto = (texto or "").replace("*", "").replace("?", "").strip()
    if not texto:
        return {"status": "error", "message": "Escribe el nombre (o parte del nombre) de lo que buscas"}
    copias, _ = copias_por_equipo()
    # buscar: en las copias mas recientes (rapido); elegir de cuando: en mas copias para ver mas versiones
    max_copias = max_copias or (30 if exacta else 6)
    mias = [c for c in copias.get(system["hostname"].lower(), []) if "forense" not in c["tags"]][:max_copias]
    if not mias:
        return {"status": "error", "message": "Este equipo todavía no tiene copias"}
    windows = (system["os_family"] or "").lower() == "windows"
    restic, env, subprocess = _restic_servidor()
    cmd = [restic, "find", "--json", "--no-lock", "--ignore-case"]
    for c in mias:
        cmd += ["--snapshot", c["id"]]
    cmd.append(f"*{texto}*")
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    except Exception as exc:
        return {"status": "error", "message": f"No se pudo buscar: {exc}"}
    if r.returncode != 0 and not (r.stdout or "").strip():
        return {"status": "error", "message": (r.stderr or "No se pudo buscar")[-300:]}
    try:
        bloques = json.loads(r.stdout or "[]") or []
    except ValueError:
        bloques = []
    por_ruta = {}
    for b in bloques:
        sid = str(b.get("snapshot", ""))
        copia = next((c for c in mias if sid.startswith(c["id"])), None)
        if not copia:
            continue
        for m in b.get("matches") or []:
            npath = m.get("path", "")
            if npath.rsplit("/", 1)[-1] in SENUELOS:
                continue
            if windows and len(npath) > 2 and npath[0] == "/":
                vista = npath[1] + ":" + npath[2:].replace("/", "\\")
            else:
                vista = npath
            if exacta and vista.rstrip("/\\") != exacta.rstrip("/\\"):
                continue
            e = por_ruta.setdefault(vista, {"path": vista, "nombre": vista.replace("\\", "/").rsplit("/", 1)[-1],
                                            "tipo": m.get("type"), "versiones": []})
            e["versiones"].append({"copia": copia["id"], "fecha": copia["time"], "tamano": m.get("size", 0),
                                   "mtime": m.get("mtime"), "etiquetas": copia["tags"]})
    resultados = list(por_ruta.values())
    for e in resultados:
        e["versiones"].sort(key=lambda v: v["fecha"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    t = texto.lower()

    def orden(e):
        # primero lo de las carpetas protegidas de siempre (no solo de la copia completa de todo el disco),
        # luego lo que se llama como lo buscado, los archivos antes que las carpetas y las rutas mas cortas
        solo_completa = all("completa" in (v["etiquetas"] or []) for v in e["versiones"])
        nombre = e["nombre"].lower()
        return (solo_completa, not nombre.startswith(t), t not in nombre, e["tipo"] != "file", len(e["path"]))
    resultados.sort(key=orden)
    return {"status": "success", "resultados": resultados[:max_rutas], "total": len(resultados)}
