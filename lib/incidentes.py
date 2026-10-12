"""
OCTOPUS - Respuesta automatica a incidentes y sala de analisis (sandbox).

Flujo ante un ataque critico en un equipo:
  1. Aislar el equipo (solo puede hablar con el servidor)
  2. Copia forense del estado infectado -> almacen de CUARENTENA (repositorio separado)
  3. Restaurar la ultima copia sana anterior al ataque (y borrar lo que dejo el ataque)
  4. Avisar al usuario del equipo
  5. El equipo sigue aislado hasta que seguridad lo libere (configurable)

Sala de analisis: la copia forense se recupera en el servidor y se examina dentro de un
contenedor Docker SIN RED, de solo lectura, sin privilegios y con limites de CPU/memoria.
"""
import hashlib
import json
import os
import secrets
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

import agentes

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX_ROOT = os.environ.get("OCTOPUS_SANDBOX_DIR", "/var/lib/octopus/sandbox")
SANDBOX_IMAGE = os.environ.get("OCTOPUS_SANDBOX_IMAGE", "octopus-sandbox:1")
DB_FILE = None  # lo fija init()
_notify = None  # funcion de aviso (correo/Telegram) que pasa el panel


def init(db_file, notify=None):
    global DB_FILE, _notify
    DB_FILE = db_file
    _notify = notify
    import ordenes  # la respuesta habla con los agentes por la cola de ordenes (misma base de datos)
    ordenes.init(db_file)
    conn = _db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER, hostname TEXT,
            creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            detectado TEXT, origen TEXT, severidad TEXT, motivo TEXT, evidencias TEXT,
            estado TEXT DEFAULT 'nuevo', aislado INTEGER DEFAULT 0,
            snapshot_forense TEXT, snapshot_restaurado TEXT,
            pasos TEXT DEFAULT '[]', clave_paquete TEXT, notas TEXT, cerrado TIMESTAMP
        )""")
    conn.commit()
    conn.close()


def _db():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _env(key, default=""):
    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# Incidentes
# ---------------------------------------------------------------------------
def obtener(inc_id):
    conn = _db()
    row = conn.execute("SELECT * FROM incidents WHERE id = ?", (inc_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["pasos"] = json.loads(d.get("pasos") or "[]")
    d["evidencias"] = json.loads(d.get("evidencias") or "[]")
    return d


def listar(limit=100):
    conn = _db()
    rows = conn.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["pasos"] = json.loads(d.get("pasos") or "[]")
        out.append(d)
    return out


def abiertos():
    conn = _db()
    n = conn.execute("SELECT COUNT(*) FROM incidents WHERE estado NOT IN ('cerrado')").fetchone()[0]
    conn.close()
    return n


def _paso(inc_id, texto, ok=True, detalle=""):
    conn = _db()
    row = conn.execute("SELECT pasos FROM incidents WHERE id = ?", (inc_id,)).fetchone()
    pasos = json.loads(row["pasos"] or "[]") if row else []
    pasos.append({"hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"), "texto": texto, "ok": ok,
                  "detalle": str(detalle)[:500]})
    conn.execute("UPDATE incidents SET pasos = ? WHERE id = ?", (json.dumps(pasos), inc_id))
    conn.commit()
    conn.close()


def ventanas_sospechosas(system_id) -> list:
    """Periodos en los que las copias de un equipo pueden llevar archivos del ataque: desde 2 minutos antes de
    detectarlo hasta que se restauro la copia sana (o se cerro el incidente). Si sigue abierto, hasta ahora."""
    try:
        conn = _db()
        rows = conn.execute("SELECT detectado, estado, cerrado, pasos FROM incidents WHERE system_id = ?",
                            (system_id,)).fetchall()
        conn.close()
    except sqlite3.Error:
        return []
    ventanas = []
    for r in rows:
        ini = agentes.parse_time(r["detectado"])
        if not ini:
            continue
        fin = None
        try:
            for p in json.loads(r["pasos"] or "[]"):
                if str(p.get("texto", "")).startswith("Restaurada la copia sana"):
                    fin = datetime.strptime(p["hora"], "%d/%m/%Y %H:%M:%S").astimezone()
        except (ValueError, TypeError, KeyError):
            pass
        if fin is None and r["estado"] == "cerrado" and r["cerrado"]:
            try:
                fin = datetime.fromisoformat(str(r["cerrado"])[:19]).astimezone()
            except ValueError:
                fin = None
        ventanas.append((ini - timedelta(minutes=2), fin))
    return ventanas


def marcar_copias(system_id, copias: list) -> list:
    """Copia de la lista de copias con 'sospechosa': True en las hechas durante un ataque."""
    ventanas = ventanas_sospechosas(system_id)
    salida = []
    for c in copias:
        c = dict(c)
        t = c.get("time")
        c["sospechosa"] = bool(t and any(t >= ini and (fin is None or t <= fin) for ini, fin in ventanas))
        salida.append(c)
    return salida


def ultima_limpia(copias_marcadas: list):
    return next((c for c in copias_marcadas if not c.get("sospechosa")), None)


def _set(inc_id, **campos):
    conn = _db()
    for k, v in campos.items():
        conn.execute(f"UPDATE incidents SET {k} = ? WHERE id = ?", (v, inc_id))
    conn.commit()
    conn.close()


def crear(system, motivo, evidencias=None, detectado=None, origen="agente", severidad="critica",
          auto=True, mantener_aislado=True, contacto="el departamento de seguridad"):
    """Registra el incidente y, si la respuesta automatica esta activa, la lanza en segundo plano."""
    conn = _db()
    # Evitar duplicados: si el equipo ya tiene un incidente abierto de los ultimos 30 min, se reutiliza
    prev = conn.execute("SELECT id FROM incidents WHERE system_id = ? AND estado NOT IN ('cerrado') "
                        "AND creado > datetime('now', '-30 minutes')", (system["id"],)).fetchone()
    if prev:
        conn.close()
        return prev["id"], False
    cur = conn.execute(
        "INSERT INTO incidents (system_id, hostname, detectado, origen, severidad, motivo, evidencias, estado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (system["id"], system["hostname"], detectado or datetime.now(timezone.utc).isoformat(), origen, severidad,
         motivo, json.dumps(evidencias or []), "respondiendo" if auto else "pendiente"))
    inc_id = cur.lastrowid
    conn.commit()
    conn.close()
    _paso(inc_id, f"Ataque detectado ({origen}): {motivo}", True)
    if _notify:
        try:
            _notify("incidente", f"INCIDENTE #{inc_id} en {system['hostname']}: {motivo}")
        except Exception:
            pass
    if auto:
        threading.Thread(target=responder, args=(inc_id, mantener_aislado, contacto), daemon=True).start()
    return inc_id, True


def _system(inc):
    conn = _db()
    row = conn.execute("SELECT * FROM systems WHERE id = ?", (inc["system_id"],)).fetchone()
    conn.close()
    return row


def responder(inc_id, mantener_aislado=True, contacto="el departamento de seguridad"):
    """Respuesta completa al incidente. Cada paso queda registrado en la linea de tiempo."""
    inc = obtener(inc_id)
    system = _system(inc)
    if not system:
        _paso(inc_id, "El equipo ya no existe en el panel", False)
        return
    _set(inc_id, estado="respondiendo")
    ag = agentes.Agente(agentes.ip_de(system), timeout=30)
    errores = 0

    # 1. Aislar
    r = ag._req("POST", "/webhook/aislamiento", {}, timeout=60)
    ok = r.get("status") == "success"
    errores += 0 if ok else 1
    _set(inc_id, aislado=1 if ok else 0)
    _paso(inc_id, "Equipo aislado de la red (solo puede hablar con el servidor)" if ok else "No se pudo aislar el equipo",
          ok, "" if ok else r.get("message"))

    # 2. Copia forense
    r = ag._req("POST", "/webhook/forense", {"incidente": str(inc_id)}, timeout=3600)
    ok = r.get("status") == "success"
    errores += 0 if ok else 1
    if ok:
        _set(inc_id, snapshot_forense=r.get("snapshot_id"))
    _paso(inc_id, "Copia forense del estado infectado guardada en cuarentena" if ok else "Fallo la copia forense",
          ok, r.get("snapshot_id") if ok else r.get("message"))

    # 3. Elegir la ultima copia sana anterior al ataque
    detectado = agentes.parse_time(inc["detectado"]) or datetime.now(timezone.utc)
    limite = detectado - timedelta(minutes=2)
    snaps = ag.snapshots()
    sana = None
    for c in sorted(snaps.get("snapshots", []), key=lambda c: c.get("time") or "", reverse=True):
        t = agentes.parse_time(c.get("time"))
        if t and t < limite:
            sana = c
            break
    if not sana:
        errores += 1
        _paso(inc_id, "No hay ninguna copia sana anterior al ataque: no se restaura nada", False)
    else:
        r = ag._req("POST", "/webhook/restaurar-limpio", {"snapshot": sana["id"]}, timeout=3600)
        ok = r.get("status") == "success"
        errores += 0 if ok else 1
        if ok:
            _set(inc_id, snapshot_restaurado=sana["id"])
        fecha = agentes.parse_time(sana.get("time"))
        fecha_txt = fecha.astimezone().strftime("%d/%m/%Y %H:%M") if fecha else sana["id"]
        _paso(inc_id, f"Restaurada la copia sana del {fecha_txt}" if ok else "Fallo la restauracion de la copia sana",
              ok, "" if ok else (r.get("message") or json.dumps(r.get("resultados"))))

        # 4. Aviso al usuario del equipo
        titulo = "AVISO DE SEGURIDAD - OCTOPUS"
        mensaje = (f"Se ha detectado una amenaza en este equipo y se ha restaurado automaticamente la copia de "
                   f"seguridad del {fecha_txt}.\n\nRevise sus documentos: los cambios posteriores a esa hora "
                   f"pueden no estar.\n\nPongase en contacto con {contacto} antes de seguir trabajando.\n"
                   f"Referencia del incidente: #{inc_id}")
        r = ag._req("POST", "/webhook/aviso", {"titulo": titulo, "mensaje": mensaje}, timeout=60)
        ok = r.get("status") == "success"
        _paso(inc_id, "Aviso mostrado al usuario del equipo" if ok else "No se pudo mostrar el aviso al usuario",
              ok, ", ".join(r.get("donde", [])) if ok else r.get("message"))

    # 5. Mantener aislado o reincorporar
    if not mantener_aislado:
        liberar(inc_id, cerrar=False)
    else:
        _paso(inc_id, "El equipo sigue aislado hasta que seguridad lo revise y pulse «Liberar equipo»", True)
    estado = "contenido" if errores == 0 else "revisar"
    _set(inc_id, estado=estado)
    agentes.invalidar(system["id"])
    if _notify:
        try:
            _notify("incidente", f"Incidente #{inc_id} en {system['hostname']}: respuesta terminada ({estado}).")
        except Exception:
            pass


def liberar(inc_id, cerrar=True, notas=""):
    inc = obtener(inc_id)
    system = _system(inc)
    if not system:
        return False, "El equipo ya no existe"
    ag = agentes.Agente(agentes.ip_de(system), timeout=30)
    r = ag._req("POST", "/webhook/reincorporacion", {}, timeout=60)
    ag._req("POST", "/webhook/quitar-aviso", {}, timeout=30)
    ok = r.get("status") == "success"
    _paso(inc_id, "Equipo reincorporado a la red" if ok else "No se pudo reincorporar el equipo", ok,
          "" if ok else r.get("message"))
    if ok:
        _set(inc_id, aislado=0)
        if cerrar:
            _set(inc_id, estado="cerrado", cerrado=datetime.now().isoformat(), notas=notas or None)
            _paso(inc_id, "Incidente cerrado", True, notas)
    return ok, r.get("message", "")


# ---------------------------------------------------------------------------
# Sala de analisis (sandbox)
# ---------------------------------------------------------------------------
def sala_dir(inc_id):
    return os.path.join(SANDBOX_ROOT, str(int(inc_id)))


def sala_preparada(inc_id):
    return os.path.isdir(os.path.join(sala_dir(inc_id), "muestras"))


def _restic_cuarentena_env():
    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = _env("RESTIC_REPOSITORY_CUARENTENA")
    env["RESTIC_PASSWORD"] = _env("RESTIC_PASSWORD_CUARENTENA") or _env("RESTIC_PASSWORD")
    env["AWS_ACCESS_KEY_ID"] = _env("AWS_ACCESS_KEY_ID")
    env["AWS_SECRET_ACCESS_KEY"] = _env("AWS_SECRET_ACCESS_KEY")
    return env


def preparar_sala(inc_id):
    """Recupera la copia forense en el servidor, sin permisos de ejecucion, y genera el indice."""
    inc = obtener(inc_id)
    if not inc or not inc.get("snapshot_forense"):
        return False, "Este incidente no tiene copia forense"
    base = sala_dir(inc_id)
    destino = os.path.join(base, "muestras")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(destino, mode=0o750)
    restic = shutil.which("restic") or "/usr/local/bin/restic"
    r = subprocess.run([restic, "restore", inc["snapshot_forense"], "--target", destino],
                       env=_restic_cuarentena_env(), capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout)[-500:]
    # Nada ejecutable y solo lectura
    for root, dirs, files in os.walk(destino):
        for d in dirs:
            os.chmod(os.path.join(root, d), 0o755)
        for f in files:
            p = os.path.join(root, f)
            if not os.path.islink(p):
                os.chmod(p, 0o444)
    _poblar_volumen(inc_id)
    indice = escanear(inc_id)
    _paso(inc_id, "Sala de análisis preparada", True, f"{len(indice)} archivos")
    return True, f"{len(indice)} archivos listos para analizar"


def _docker_ok():
    try:
        return subprocess.run(["docker", "image", "inspect", SANDBOX_IMAGE], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


EN_CONTENEDOR = os.environ.get("OCTOPUS_EN_CONTENEDOR") == "1"


def _volumen_sala(inc_id):
    return f"octopus-sala-{int(inc_id)}"


def _poblar_volumen(inc_id):
    """Servidor en contenedor: las muestras se copian a un volumen propio del incidente, porque el Docker del
    anfitrion no ve las carpetas de este contenedor. Cada analisis lo monta despues en solo lectura."""
    if not EN_CONTENEDOR or not _docker_ok():
        return
    vol = _volumen_sala(inc_id)
    tmp = f"octopus-carga-{int(inc_id)}-{secrets.token_hex(3)}"
    subprocess.run(["docker", "volume", "rm", "-f", vol], capture_output=True, timeout=60)
    subprocess.run(["docker", "volume", "create", vol], capture_output=True, timeout=60)
    subprocess.run(["docker", "create", "--name", tmp, "--network", "none", "-v", f"{vol}:/muestras",
                    SANDBOX_IMAGE, "true"], capture_output=True, timeout=60)
    subprocess.run(["docker", "cp", os.path.join(sala_dir(inc_id), "muestras") + "/.", f"{tmp}:/muestras"],
                   capture_output=True, timeout=3600)
    subprocess.run(["docker", "rm", "-f", tmp], capture_output=True, timeout=60)


def _docker_cmd(inc_id, comando, timeout=30):
    """Ejecuta un comando dentro del contenedor aislado: sin red, solo lectura, sin privilegios."""
    name = f"octopus-sala-{int(inc_id)}-{secrets.token_hex(3)}"
    cmd = ["docker", "run", "--rm", "--name", name,
           "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,noexec,size=64m",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--pids-limit", "64", "--memory", "256m", "--cpus", "0.5", "--user", "65534:65534",
           "-v", (f"{_volumen_sala(inc_id)}:/muestras:ro" if EN_CONTENEDOR
                  else f"{os.path.join(sala_dir(inc_id), 'muestras')}:/muestras:ro"),
           "-w", "/muestras", SANDBOX_IMAGE, "sh", "-c", comando]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out[:100000]
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        return 124, f"Tiempo agotado ({timeout} s). El contenedor se ha eliminado."


def escanear(inc_id):
    """Indice de archivos: hash, tamano, tipo real, entropia y si parece sospechoso."""
    base = os.path.join(sala_dir(inc_id), "muestras")
    indice = []
    if _docker_ok():
        code, out = _docker_cmd(inc_id, "python3 /opt/octopus/escanear.py /muestras", timeout=300)
        try:
            indice = json.loads(out[out.index("["):])
        except ValueError:
            indice = []
    if not indice:  # sin Docker: analisis estatico en Python puro (solo lectura de bytes)
        import math
        for root, _, files in os.walk(base):
            for f in files:
                p = os.path.join(root, f)
                try:
                    data = open(p, "rb").read()
                except OSError:
                    continue
                counts = [0] * 256
                for b in data[:65536]:
                    counts[b] += 1
                n = min(len(data), 65536) or 1
                ent = -sum(c / n * math.log2(c / n) for c in counts if c)
                indice.append({"ruta": os.path.relpath(p, base), "tamano": len(data),
                               "sha256": hashlib.sha256(data).hexdigest(), "tipo": "",
                               "entropia": round(ent, 2), "motivos": []})
    from_agent = set()
    try:
        inc = obtener(inc_id)
        from_agent = {e.lstrip("/").replace("\\", "/") for e in inc.get("evidencias", [])}
    except Exception:
        pass
    for it in indice:
        if it["ruta"].replace("\\", "/") in from_agent:
            it.setdefault("motivos", []).append("señalado por el detector")
        it["sospechoso"] = bool(it.get("motivos"))
    indice.sort(key=lambda x: (not x["sospechoso"], x["ruta"]))
    with open(os.path.join(sala_dir(inc_id), "indice.json"), "w", encoding="utf-8") as fh:
        json.dump(indice, fh, indent=1)
    return indice


def indice(inc_id):
    try:
        with open(os.path.join(sala_dir(inc_id), "indice.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def _ruta_segura(inc_id, ruta):
    base = os.path.realpath(os.path.join(sala_dir(inc_id), "muestras"))
    p = os.path.realpath(os.path.join(base, ruta))
    if not (p == base or p.startswith(base + os.sep)):
        raise ValueError("Ruta fuera de la sala")
    return os.path.relpath(p, base)


def ver_archivo(inc_id, ruta):
    rel = _ruta_segura(inc_id, ruta)
    q = shlex.quote(rel)
    if _docker_ok():
        _, tipo = _docker_cmd(inc_id, f"file -b {q}")
        _, hexd = _docker_cmd(inc_id, f"xxd -l 768 {q}")
        _, txt = _docker_cmd(inc_id, f"strings -n 5 {q} | head -n 300")
        _, yara = _docker_cmd(inc_id, f"yara -s /opt/octopus/reglas.yar {q} 2>&1 | head -n 50")
    else:
        data = open(os.path.join(sala_dir(inc_id), "muestras", rel), "rb").read()
        tipo = "(sin Docker: tipo no disponible)"
        hexd = "\n".join(f"{i:08x}: {data[i:i+16].hex(' ')}" for i in range(0, min(len(data), 768), 16))
        txt, yara = "", ""
    return {"ruta": rel, "tipo": tipo.strip(), "hex": hexd, "strings": txt, "yara": yara.strip()}


def ejecutar(inc_id, comando):
    if not sala_preparada(inc_id):
        return 1, "Primero prepara la sala de análisis."
    if not _docker_ok():
        return 1, "La imagen del sandbox no está instalada en el servidor (octopus-sandbox)."
    _paso(inc_id, "Comando ejecutado en la sala", True, comando[:200])
    return _docker_cmd(inc_id, comando, timeout=60)


def paquete(inc_id):
    """Paquete forense descargable: .7z cifrado (AES-256, nombres de archivo tambien cifrados)."""
    inc = obtener(inc_id)
    base = sala_dir(inc_id)
    if not sala_preparada(inc_id):
        return None, "Primero prepara la sala de análisis."
    seven = shutil.which("7z") or shutil.which("7za")
    if not seven:
        return None, "Falta 7-Zip en el servidor (paquete p7zip-full)."
    clave = inc.get("clave_paquete") or secrets.token_urlsafe(12)
    _set(inc_id, clave_paquete=clave)
    informe = {k: inc[k] for k in ("id", "hostname", "detectado", "origen", "severidad", "motivo",
                                   "snapshot_forense", "snapshot_restaurado", "estado")}
    informe["pasos"] = inc["pasos"]
    informe["archivos"] = indice(inc_id)
    with open(os.path.join(base, "INFORME_INCIDENTE.json"), "w", encoding="utf-8") as fh:
        json.dump(informe, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(base, "LEEME.txt"), "w", encoding="utf-8") as fh:
        fh.write("PAQUETE FORENSE OCTOPUS - CONTIENE POSIBLE MALWARE\n"
                 "No lo abras en un equipo de trabajo. Analizalo en una maquina virtual aislada.\n"
                 f"Incidente #{inc_id} - equipo {inc['hostname']} - detectado {inc['detectado']}\n")
    out = os.path.join(base, f"incidente_{inc_id}_forense.7z")
    if os.path.exists(out):
        os.remove(out)
    r = subprocess.run([seven, "a", "-t7z", "-mhe=on", f"-p{clave}", out,
                        os.path.join(base, "muestras"), os.path.join(base, "INFORME_INCIDENTE.json"),
                        os.path.join(base, "LEEME.txt")], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        return None, (r.stderr or r.stdout)[-400:]
    _paso(inc_id, "Paquete forense generado para descarga", True, os.path.basename(out))
    return out, clave


def borrar_sala(inc_id):
    shutil.rmtree(sala_dir(inc_id), ignore_errors=True)
    if EN_CONTENEDOR:
        subprocess.run(["docker", "volume", "rm", "-f", _volumen_sala(inc_id)], capture_output=True, timeout=60)
    _paso(inc_id, "Sala de análisis eliminada del servidor", True)


# ---------------------------------------------------------------------------
# Borrar la amenaza
# ---------------------------------------------------------------------------
def ruta_en_equipo(inc_id, rel):
    """Convierte la ruta de la sala ('home/ana/x.exe' o 'C/Users/ana/x.exe') en la ruta real del equipo."""
    rel = rel.replace("\\", "/").lstrip("/")
    partes = rel.split("/")
    inc = obtener(inc_id)
    system = _system(inc) if inc else None
    es_windows = system is not None and (system["os_family"] or "").lower().startswith("win")
    if es_windows and partes and len(partes[0]) == 1:
        return partes[0].upper() + ":\\" + "\\".join(partes[1:])
    return "/" + rel


def eliminar_amenaza(inc_id, rutas=None):
    """Borra del equipo los archivos maliciosos. Sin rutas: los que senalo el detector."""
    inc = obtener(inc_id)
    system = _system(inc) if inc else None
    if not system:
        return False, "El equipo ya no existe"
    rutas = rutas or inc.get("evidencias") or []
    if not rutas:
        return False, "No hay archivos señalados como amenaza"
    r = agentes.Agente(agentes.ip_de(system), timeout=60)._req("POST", "/webhook/eliminar", {"rutas": rutas}, timeout=120)
    borrados = r.get("borrados", [])
    ok = r.get("status") == "success"
    detalle = f"{len(borrados)} borrados, {len(r.get('no_existian', []))} ya no estaban"
    if r.get("rechazados"):
        detalle += f", {len(r['rechazados'])} rechazados"
    _paso(inc_id, "Amenaza eliminada del equipo" if ok else "No se pudo eliminar toda la amenaza", ok,
          detalle if (ok or r.get("borrados") is not None) else r.get("message"))
    return ok, detalle if r.get("borrados") is not None else r.get("message", "")


def _volumen_boveda():
    if os.environ.get("OCTOPUS_BOVEDA_DIR"):
        return os.environ["OCTOPUS_BOVEDA_DIR"]
    try:
        nombres = subprocess.run(["docker", "volume", "ls", "-q"], capture_output=True, text=True, timeout=20).stdout.split()
        vol = next(n for n in nombres if n.endswith("boveda_data"))
        return subprocess.run(["docker", "volume", "inspect", "-f", "{{.Mountpoint}}", vol],
                              capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def destruir_forense(inc_id):
    """Borra la sala y la copia forense de la cuarentena (cuando el caso esta cerrado).
    El almacen es de solo-anadir para los equipos; el borrado se hace desde el propio servidor."""
    inc = obtener(inc_id)
    if not inc:
        return False, "No existe el incidente"
    shutil.rmtree(sala_dir(inc_id), ignore_errors=True)
    if EN_CONTENEDOR:
        subprocess.run(["docker", "volume", "rm", "-f", _volumen_sala(inc_id)], capture_output=True, timeout=60)
    snap = inc.get("snapshot_forense")
    if not snap:
        _paso(inc_id, "Sala de análisis eliminada (no había copia forense)", True)
        return True, "Sala eliminada"
    mount = _volumen_boveda()
    repo = os.path.join(mount, "octopus-cuarentena") if mount else ""
    if not repo or not os.path.isdir(repo):
        return False, "No se encuentra el almacén de cuarentena en el servidor"
    env = os.environ.copy()
    env.pop("RESTIC_REPOSITORY", None)
    env["RESTIC_PASSWORD"] = _env("RESTIC_PASSWORD_CUARENTENA") or _env("RESTIC_PASSWORD")
    restic = shutil.which("restic") or "/usr/local/bin/restic"
    r = subprocess.run([restic, "-r", repo, "forget", snap, "--prune"], env=env, capture_output=True, text=True, timeout=1800)
    ok = r.returncode == 0
    if ok:
        _set(inc_id, snapshot_forense=None, clave_paquete=None)
    _paso(inc_id, "Copia forense destruida definitivamente" if ok else "No se pudo destruir la copia forense", ok,
          "" if ok else (r.stderr or r.stdout)[-300:])
    return ok, "Copia forense destruida" if ok else (r.stderr or r.stdout)[-300:]


# ---------------------------------------------------------------------------
# Uso desde la consola del servidor (lo usan las pruebas):
#   python3 incidentes.py ultimo|ver <id>|preparar <id>|liberar <id>|eliminar <id>|limpiar-laboratorio
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.isfile(env_file):
        for raw in open(env_file, encoding="utf-8"):
            if "=" in raw and not raw.lstrip().startswith("#"):
                k, v = raw.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
    db = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "data", "admin_panel.db"))
    init(db if os.path.isabs(db) else os.path.join(BASE_DIR, db))
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ultimo"
    if cmd == "ultimo":
        lst = listar(1)
        print(json.dumps(lst[0] if lst else {}, default=str))
    elif cmd == "ver":
        print(json.dumps(obtener(int(sys.argv[2])) or {}, default=str))
    elif cmd == "preparar":
        ok, msg = preparar_sala(int(sys.argv[2]))
        print(json.dumps({"ok": ok, "msg": msg, "sospechosos": [a["ruta"] for a in indice(int(sys.argv[2])) if a.get("sospechoso")]}))
    elif cmd == "liberar":
        ok, msg = liberar(int(sys.argv[2]), cerrar=True, notas="cerrado por las pruebas automaticas")
        print(json.dumps({"ok": ok, "msg": msg}))
    elif cmd == "limpiar-laboratorio":
        # Solo para las pruebas: libera y cierra los incidentes que hayan quedado abiertos de ejecuciones anteriores
        conn = _db()
        ids = [r[0] for r in conn.execute("SELECT id FROM incidents WHERE estado != 'cerrado'").fetchall()]
        conn.close()
        res = []
        for i in ids:
            ok, msg = liberar(i, cerrar=True, notas="cerrado al iniciar una nueva bateria de pruebas")
            if not ok:
                _set(i, estado="cerrado", cerrado=datetime.now().isoformat(), notas="cerrado por las pruebas (equipo no accesible)")
            res.append({"id": i, "liberado": ok, "msg": msg})
        print(json.dumps({"ok": True, "cerrados": res}))
    elif cmd == "eliminar":
        ok, msg = eliminar_amenaza(int(sys.argv[2]))
        print(json.dumps({"ok": ok, "msg": msg}))
