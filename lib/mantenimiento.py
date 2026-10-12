#!/usr/bin/env python3
"""
OCTOPUS Zero-Touch - Mantenimiento diario del servidor (lo lanza el temporizador octopus-mantenimiento).

  retencion   borra las copias antiguas segun la politica elegida en el panel (por equipo)
  verificar   comprueba la integridad del almacen (y lee una muestra de datos los domingos)
  autocopia   copia de seguridad del PROPIO servidor: base de datos, .env, claves SSH/WireGuard, certificados
              (en el almacen y, si se configura, en un almacen externo OFFSITE_RESTIC_REPOSITORY)
  vigilar     avisa si un equipo lleva demasiado sin copia o si el disco se esta llenando
  probar      prueba de recuperacion: recupera DE VERDAD unos archivos de la ultima copia de cada equipo
              (cada PRUEBA_RECUPERACION_DIAS dias, 7 por defecto).  probar <equipo>  la hace ya
  todo        todo lo anterior (por defecto)
  kit         imprime el kit de recuperacion (claves necesarias para recuperar las copias)

El almacen (rest-server) funciona en modo "solo anadir": los equipos no pueden borrar copias. Por eso
la limpieza se hace aqui, en el servidor, accediendo al repositorio directamente en disco.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
ESTADO_FILE = BASE_DIR / "data" / "mantenimiento.json"
PRUEBAS_FILE = BASE_DIR / "data" / "pruebas_recuperacion.json"

POLITICAS = {
    "daily_7": dict(daily=7, weekly=4, monthly=6),
    "daily_30": dict(daily=30, weekly=8, monthly=12),
    "daily_90": dict(daily=90, weekly=26, monthly=24),
    "weekly_4": dict(daily=7, weekly=4, monthly=3),
    "weekly_12": dict(daily=7, weekly=12, monthly=6),
    "monthly_3": dict(daily=7, weekly=4, monthly=3),
    "monthly_12": dict(daily=7, weekly=8, monthly=12),
}


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def leer_env() -> dict:
    env = {}
    f = BASE_DIR / ".env"
    if f.is_file():
        for raw in f.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def db_path(env: dict) -> Path:
    p = env.get("DB_PATH", "./data/admin_panel.db")
    return Path(p) if os.path.isabs(p) else (BASE_DIR / p).resolve()


def run(cmd, env=None, timeout=6 * 3600):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "tiempo agotado")
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def restic_bin() -> str:
    return shutil.which("restic") or "/usr/local/bin/restic"


# ---------------------------------------------------------------- acceso al almacen
def volumen_boveda() -> str:
    """Carpeta en disco del volumen del almacen (rest-server)."""
    r = run(["docker", "volume", "ls", "-q"], timeout=30)
    for vol in (r.stdout or "").split():
        if vol.endswith("boveda_data"):
            m = run(["docker", "volume", "inspect", "-f", "{{.Mountpoint}}", vol], timeout=30)
            if m.returncode == 0 and m.stdout.strip():
                return m.stdout.strip()
    return ""


def repo_local(env: dict, cuarentena: bool = False) -> tuple[str, str]:
    """(ruta del repositorio en disco, contrasena). Sin pasar por rest-server (que no deja borrar)."""
    url = env.get("RESTIC_REPOSITORY_CUARENTENA" if cuarentena else "RESTIC_REPOSITORY", "")
    pwd = env.get("RESTIC_PASSWORD_CUARENTENA" if cuarentena else "RESTIC_PASSWORD", "")
    nombre = url.rstrip("/").rsplit("/", 1)[-1] if url else ("octopus-cuarentena" if cuarentena else "octopus-backups")
    base = os.environ.get("OCTOPUS_BOVEDA_DIR") or volumen_boveda()
    if not base:
        return "", pwd
    return os.path.join(base, nombre), pwd


def restic_env(repo: str, pwd: str) -> dict:
    e = dict(os.environ)
    e["RESTIC_REPOSITORY"] = repo
    e["RESTIC_PASSWORD"] = pwd
    e.setdefault("RESTIC_CACHE_DIR", "/var/cache/octopus-restic")
    return e


# ---------------------------------------------------------------- tareas
def politica(env: dict) -> dict:
    nombre = "daily_30"
    try:
        from config_manager import ConfigManager
        nombre = str(ConfigManager(str(db_path(env))).get_config("backup_retention") or nombre).strip('"')
    except Exception:
        pass
    p = dict(POLITICAS.get(nombre, POLITICAS["daily_30"]))
    for clave in ("daily", "weekly", "monthly"):
        v = env.get(f"RETENCION_{clave.upper()}")
        if v and v.isdigit():
            p[clave] = int(v)
    p["nombre"] = nombre
    return p


def retencion(env: dict) -> dict:
    repo, pwd = repo_local(env)
    if not repo or not os.path.isdir(repo):
        return {"ok": False, "detalle": "No se encuentra el almacen en disco"}
    p = politica(env)
    cmd = [restic_bin(), "forget", "--prune", "--group-by", "host,paths", "--keep-last", "3",
           "--keep-daily", str(p["daily"]), "--keep-weekly", str(p["weekly"]), "--keep-monthly", str(p["monthly"]),
           "--json"]
    r = run(cmd, env=restic_env(repo, pwd))
    if r.returncode != 0:
        if "locked" in (r.stderr or "").lower():
            run([restic_bin(), "unlock"], env=restic_env(repo, pwd), timeout=300)
            r = run(cmd, env=restic_env(repo, pwd))
    borradas = 0
    try:
        for grupo in json.loads((r.stdout or "").strip().splitlines()[0] if r.stdout.strip() else "[]"):
            borradas += len(grupo.get("remove") or [])
    except (ValueError, IndexError, AttributeError):
        pass
    ok = r.returncode == 0
    detalle = (f"Politica {p['nombre']}: {p['daily']} diarias, {p['weekly']} semanales, {p['monthly']} mensuales. "
               f"Copias antiguas borradas: {borradas}") if ok else (r.stderr or r.stdout)[-400:]
    return {"ok": ok, "detalle": detalle}


def verificar(env: dict) -> dict:
    res = []
    for cuarentena in (False, True):
        repo, pwd = repo_local(env, cuarentena)
        if not repo or not os.path.isdir(repo):
            continue
        cmd = [restic_bin(), "check"]
        if not cuarentena and datetime.now().weekday() == 6:  # domingos: lee tambien una muestra de los datos
            cmd.append("--read-data-subset=5%")
        r = run(cmd, env=restic_env(repo, pwd))
        res.append({"repo": os.path.basename(repo), "ok": r.returncode == 0,
                    "detalle": "" if r.returncode == 0 else (r.stderr or r.stdout)[-400:]})
    if not res:
        return {"ok": False, "detalle": "No se encuentra el almacen en disco"}
    ok = all(x["ok"] for x in res)
    return {"ok": ok, "detalle": "; ".join(f"{x['repo']}: {'correcto' if x['ok'] else 'ERROR ' + x['detalle']}" for x in res)}


def _copiar_db(origen: Path, destino: Path) -> None:
    src = sqlite3.connect(str(origen))
    dst = sqlite3.connect(str(destino))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()


def autocopia(env: dict) -> dict:
    """Empaqueta lo necesario para reconstruir el servidor y lo guarda con restic."""
    tmp = Path(tempfile.mkdtemp(prefix="octopus_autocopia_"))
    os.chmod(tmp, 0o700)
    try:
        dest = tmp / "servidor"
        dest.mkdir()
        db = db_path(env)
        if db.is_file():
            _copiar_db(db, dest / db.name)
        for rel in (".env", "ansible/config.json", "ansible/wg", "ansible/equipos.ini", "data/tls"):
            src = BASE_DIR / rel
            if src.is_dir():
                shutil.copytree(src, dest / rel, dirs_exist_ok=True)
            elif src.is_file():
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / rel)
        ssh = Path("/root/.ssh")
        for f in ssh.glob("octopus_ed25519*"):
            (dest / "ssh").mkdir(exist_ok=True)
            shutil.copy2(f, dest / "ssh" / f.name)
        r = run(["docker", "volume", "ls", "-q"], timeout=30)
        for vol in (r.stdout or "").split():
            if vol.endswith("wg_data"):
                m = run(["docker", "volume", "inspect", "-f", "{{.Mountpoint}}", vol], timeout=30).stdout.strip()
                if m and os.path.isdir(m):
                    shutil.copytree(m, dest / "wireguard", dirs_exist_ok=True)
        (dest / "LEEME.txt").write_text(
            "Copia del servidor OCTOPUS. Para reconstruirlo: instala OCTOPUS en un servidor nuevo, para los servicios,\n"
            "copia aqui .env, ansible/, data/ y la base de datos en su sitio, las claves ssh/ en /root/.ssh y wireguard/\n"
            "en el volumen wg_data, y vuelve a ejecutar el instalador. Detalle en PRODUCCION.md.\n", encoding="utf-8")
        destinos = []
        repo, pwd = repo_local(env)
        if repo and os.path.isdir(repo):
            destinos.append(("almacen local", repo, pwd))
        if env.get("OFFSITE_RESTIC_REPOSITORY") and env.get("OFFSITE_RESTIC_PASSWORD"):
            destinos.append(("almacen externo", env["OFFSITE_RESTIC_REPOSITORY"], env["OFFSITE_RESTIC_PASSWORD"]))
        if not destinos:
            return {"ok": False, "detalle": "No hay donde guardar la copia del servidor"}
        partes, ok, local_ok = [], True, False
        for nombre, rp, pw in destinos:
            e = restic_env(rp, pw)
            for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "B2_ACCOUNT_ID", "B2_ACCOUNT_KEY"):
                if env.get("OFFSITE_" + k) and nombre == "almacen externo":
                    e[k] = env["OFFSITE_" + k]
            if run([restic_bin(), "cat", "config"], env=e, timeout=300).returncode != 0:
                run([restic_bin(), "init"], env=e, timeout=600)
            copiar_todo = (nombre == "almacen externo" and local_ok and
                           env.get("OFFSITE_COPIAR_EQUIPOS", "si").lower() not in ("no", "0", "false"))
            if copiar_todo:
                # al externo va TODO el almacen (copias de los equipos y la del servidor recien hecha)
                c = copiar_equipos_externo(env, e)
                ok = ok and c["ok"]
                partes.append(f"almacen externo: {c['detalle']}")
                continue
            r = run([restic_bin(), "backup", str(dest), "--host", "octopus-servidor", "--tag", "servidor"], env=e)
            ok = ok and r.returncode == 0
            if nombre == "almacen local":
                local_ok = r.returncode == 0
            partes.append(f"{nombre}: {'correcta' if r.returncode == 0 else 'ERROR ' + (r.stderr or '')[-200:]}")
            if r.returncode == 0 and nombre == "almacen externo":
                run([restic_bin(), "forget", "--prune", "--host", "octopus-servidor", "--keep-daily", "14",
                     "--keep-weekly", "8", "--keep-monthly", "12"], env=e)
        if not env.get("OFFSITE_RESTIC_REPOSITORY"):
            partes.append("sin almacen externo (recomendado: configuralo con  sudo bash octopus.sh ajustes  - ver PRODUCCION.md)")
        return {"ok": ok, "detalle": "; ".join(partes)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def copiar_equipos_externo(env: dict, e_externo: dict) -> dict:
    """Copia al almacen externo las copias de los equipos que aun no esten alli (restic copy solo envia lo
    nuevo) y aplica alli la misma politica de limpieza. Asi, si se pierde el disco del servidor, el historial
    de copias de los equipos sigue en el almacen externo."""
    repo, pwd = repo_local(env)
    if not repo or not os.path.isdir(repo):
        return {"ok": False, "detalle": "no se encuentra el almacen local"}
    e = dict(e_externo)
    e["RESTIC_FROM_REPOSITORY"] = repo
    e["RESTIC_FROM_PASSWORD"] = pwd
    r = run([restic_bin(), "copy"], env=e)
    if r.returncode != 0 and "locked" in (r.stderr or "").lower():
        run([restic_bin(), "unlock"], env=e, timeout=300)
        r = run([restic_bin(), "copy"], env=e)
    if r.returncode != 0:
        return {"ok": False, "detalle": "ERROR " + (r.stderr or r.stdout or "")[-200:]}
    nuevas = sum(1 for l in (r.stdout or "").splitlines() if l.strip().startswith("snapshot") and "saved" in l)
    p = politica(env)
    run([restic_bin(), "forget", "--prune", "--group-by", "host,paths", "--keep-last", "3",
         "--keep-daily", str(p["daily"]), "--keep-weekly", str(p["weekly"]), "--keep-monthly", str(p["monthly"])], env=e)
    return {"ok": True, "detalle": f"todas las copias al dia ({nuevas} nuevas)"}


def vigilar(env: dict) -> dict:
    avisos = []
    base = os.environ.get("OCTOPUS_BOVEDA_DIR") or volumen_boveda()
    uso = None
    if base and os.path.isdir(base):
        du = shutil.disk_usage(base)
        uso = round(du.used * 100 / du.total, 1)
        limite = float(env.get("ALERTA_DISCO_PORCENTAJE", "85"))
        if uso >= limite:
            avisos.append(f"El disco del almacen esta al {uso}% (quedan {du.free // 2**30} GB). Que hacer: amplia el "
                          f"disco del servidor o guarda menos copias antiguas (Ajustes > Programacion de copias)")
    horas = float(env.get("ALERTA_SIN_COPIA_HORAS", "26"))
    repo, pwd = repo_local(env)
    ultimas = {}
    if repo and os.path.isdir(repo):
        r = run([restic_bin(), "snapshots", "--json", "--no-lock"], env=restic_env(repo, pwd), timeout=600)
        try:
            for s in json.loads(r.stdout or "[]"):
                t = datetime.fromisoformat(s["time"][:19]).replace(tzinfo=timezone.utc)
                if s.get("hostname") not in ultimas or t > ultimas[s["hostname"]]:
                    ultimas[s["hostname"]] = t
        except (ValueError, KeyError, TypeError):
            pass
    sin_copia = []
    try:
        conn = sqlite3.connect(str(db_path(env)))
        equipos = list(conn.execute("SELECT hostname, notes FROM systems"))
        conn.close()
    except sqlite3.Error:
        equipos = []
    ahora = datetime.now(timezone.utc)
    for h, notas in equipos:
        # limite propio del equipo (se elige en su ficha del panel) o el general
        limite = horas
        try:
            limite = float((json.loads(notas or "{}") or {}).get("horas_sin_copia") or horas)
        except (ValueError, TypeError, AttributeError):
            pass
        t = ultimas.get(h)
        if t is None or (ahora - t).total_seconds() > limite * 3600:
            sin_copia.append(f"{h} ({'nunca' if t is None else 'hace ' + str(int((ahora - t).total_seconds() // 3600)) + ' h'})")
    if sin_copia:
        avisos.append(f"Equipos sin copia reciente: {', '.join(sin_copia)}. Que hacer: comprueba que estan "
                      f"encendidos y conectados; en el panel, entra en el equipo y pulsa 'Hacer copia ahora'")
    return {"ok": not avisos, "detalle": "; ".join(avisos) or "Todo en orden", "uso_disco": uso,
            "sin_copia": sin_copia}


# ---------------------------------------------------------------- prueba de recuperacion
def leer_pruebas() -> dict:
    """{equipo_en_minusculas: {ok, fecha, copia, copia_fecha, archivos, total, detalle}}"""
    try:
        return json.loads(PRUEBAS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_prueba(host: str, res: dict) -> None:
    datos = leer_pruebas()
    datos[host.lower()] = res
    PRUEBAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PRUEBAS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PRUEBAS_FILE)


def probar_equipo(env: dict, host: str, muestra: int = 5) -> dict:
    """Recupera de verdad unos archivos de la ultima copia de `host` en una carpeta temporal del servidor y
    comprueba que salen completos (restic --verify vuelve a leer y comparar cada archivo recuperado)."""
    inicio = time.time()
    res = {"ok": False, "fecha": datetime.now().astimezone().isoformat(timespec="seconds"), "copia": "",
           "copia_fecha": "", "archivos": 0, "total": 0, "detalle": ""}

    def fin(ok: bool, detalle: str, guardar: bool = True) -> dict:
        res.update(ok=ok, detalle=detalle, segundos=round(time.time() - inicio))
        if guardar:  # "aun no hay copias" no es una prueba fallida: no se guarda
            _guardar_prueba(host, res)
        return res

    repo, pwd = repo_local(env)
    if not repo or not os.path.isdir(repo):
        return fin(False, "No se encuentra el almacen en disco")
    e = restic_env(repo, pwd)
    r = run([restic_bin(), "snapshots", "--json", "--no-lock", "--host", host], env=e, timeout=600)
    try:
        copias = [s for s in json.loads(r.stdout or "[]") or [] if "forense" not in (s.get("tags") or [])]
    except ValueError:
        copias = []
    if not copias:
        return fin(False, "Este equipo todavia no tiene copias que probar", guardar=False)
    ultima = max(copias, key=lambda s: s.get("time") or "")
    res["copia"] = ultima.get("short_id") or ultima.get("id", "")[:8]
    res["copia_fecha"] = ultima.get("time") or ""
    try:
        dia = datetime.fromisoformat(res["copia_fecha"][:19]).replace(tzinfo=timezone.utc).astimezone().strftime("%d/%m/%Y")
    except ValueError:
        dia = res["copia_fecha"][:10]
    r = run([restic_bin(), "ls", "--json", "--no-lock", ultima["id"]], env=e, timeout=1800)
    candidatos = []
    for linea in (r.stdout or "").splitlines():
        try:
            n = json.loads(linea)
        except ValueError:
            continue
        ruta = n.get("path") or ""
        # archivos con datos y de tamano razonable; sin caracteres que restic trataria como comodines
        if n.get("type") == "file" and 0 < (n.get("size") or 0) <= 50 * 2**20 and not any(c in ruta for c in "*?[]\\"):
            candidatos.append((ruta, n["size"]))
    if not candidatos:
        return fin(False, "La ultima copia no tiene archivos que se puedan probar")
    elegidos = random.sample(candidatos, min(muestra, len(candidatos)))
    res["total"] = len(elegidos)
    tmp = tempfile.mkdtemp(prefix="octopus_prueba_")
    try:
        cmd = [restic_bin(), "restore", ultima["id"], "--no-lock", "--target", tmp, "--verify"]
        for ruta, _ in elegidos:
            cmd += ["--include", ruta]
        r = run(cmd, env=e, timeout=3600)
        bien = 0
        mal = []
        for ruta, tam in elegidos:
            f = Path(tmp) / ruta.lstrip("/")
            if f.is_file() and f.stat().st_size == tam:
                bien += 1
            else:
                mal.append(ruta)
        res["archivos"] = bien
        if r.returncode != 0 or mal:
            motivo = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
            return fin(False, f"Se recuperaron {bien} de {len(elegidos)} archivos. "
                              f"Fallaron: {', '.join(mal[:3]) or motivo[0][:200]}")
        return fin(True, f"Recuperados y comprobados {bien} archivos de la copia del {dia}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prueba_recuperacion(env: dict, forzar: bool = False) -> dict:
    """Prueba cada equipo si su ultima prueba tiene mas de PRUEBA_RECUPERACION_DIAS dias (7 por defecto)."""
    dias = float(env.get("PRUEBA_RECUPERACION_DIAS", "7"))
    try:
        conn = sqlite3.connect(str(db_path(env)))
        equipos = [r[0] for r in conn.execute("SELECT hostname FROM systems ORDER BY hostname")]
        conn.close()
    except sqlite3.Error:
        equipos = []
    previas = leer_pruebas()
    ahora = datetime.now().astimezone()
    partes, fallos, hechas = [], [], 0
    for h in equipos:
        p = previas.get(h.lower())
        if p and not forzar:
            try:
                if (ahora - datetime.fromisoformat(p["fecha"])).total_seconds() < dias * 86400 - 3600:
                    continue
            except (KeyError, ValueError, TypeError):
                pass
        r = probar_equipo(env, h)
        if r["detalle"].startswith("Este equipo todavia no tiene copias"):
            continue
        hechas += 1
        partes.append(f"{h}: {'correcta' if r['ok'] else 'FALLO - ' + r['detalle']}")
        if not r["ok"]:
            fallos.append(h)
    if not hechas:
        return {"ok": True, "detalle": f"No tocaba ninguna prueba (se hacen cada {int(dias)} dias)"}
    return {"ok": not fallos, "detalle": "; ".join(partes)}


def kit(env: dict) -> str:
    """Texto con lo imprescindible para recuperar las copias si se pierde el servidor."""
    return f"""OCTOPUS Zero-Touch - KIT DE RECUPERACION
Generado: {datetime.now():%Y-%m-%d %H:%M}

GUARDA ESTE DOCUMENTO FUERA DEL SERVIDOR (gestor de contrasenas, caja fuerte, papel).
Sin la clave de copias, NADIE puede recuperar las copias de seguridad: ni tu, ni un atacante, ni el soporte.

Clave de las copias (restic) ..... {env.get('RESTIC_PASSWORD', '')}
Clave de la cuarentena ........... {env.get('RESTIC_PASSWORD_CUARENTENA', '')}
Usuario del almacen .............. {env.get('REST_USER', '')}
Contrasena del almacen ........... {env.get('REST_PASSWORD', '')}
Almacen externo .................. {env.get('OFFSITE_RESTIC_REPOSITORY') or '(no configurado)'}
Clave del almacen externo ........ {env.get('OFFSITE_RESTIC_PASSWORD') or '(no configurado)'}

Recuperar archivos sin el servidor OCTOPUS (desde cualquier equipo con restic instalado):
  1. Copia la carpeta del almacen (volumen octopus_boveda, o install_boveda_data si vienes de la v1;
     subcarpeta octopus-backups) o usa el almacen externo.
  2. restic -r <ruta-al-almacen> snapshots              (pide la clave de las copias)
  3. restic -r <ruta-al-almacen> restore latest --host <equipo> --target <carpeta>

Reconstruir el servidor:  sudo bash octopus.sh recuperar-servidor <almacen>  (PRODUCCION.md, "Si se pierde el servidor").
"""


def guardar_estado(resultados: dict) -> None:
    ESTADO_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"fecha": datetime.now().astimezone().isoformat(timespec="seconds"), "resultados": resultados,
            "ok": all(r.get("ok") for r in resultados.values())}
    tmp = ESTADO_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ESTADO_FILE)


def leer_estado() -> dict:
    try:
        return json.loads(ESTADO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def avisar(env: dict, texto: str) -> None:
    try:
        from config_manager import ConfigManager
        from notifications import NotificationManager
        from telegram_integration import TelegramIntegration
        cm = ConfigManager(str(db_path(env)))
        NotificationManager(cm).send_alert("backup_failed", texto)
        TelegramIntegration(cm).send_alert("backup_failed", texto)
    except Exception as exc:
        log(f"No se pudo enviar el aviso: {exc}")


NOMBRES = {"retencion": "Limpieza de copias antiguas", "verificar": "Comprobacion del almacen",
           "autocopia": "Copia del propio servidor", "vigilar": "Vigilancia",
           "probar": "Prueba de recuperacion", "informe": "Informe mensual"}

# Que hacer cuando falla cada tarea (va en el aviso por correo/Telegram y en el panel)
QUE_HACER = {
    "retencion": "Comprueba que el disco del servidor no esta lleno. Si se repite, avisa al tecnico.",
    "verificar": "El almacen de copias puede estar danado. No borres nada, revisa el disco del servidor y avisa al "
                 "tecnico. Si tienes almacen externo, tus copias siguen alli.",
    "autocopia": "Comprueba el espacio en disco y, si usas almacen externo, la conexion a Internet y sus claves.",
    "probar": "Una copia no se ha podido recuperar bien. Haz una copia nueva de ese equipo y vuelve a probar "
              "desde su ficha en el panel ('Probar recuperacion ahora').",
}


def main(argv: list[str]) -> int:
    env = leer_env()
    cmd = argv[1] if len(argv) > 1 else "todo"
    if cmd == "kit":
        print(kit(env))
        return 0
    if cmd == "probar" and len(argv) > 2:
        r = probar_equipo(env, argv[2])
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r["ok"] else 1
    tareas = {"retencion": retencion, "verificar": verificar, "autocopia": autocopia, "vigilar": vigilar,
              "probar": prueba_recuperacion}
    elegidas = list(tareas) if cmd == "todo" else [cmd]
    if any(t not in tareas for t in elegidas):
        print(__doc__)
        return 2
    resultados = {}
    for t in elegidas:
        log(f"{NOMBRES[t]}...")
        inicio = time.time()
        try:
            resultados[t] = tareas[t](env)
        except Exception as exc:  # una tarea no debe impedir las demas
            resultados[t] = {"ok": False, "detalle": f"error inesperado: {exc}"}
        resultados[t]["segundos"] = round(time.time() - inicio)
        log(f"  {'OK ' if resultados[t]['ok'] else 'MAL'} {resultados[t]['detalle']}")
    if cmd == "todo" and datetime.now().day == 1:
        try:
            import informe
            resultados["informe"] = informe.enviar(env, informe.mes_anterior())
        except Exception as exc:
            resultados["informe"] = {"ok": False, "detalle": f"error inesperado: {exc}"}
        log(f"  Informe mensual: {resultados['informe']['detalle']}")
    if cmd == "todo":
        guardar_estado(resultados)
    fallos = [f"{NOMBRES[k]}: {v['detalle']}" + (f"\n  Que hacer: {QUE_HACER[k]}" if k in QUE_HACER else "")
              for k, v in resultados.items() if not v.get("ok")]
    if fallos:
        avisar(env, "Mantenimiento del servidor OCTOPUS:\n" + "\n".join(fallos))
    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
