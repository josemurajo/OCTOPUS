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


def _token():
    return os.environ.get("OCTOPUS_AGENT_TOKEN", "")


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

    def health(self):
        return self._req("GET", "/health", timeout=10)

    def snapshots(self):
        return self._req("GET", "/snapshots", timeout=90)

    def info(self):
        return self._req("GET", "/info", timeout=20)

    def ls(self, path, snapshot="latest"):
        q = urllib.parse.urlencode({"path": path, "snapshot": snapshot})
        return self._req("GET", f"/ls?{q}", timeout=120)

    def backup(self):
        return self._req("POST", "/webhook/backup", timeout=6 * 3600)

    def copia_completa(self):
        return self._req("POST", "/webhook/copia-completa", timeout=12 * 3600)

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
    import shutil
    import subprocess
    env = dict(os.environ)
    repo_disco = os.path.join(os.environ.get("OCTOPUS_BOVEDA_DIR", ""), "octopus-backups")
    if os.environ.get("OCTOPUS_BOVEDA_DIR") and os.path.isdir(repo_disco):
        env["RESTIC_REPOSITORY"] = repo_disco
    env.setdefault("RESTIC_PASSWORD", os.environ.get("RESTIC_PASSWORD", ""))
    return shutil.which("restic") or "/usr/local/bin/restic", env, subprocess


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


def lanzar_copia(system, on_done=None, completa=False):
    """Lanza la copia (o la copia completa del equipo) en segundo plano y devuelve el id del trabajo."""
    job_id = uuid.uuid4().hex[:10]
    with _jobs_lock:
        for j in JOBS.values():
            if j["system_id"] == system["id"] and j["estado"] == "en_curso":
                return j["id"]
        JOBS[job_id] = {"id": job_id, "system_id": system["id"], "equipo": system["hostname"],
                        "tipo": "copia", "estado": "en_curso",
                        "mensaje": "Copia completa del equipo en curso (puede tardar horas)..." if completa else "Copia en curso...",
                        "inicio": datetime.now(timezone.utc), "fin": None}
    ip = ip_de(system)
    sid = system["id"]

    def _run():
        r = Agente(ip).copia_completa() if completa else Agente(ip).backup()
        ok = r.get("status") == "success"
        with _jobs_lock:
            JOBS[job_id].update(estado="ok" if ok else "error", fin=datetime.now(timezone.utc),
                                mensaje=("Copia completa terminada" if completa else "Copia terminada") if ok
                                else (r.get("message") or "Error desconocido"))
        invalidar(sid)
        if on_done:
            try:
                on_done(sid, ok, r)
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return job_id


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


def buscar_en_servidor(system, texto, exacta=None, max_copias=30, max_rutas=40):
    """Busca un archivo o carpeta por su nombre (o parte) en las copias de un equipo, directamente en el servidor.
    Devuelve cada ruta encontrada con sus versiones (de que copia, fecha, tamano), la mas reciente primero.
    Con exacta=<ruta> solo devuelve esa ruta (para elegir de cuando recuperarla)."""
    texto = (texto or "").replace("*", "").replace("?", "").strip()
    if not texto:
        return {"status": "error", "message": "Escribe el nombre (o parte del nombre) de lo que buscas"}
    copias, _ = copias_por_equipo()
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
    resultados.sort(key=lambda e: (e["tipo"] != "file", len(e["path"])))
    return {"status": "success", "resultados": resultados[:max_rutas], "total": len(resultados)}
