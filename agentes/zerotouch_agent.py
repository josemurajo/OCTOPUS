#!/usr/bin/env python3
"""OCTOPUS Zero-Touch - agente portable (Windows, Linux, macOS).

Pensado para empaquetarse con PyInstaller: el usuario final no instala Python.
"""
from __future__ import annotations

import hmac
import http.server
import ipaddress
import json
import threading
import os
import platform
import re
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

PORT = int(os.environ.get("OCTOPUS_AGENT_PORT", "9999"))
AGENT_VERSION = "3.3"
_BACKUP_LOCK = threading.Lock()
SYSTEM = platform.system().lower()


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_candidates() -> list[Path]:
    base = app_dir()
    paths = [
        Path(os.environ["OCTOPUS_CONFIG"]) if os.environ.get("OCTOPUS_CONFIG") else None,
        Path("/etc/octopus/config.json"),
        Path("/Library/Application Support/Octopus/config.json"),
        Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Octopus" / "config.json",
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Octopus" / "config.json",
        base / "config.json",
        base.parent / "config.json",
    ]
    return [p for p in paths if p is not None]


def log_file() -> Path:
    if SYSTEM == "windows":
        d = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Octopus"
    elif SYSTEM == "darwin":
        d = Path("/Library/Logs/Octopus")
    else:
        d = Path("/var/log/octopus")
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d / "agent.log"
    except OSError:
        return app_dir() / "zerotouch_agent.log"


def log(message: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        with open(log_file(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def load_config() -> dict:
    for path in config_candidates():
        try:
            if path.is_file():
                with open(path, encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                data["_config_path"] = str(path)
                return data
        except Exception as exc:
            log(f"Config ilegible {path}: {exc}")
    return {
        "ip_cerebro": os.environ.get("OCTOPUS_CEREBRO", "127.0.0.1"),
        "password_restic": os.environ.get("RESTIC_PASSWORD", "CHANGEME"),
        "minio_port": 9000,
        "bucket": "octopus-backups",
        "backup_paths": [],
        "agent_token": os.environ.get("OCTOPUS_AGENT_TOKEN", ""),
    }


def restic_bin() -> str:
    try:
        elegido = load_config().get("restic_bin")
    except Exception:
        elegido = None
    if elegido and Path(elegido).is_file():
        return str(elegido)
    bundled = app_dir() / ("restic.exe" if SYSTEM == "windows" else "restic")
    if not bundled.is_file() and getattr(sys, "_MEIPASS", None):
        bundled = Path(sys._MEIPASS) / bundled.name
    if bundled.is_file():
        return str(bundled)
    found = shutil.which("restic")
    return found or str(bundled)


def restic_env(cfg: dict) -> dict:
    env = os.environ.copy()
    ip = cfg.get("ip_cerebro", "127.0.0.1")
    port = cfg.get("minio_port", 9000)
    bucket = cfg.get("bucket", "octopus-backups")
    password = cfg.get("password_restic") or cfg.get("restic_password") or "CHANGEME"
    access = cfg.get("minio_access_key") or "admin"
    secret = cfg.get("minio_secret_key") or password
    env["RESTIC_PASSWORD"] = str(password)
    env["RESTIC_REPOSITORY"] = cfg.get("restic_repository", f"s3:http://{ip}:{port}/{bucket}")
    env["AWS_ACCESS_KEY_ID"] = str(access)
    env["AWS_SECRET_ACCESS_KEY"] = str(secret)
    env["AWS_DEFAULT_REGION"] = cfg.get("aws_region", "us-east-1")
    ca = ca_servidor(cfg)
    if ca:
        env["RESTIC_CACERT"] = ca  # el almacen va por HTTPS con la autoridad propia de OCTOPUS
    return env


def ca_servidor(cfg: dict) -> str | None:
    """Autoridad de certificados de OCTOPUS (viene en la configuracion): el agente solo confia en ella."""
    pem = cfg.get("ca_pem")
    if not pem:
        return None
    ruta = STATE_DIR / "servidor_ca.pem"
    try:
        if not ruta.is_file() or ruta.read_text(encoding="utf-8") != pem:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            ruta.write_text(pem, encoding="utf-8")
        return str(ruta)
    except OSError:
        return None


def run_cmd(cmd: list[str], env: dict | None = None, timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=env, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, 124, "", f"timeout: {exc}")
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", f"no encontrado: {exc}")


def agent_host(cfg: dict) -> str:
    """Nombre con el que se etiquetan los snapshots de ESTA maquina (repo compartido)."""
    return str(cfg.get("hostname") or socket.gethostname())


def snapshot_path(path: str) -> str:
    """Ruta tal y como restic la guarda en el snapshot (C:\\x\\y -> /C/x/y en Windows)."""
    p = os.path.abspath(path)
    if SYSTEM == "windows" and len(p) >= 2 and p[1] == ":":
        return "/" + p[0].upper() + p[2:].replace("\\", "/")
    return p


def authorized(handler: http.server.BaseHTTPRequestHandler, cfg: dict) -> bool:
    token = str(cfg.get("agent_token") or "")
    if not token:
        # Sin token configurado solo se aceptan ordenes desde el propio equipo (nunca abierto a la red)
        client = handler.client_address[0].replace("::ffff:", "")
        return client in ("127.0.0.1", "::1")
    header = handler.headers.get("Authorization", "")
    provided = handler.headers.get("X-Octopus-Token", "")
    if header.startswith("Bearer "):
        provided = header.split(" ", 1)[1].strip()
    return hmac.compare_digest(provided.encode(), token.encode())


def source_allowed(handler: http.server.BaseHTTPRequestHandler, cfg: dict) -> bool:
    """Capa extra: solo se aceptan ordenes desde las IPs del cerebro (y desde la propia maquina)."""
    allowed = cfg.get("allowed_sources") or []
    if not allowed:
        return True
    client = handler.client_address[0]
    if client.startswith("::ffff:"):
        client = client[7:]
    for entry in list(allowed) + ["127.0.0.1"]:
        try:
            if ipaddress.ip_address(client) in ipaddress.ip_network(str(entry), strict=False):
                return True
        except ValueError:
            continue
    return False


def _norm(path: str) -> str:
    p = os.path.normpath(os.path.abspath(path))
    return p.lower() if SYSTEM == "windows" else p


def path_protegida(cfg: dict, path: str) -> bool:
    """Solo se puede restaurar/listar dentro de las rutas de las que se hace copia
    (o de cualquier sitio del disco si el equipo tiene la copia completa activada)."""
    return en_rutas_normales(cfg, path) or (bool(AJUSTES_SERVIDOR.get("copia_completa")) and en_copia_completa(path))


def en_rutas_normales(cfg: dict, path: str) -> bool:
    target = _norm(path)
    for base in backup_paths(cfg):
        b = _norm(base)
        if target == b or target.startswith(b.rstrip(os.sep) + os.sep):
            return True
    return False


def en_copia_completa(path: str) -> bool:
    target = _norm(path)
    for base in rutas_completas():
        b = _norm(base)
        if target == b or target.startswith(b.rstrip(os.sep) + os.sep):
            return True
    return False


STATE_DIR = Path(os.environ["OCTOPUS_STATE_DIR"]) if os.environ.get("OCTOPUS_STATE_DIR") else (
    Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Octopus" if platform.system() == "Windows"
    else Path("/Library/Application Support/Octopus") if platform.system() == "Darwin" else Path("/var/lib/octopus"))
ISOLATION_FLAG = STATE_DIR / "aislado.json"


def _resolver(nombre: str) -> list[str]:
    try:
        ipaddress.ip_address(nombre)
        return [nombre]
    except ValueError:
        pass
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(nombre, None, socket.AF_INET)})
    except OSError:
        return []


def _allowed_ips(cfg: dict) -> list[str]:
    """Durante un aislamiento solo se puede hablar con el servidor OCTOPUS."""
    ips = []
    for nombre in [cfg.get("servidor"), cfg.get("ip_cerebro"), cfg.get("cerebro_endpoint")]:
        if nombre:
            ips += _resolver(str(nombre))
    ips += [str(x) for x in (cfg.get("isolation_allow") or [])]  # p.ej. gestion del laboratorio
    return list(dict.fromkeys(ips)) or ["127.0.0.1"]


HOSTS_FILE = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "drivers" / "etc" / "hosts" \
    if platform.system() == "Windows" else Path("/etc/hosts")
MARCA_HOSTS = "# octopus-aislamiento"


def _fijar_hosts(cfg: dict) -> None:
    """Aislado no hay DNS: se apunta el nombre del servidor en el archivo hosts mientras dure."""
    nombre = str(cfg.get("servidor") or "")
    try:
        ipaddress.ip_address(nombre)
        return
    except ValueError:
        pass
    ips = _resolver(nombre) if nombre else []
    if not ips:
        return
    try:
        texto = HOSTS_FILE.read_text(encoding="utf-8", errors="replace")
        lineas = [l for l in texto.splitlines() if MARCA_HOSTS not in l]
        lineas.append(f"{ips[0]} {nombre} {MARCA_HOSTS}")
        HOSTS_FILE.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    except OSError as exc:
        log(f"No se pudo fijar el servidor en {HOSTS_FILE}: {exc}")


def _quitar_hosts() -> None:
    try:
        texto = HOSTS_FILE.read_text(encoding="utf-8", errors="replace")
        if MARCA_HOSTS in texto:
            HOSTS_FILE.write_text("\n".join(l for l in texto.splitlines() if MARCA_HOSTS not in l) + "\n",
                                  encoding="utf-8")
    except OSError:
        pass


def esta_aislado() -> bool:
    return ISOLATION_FLAG.exists()


def aislar_maquina(cfg: dict) -> dict:
    """Corta toda la red del equipo salvo el servidor OCTOPUS (y el tunel)."""
    log("Aislando maquina")
    ips = _allowed_ips(cfg)
    if cfg.get("simular_aislamiento"):  # solo pruebas automaticas: no se toca el cortafuegos
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ISOLATION_FLAG.write_text(json.dumps({"desde": datetime.now().isoformat(), "permitido": ips, "simulado": True}))
        log(f"Aislamiento SIMULADO (solo permitido: {ips})")
        return {"status": "success", "message": "Maquina aislada (simulado)", "permitido": ips}
    _fijar_hosts(cfg)
    try:
        if SYSTEM == "windows":
            # En Windows una regla de bloqueo gana a cualquier regla de permitir: se cambia la
            # politica por defecto a bloquear y se permite solo el servidor.
            run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", "name=Octopus-AllowCerebro"])
            run_cmd(["netsh", "advfirewall", "firewall", "add", "rule", "name=Octopus-AllowCerebro",
                     "dir=out", "action=allow", f"remoteip={','.join(ips)}", "enable=yes"])
            run_cmd(["netsh", "advfirewall", "firewall", "add", "rule", "name=Octopus-AllowCerebroIn",
                     "dir=in", "action=allow", f"remoteip={','.join(ips)}", "enable=yes"])
            r = run_cmd(["netsh", "advfirewall", "set", "allprofiles", "firewallpolicy", "blockinbound,blockoutbound"])
            run_cmd(["netsh", "advfirewall", "set", "allprofiles", "state", "on"])
        elif SYSTEM == "darwin":
            rules = "block all\npass quick on lo0 all\n" + "".join(f"pass quick to {ip}\npass quick from {ip}\n" for ip in ips)
            Path("/etc/octopus_pf.conf").write_text(rules)
            r = run_cmd(["pfctl", "-e", "-f", "/etc/octopus_pf.conf"])
        elif shutil.which("nft"):
            run_cmd(["nft", "delete", "table", "inet", "octopus"])
            allow = " ".join(f"ip daddr {ip} accept;" for ip in ips)
            allow_in = " ".join(f"ip saddr {ip} accept;" for ip in ips)
            ruleset = (
                "table inet octopus {\n"
                "  chain out { type filter hook output priority -10; policy drop;\n"
                f"    oif lo accept; ct state established,related accept; {allow} }}\n"
                "  chain inp { type filter hook input priority -10; policy drop;\n"
                f"    iif lo accept; ct state established,related accept; {allow_in} }}\n"
                "}\n")
            tmp = STATE_DIR / "octopus.nft"
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp.write_text(ruleset)
            r = run_cmd(["nft", "-f", str(tmp)])
        elif shutil.which("iptables"):
            reincorporar_red()
            for chain, hook in (("OCTOPUS_OUT", "OUTPUT"), ("OCTOPUS_IN", "INPUT")):
                run_cmd(["iptables", "-N", chain])
                flag = "-o" if hook == "OUTPUT" else "-i"
                run_cmd(["iptables", "-A", chain, flag, "lo", "-j", "ACCEPT"])
                run_cmd(["iptables", "-A", chain, "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"])
                for ip in ips:
                    run_cmd(["iptables", "-A", chain, "-d" if hook == "OUTPUT" else "-s", ip, "-j", "ACCEPT"])
                run_cmd(["iptables", "-A", chain, "-j", "DROP"])
                r = run_cmd(["iptables", "-I", hook, "1", "-j", chain])
        else:
            return {"status": "error", "message": "No hay cortafuegos disponible para aislar"}
        if r.returncode != 0:
            return {"status": "error", "message": r.stderr or r.stdout}
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ISOLATION_FLAG.write_text(json.dumps({"desde": datetime.now().isoformat(), "permitido": ips}))
        log(f"Maquina aislada (solo permitido: {ips})")
        return {"status": "success", "message": "Maquina aislada", "permitido": ips}
    except Exception as exc:
        log(f"Error aislando: {exc}")
        return {"status": "error", "message": str(exc)}


def reincorporar_red() -> dict:
    log("Reincorporando a la red")
    try:
        if ISOLATION_FLAG.exists() and '"simulado": true' in ISOLATION_FLAG.read_text():
            ISOLATION_FLAG.unlink()
            return {"status": "success", "message": "Maquina reincorporada (simulado)"}
        if SYSTEM == "windows":
            run_cmd(["netsh", "advfirewall", "set", "allprofiles", "firewallpolicy", "blockinbound,allowoutbound"])
            run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", "name=Octopus-AllowCerebro"])
            run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", "name=Octopus-AllowCerebroIn"])
            run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", "name=Octopus-Isolation"])
        elif SYSTEM == "darwin":
            run_cmd(["pfctl", "-d"])
        else:
            if shutil.which("nft"):
                run_cmd(["nft", "delete", "table", "inet", "octopus"])
            if shutil.which("iptables"):
                for chain, hook in (("OCTOPUS_OUT", "OUTPUT"), ("OCTOPUS_IN", "INPUT")):
                    for _ in range(20):  # quitar todas las referencias (con limite por seguridad)
                        if run_cmd(["iptables", "-D", hook, "-j", chain], timeout=10).returncode != 0:
                            break
                    run_cmd(["iptables", "-F", chain])
                    run_cmd(["iptables", "-X", chain])
        try:
            ISOLATION_FLAG.unlink()
        except FileNotFoundError:
            pass
        _quitar_hosts()
        return {"status": "success", "message": "Maquina reincorporada"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# DETECTOR DE ATAQUES (ransomware / cifrado masivo)
# ---------------------------------------------------------------------------
RANSOM_EXT = {".locked", ".encrypted", ".enc", ".crypt", ".crypted", ".crypto", ".cry", ".lockbit", ".ryk",
              ".wncry", ".wnry", ".wcry", ".cerber", ".locky", ".zepto", ".odin", ".djvu", ".crypz", ".kraken",
              ".conti", ".phobos", ".makop", ".stop", ".pay", ".ransom", ".blackcat", ".hive", ".royal", ".akira",
              ".basta", ".clop", ".8base", ".nokoyawa", ".medusa", ".rhysida", ".play"}
RANSOM_NOTES = ("readme_decrypt", "how_to_decrypt", "decrypt_instructions", "restore_files", "how_to_recover",
                "recover-files", "recover_files", "!readme!", "_readme.txt", "read_me_to_decrypt", "ransom",
                "your_files_are_encrypted", "help_decrypt", "restore-my-files")
_detector_state = {"mtimes": {}, "recent": [], "last_alert": 0.0, "suspended_until": 0.0}
_detector_lock = threading.Lock()


def _entropy(data: bytes) -> float:
    import math
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts if c)


def suspender_detector(segundos: int = 120) -> None:
    """Durante una restauracion los cambios son legitimos: no deben disparar alertas."""
    with _detector_lock:
        _detector_state["suspended_until"] = time.time() + segundos


# ---- archivos señuelo: un archivo trampa oculto en cada carpeta protegida. Nadie lo usa: si cambia o
# desaparece, casi seguro es un ransomware recorriendo las carpetas -> alerta inmediata (sin esperar umbrales).
SENUELOS_FILE = STATE_DIR / "senuelos.json"
_NOMBRE_SENUELO = "~octopus_no_tocar.docx" if SYSTEM == "windows" else ".octopus_no_tocar.docx"


def senuelos_activos(cfg: dict) -> bool:
    return bool(cfg.get("senuelos", True)) and AJUSTES_SERVIDOR.get("senuelos", True) is not False


def _leer_senuelos() -> dict:
    try:
        return json.loads(SENUELOS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_senuelos(datos: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SENUELOS_FILE.write_text(json.dumps(datos), encoding="utf-8")
    except OSError:
        pass


def _crear_senuelo(ruta: str) -> str | None:
    import hashlib
    contenido = ("OCTOPUS - archivo de proteccion. No lo abras, no lo muevas y no lo borres.\n"
                 "Si este archivo cambia, OCTOPUS entiende que hay un ataque y protege el equipo.\n" * 40
                 + f"id {os.urandom(8).hex()}\n").encode()
    try:
        if os.path.exists(ruta) and SYSTEM == "windows":
            run_cmd(["attrib", "-h", ruta], timeout=20)
        with open(ruta, "wb") as fh:
            fh.write(contenido)
        if SYSTEM == "windows":
            run_cmd(["attrib", "+h", ruta], timeout=20)
        return hashlib.sha256(contenido).hexdigest()
    except OSError:
        return None


def preparar_senuelos(cfg: dict) -> None:
    """Crea los señuelos que falten (solo en carpetas protegidas nuevas) o los quita si se desactivan."""
    estado = _leer_senuelos()
    if not senuelos_activos(cfg):
        if estado:
            for ruta in estado:
                try:
                    os.remove(ruta)
                except OSError:
                    pass
            _guardar_senuelos({})
        return
    bases = [b for b in backup_paths(cfg) if os.path.isdir(b)]
    nuevo = {r: h for r, h in estado.items() if os.path.dirname(r) in bases}
    for b in bases:
        ruta = os.path.join(b, _NOMBRE_SENUELO)
        if ruta not in nuevo:
            h = _crear_senuelo(ruta)
            if h:
                nuevo[ruta] = h
                log(f"Señuelo creado en {b}")
    if nuevo != estado:
        _guardar_senuelos(nuevo)


def revisar_senuelos() -> list[str]:
    import hashlib
    tocados = []
    for ruta, h in _leer_senuelos().items():
        try:
            with open(ruta, "rb") as fh:
                if hashlib.sha256(fh.read()).hexdigest() != h:
                    tocados.append(f"{ruta} (modificado)")
        except FileNotFoundError:
            tocados.append(f"{ruta} (borrado o renombrado)")
        except OSError as exc:
            tocados.append(f"{ruta} (no se puede leer: {exc.__class__.__name__})")
    return tocados


def rehacer_senuelos(tocados: list[str]) -> None:
    """Tras avisar, se vuelven a poner (con una huella nueva) para seguir vigilando."""
    estado = _leer_senuelos()
    for t in tocados:
        ruta = t.rsplit(" (", 1)[0]
        if ruta in estado:
            h = _crear_senuelo(ruta)
            if h:
                estado[ruta] = h
    _guardar_senuelos(estado)


def aceptar_senuelos_actuales() -> None:
    """Despues de una recuperacion (legitima) los señuelos pueden volver con otro contenido: se aceptan tal cual
    estan y, si alguno falta, se vuelve a crear."""
    import hashlib
    estado = _leer_senuelos()
    for ruta in list(estado):
        try:
            with open(ruta, "rb") as fh:
                estado[ruta] = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            h = _crear_senuelo(ruta)
            if h:
                estado[ruta] = h
    _guardar_senuelos(estado)


def _escanear(cfg: dict) -> dict | None:
    """Compara el estado actual con el anterior y devuelve una alerta si parece un ataque."""
    now = time.time()
    if senuelos_activos(cfg) and now >= _detector_state["suspended_until"]:
        tocados = revisar_senuelos()
        if tocados:
            rehacer_senuelos(tocados)
            return {"severidad": "critica", "motivo": "Archivo señuelo tocado (casi seguro un ransomware): " +
                    "; ".join(tocados[:5]), "evidencias": [t.rsplit(" (", 1)[0] for t in tocados][:80],
                    "detectado": datetime.now().astimezone().isoformat()}
    previo = _detector_state["mtimes"]
    actual, cambiados, nuevos = {}, [], []
    contados = 0
    for base in backup_paths(cfg):
        for root, dirs, files in os.walk(base):
            for name in files:
                p = os.path.join(root, name)
                try:
                    m = os.stat(p).st_mtime
                except OSError:
                    continue
                actual[p] = m
                contados += 1
                if p not in previo:
                    nuevos.append(p)
                elif previo[p] != m:
                    cambiados.append(p)
                if contados > 200000:
                    break
    primera_vez = not previo
    _detector_state["mtimes"] = actual
    if primera_vez or now < _detector_state["suspended_until"]:
        return None
    tocados = nuevos + cambiados
    _detector_state["recent"] = [(t, p) for t, p in _detector_state["recent"] if now - t < 60] + [(now, p) for p in tocados]
    evidencias, motivos = [], []
    ext_sosp = [p for p in tocados if os.path.splitext(p)[1].lower() in RANSOM_EXT]
    notas = [p for p in nuevos if any(k in os.path.basename(p).lower() for k in RANSOM_NOTES)]
    if ext_sosp:
        motivos.append(f"{len(ext_sosp)} archivos con extension de ransomware")
        evidencias += ext_sosp[:50]
    if notas:
        motivos.append("nota de rescate: " + ", ".join(os.path.basename(n) for n in notas[:3]))
        evidencias += notas[:10]
    recientes = {p for _, p in _detector_state["recent"]}
    umbral = int(cfg.get("detector_umbral_archivos", 20))
    if len(recientes) >= umbral:
        altas = 0
        muestra = list(recientes)[:40]
        for p in muestra:
            try:
                with open(p, "rb") as fh:
                    if _entropy(fh.read(4096)) > 7.2:
                        altas += 1
            except OSError:
                pass
        if altas >= max(5, len(muestra) // 2):
            motivos.append(f"{len(recientes)} archivos modificados en menos de 1 minuto con contenido cifrado")
            evidencias += muestra[:30]
    if not motivos:
        return None
    return {"severidad": "critica", "motivo": "; ".join(motivos), "evidencias": list(dict.fromkeys(evidencias))[:80],
            "detectado": datetime.now().astimezone().isoformat()}


def _https(cfg: dict, ruta: str, datos: dict, timeout: float = 30) -> dict:
    """Peticion al servidor OCTOPUS por HTTPS, comprobando su certificado con la autoridad de OCTOPUS."""
    import ssl
    import urllib.request
    url = str(cfg.get("panel_url") or f"https://{cfg.get('servidor') or cfg.get('ip_cerebro')}:8080").rstrip("/") + ruta
    ca = ca_servidor(cfg)
    ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    req = urllib.request.Request(url, data=json.dumps(datos).encode(), method="POST", headers={
        "Content-Type": "application/json", "User-Agent": f"octopus-agente/{AGENT_VERSION}",
        "X-Octopus-Equipo": agent_host(cfg), "X-Octopus-Token": str(cfg.get("agent_token") or "")})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def _avisar_cerebro(cfg: dict, alerta: dict) -> bool:
    for intento in range(5):
        try:
            _https(cfg, "/api/agente/alerta", {"host": agent_host(cfg), **alerta}, timeout=15)
            log("Alerta enviada al servidor")
            return True
        except Exception as exc:
            log(f"No se pudo avisar al servidor (intento {intento + 1}): {exc}")
            time.sleep(5)
    return False


def detector_loop() -> None:
    log("Detector de ataques activo")
    while True:
        try:
            cfg = load_config()
            if cfg.get("detector", True) and not esta_aislado():
                try:
                    preparar_senuelos(cfg)
                except Exception as exc:
                    log(f"Señuelos: {exc}")
                with _detector_lock:
                    alerta = _escanear(cfg)
                if alerta and time.time() - _detector_state["last_alert"] > 600:
                    _detector_state["last_alert"] = time.time()
                    log(f"ATAQUE DETECTADO: {alerta['motivo']}")
                    _avisar_cerebro(cfg, alerta)
        except Exception as exc:
            log(f"Detector: error {exc}")
        time.sleep(int(load_config().get("detector_intervalo", 10)))


# ---------------------------------------------------------------------------
# RESPUESTA A INCIDENTES
# ---------------------------------------------------------------------------
def recoger_evidencias(cfg: dict, incidente: str) -> Path:
    """Procesos, conexiones y usuarios en el momento del incidente (se guardan con la copia forense)."""
    d = STATE_DIR / "forense" / incidente
    d.mkdir(parents=True, exist_ok=True)
    cmds = {
        "procesos.txt": ["tasklist", "/v"] if SYSTEM == "windows" else ["ps", "auxww"],
        "conexiones.txt": ["netstat", "-ano"] if SYSTEM == "windows" else (["ss", "-tupan"] if shutil.which("ss") else ["netstat", "-tupan"]),
        "usuarios.txt": ["query", "user"] if SYSTEM == "windows" else ["who", "-a"],
    }
    for name, cmd in cmds.items():
        r = run_cmd(cmd, timeout=60)
        (d / name).write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8", errors="replace")
    (d / "info.json").write_text(json.dumps({"host": agent_host(cfg), "incidente": incidente, "os": SYSTEM,
                                             "fecha": datetime.now().astimezone().isoformat(),
                                             "rutas": backup_paths(cfg)}, indent=2), encoding="utf-8")
    return d


def copia_forense(cfg: dict, incidente: str) -> dict:
    """Copia del estado INFECTADO al almacen de cuarentena (repositorio separado de las copias buenas)."""
    repo = cfg.get("restic_repository_cuarentena")
    if not repo:
        return {"status": "error", "message": "Falta restic_repository_cuarentena en la configuracion"}
    env = restic_env(cfg)
    env["RESTIC_REPOSITORY"] = repo
    env["RESTIC_PASSWORD"] = str(cfg.get("password_cuarentena") or cfg.get("password_restic"))
    binary = restic_bin()
    if run_cmd([binary, "cat", "config"], env=env, timeout=120).returncode != 0:
        run_cmd([binary, "init"], env=env, timeout=300)
    evid = recoger_evidencias(cfg, incidente)
    targets = backup_paths(cfg) + [str(evid)]
    r = run_cmd([binary, "backup", *targets, "--tag", "forense", "--tag", f"incidente-{incidente}",
                 "--host", agent_host(cfg), "--json"], env=env)
    if r.returncode != 0:
        return {"status": "error", "message": r.stderr or r.stdout}
    snap = ""
    for line in (r.stdout or "").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("message_type") == "summary":
            snap = d.get("snapshot_id", "")
    log(f"Copia forense del incidente {incidente}: {snap}")
    return {"status": "success", "snapshot_id": snap, "paths": targets}


def restaurar_limpio(cfg: dict, snapshot: str) -> dict:
    """Sustituye por completo las carpetas protegidas por su estado en una copia sana
    (borra lo que haya dejado el ataque: archivos cifrados, notas de rescate...)."""
    suspender_detector(600)
    env = restic_env(cfg)
    resultados = []
    for base in backup_paths(cfg):
        in_snap = snapshot_path(base)
        with tempfile.TemporaryDirectory(prefix="octopus_limpio_") as tmp:
            r = run_cmd([restic_bin(), "restore", snapshot, "--target", tmp, "--include", in_snap], env=env)
            restored = Path(tmp) / in_snap.lstrip("/")
            if r.returncode != 0 or not restored.exists():
                resultados.append({"ruta": base, "ok": False, "error": (r.stderr or "no esta en la copia")[:300]})
                continue
            if os.path.isdir(base):
                for entry in os.listdir(base):
                    p = os.path.join(base, entry)
                    try:
                        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
                    except OSError as exc:
                        log(f"No se pudo borrar {p}: {exc}")
                shutil.copytree(restored, base, dirs_exist_ok=True)
            else:
                shutil.copy2(restored, base)
            resultados.append({"ruta": base, "ok": True})
    aceptar_senuelos_actuales()
    suspender_detector(120)
    _detector_state["mtimes"] = {}
    ok = all(r["ok"] for r in resultados) and resultados
    return {"status": "success" if ok else "error", "resultados": resultados,
            "message": "" if ok else "Alguna ruta no se pudo restaurar"}


def mostrar_aviso(titulo: str, mensaje: str) -> dict:
    """Muestra un aviso al usuario del equipo y lo deja escrito en un archivo visible."""
    texto = f"{titulo}\n\n{mensaje}\n"
    hechos = []
    try:
        if SYSTEM == "windows":
            pub = Path(os.environ.get("PUBLIC", "C:\\Users\\Public")) / "Desktop" / "AVISO_SEGURIDAD.txt"
            pub.parent.mkdir(parents=True, exist_ok=True)
            pub.write_text(texto, encoding="utf-8")
            hechos.append(str(pub))
            if shutil.which("msg"):
                run_cmd(["msg", "*", "/TIME:0", f"{titulo}\n\n{mensaje}"], timeout=30)
                hechos.append("ventana emergente (msg)")
        else:
            homes = Path("/Users") if SYSTEM == "darwin" else Path("/home")
            for home in [Path("/root")] + [p for p in homes.glob("*") if p.is_dir() and p.name != "Shared"]:
                destinos = [home / "AVISO_SEGURIDAD.txt"]
                for escritorio in ("Escritorio", "Desktop"):
                    if (home / escritorio).is_dir():
                        destinos.append(home / escritorio / "AVISO_SEGURIDAD.txt")
                for f in destinos:
                    try:
                        f.write_text(texto, encoding="utf-8")
                        if home.name != "root":
                            shutil.chown(f, user=home.name)
                        hechos.append(str(f))
                    except Exception:
                        pass
            try:
                motd = Path("/etc/motd")
                orig = STATE_DIR / "motd.orig"
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                if not orig.exists():
                    orig.write_text(motd.read_text() if motd.exists() else "")
                motd.write_text("\n" + "*" * 70 + "\n" + texto + "*" * 70 + "\n\n" + orig.read_text())
                hechos.append("mensaje al iniciar sesion")
            except Exception:
                pass
            if shutil.which("wall"):
                subprocess.run(["wall"], input=texto, text=True, capture_output=True, timeout=10)
                hechos.append("terminales abiertos (wall)")
            if shutil.which("notify-send") and shutil.which("loginctl"):
                ses = run_cmd(["loginctl", "list-sessions", "--no-legend"], timeout=10).stdout or ""
                for line in ses.splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        uid, user = parts[1], parts[2]
                        run_cmd(["sudo", "-u", user, f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                                 "notify-send", "-u", "critical", titulo, mensaje], timeout=10)
                hechos.append("notificacion de escritorio")
        log(f"Aviso mostrado al usuario: {hechos}")
        return {"status": "success", "donde": hechos}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def eliminar_amenaza(cfg: dict, rutas: list) -> dict:
    """Borra del equipo los archivos maliciosos indicados (solo dentro de las carpetas protegidas)."""
    suspender_detector(120)
    borrados, rechazados, no_existen = [], [], []
    for r in rutas[:500]:
        r = str(r)
        if not path_protegida(cfg, r):
            rechazados.append(r)
            continue
        p = os.path.abspath(r)
        if not os.path.lexists(p):
            no_existen.append(r)
            continue
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            borrados.append(r)
        except OSError as exc:
            rechazados.append(f"{r} ({exc})")
    log(f"Amenaza eliminada: {len(borrados)} borrados, {len(no_existen)} ya no existian, {len(rechazados)} rechazados")
    return {"status": "success" if not rechazados else "error", "borrados": borrados, "no_existian": no_existen,
            "rechazados": rechazados, "message": "" if not rechazados else "Algunas rutas no se pudieron borrar"}


def quitar_aviso() -> dict:
    if SYSTEM != "windows":
        orig = STATE_DIR / "motd.orig"
        if orig.exists():
            Path("/etc/motd").write_text(orig.read_text())
            orig.unlink()
    return {"status": "success"}


# Rutas que NUNCA se tratan como carpeta protegida: restaurar "en limpio" una de ellas borraria el sistema,
# y leerlas (/proc, /sys, /dev) puede bloquear la copia.
_RUTAS_PROHIBIDAS_LINUX = {"/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/proc", "/run",
                           "/sbin", "/sys", "/usr", "/var", "/var/lib", "/var/log", "/tmp", "/opt"}
_PREFIJOS_PROHIBIDOS_LINUX = ("/proc/", "/sys/", "/dev/", "/run/")


def _lista_rutas(valor) -> list[str]:
    """Acepta lista, texto JSON ('["/a","/b"]') o texto separado por comas/;. Nunca trocea letra a letra."""
    if not valor:
        return []
    if isinstance(valor, (list, tuple)):
        return [str(v).strip() for v in valor if str(v).strip()]
    texto = str(valor).strip()
    if texto.startswith("["):
        try:
            datos = json.loads(texto)
            if isinstance(datos, list):
                return [str(v).strip() for v in datos if str(v).strip()]
        except ValueError:
            texto = texto.strip("[]")
    return [p.strip().strip("'\"") for p in re.split(r"[;,]", texto) if p.strip().strip("'\"")]


def ruta_permitida(p: str) -> bool:
    if SYSTEM == "windows":
        n = os.path.normcase(os.path.abspath(p)).rstrip("\\/")
        prohibidas = {os.path.normcase(x).rstrip("\\") for x in
                      ("C:\\", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\ProgramData")}
        return len(n) > 3 and n not in prohibidas and not n.startswith(os.path.normcase("C:\\Windows\\"))
    n = os.path.normpath(os.path.abspath(p))
    if SYSTEM == "darwin":
        if n in {"/", "/System", "/Library", "/Applications", "/private", "/usr", "/bin", "/sbin", "/var", "/etc",
                 "/tmp", "/opt", "/Volumes", "/Users"} - {"/Users"} or n.startswith(("/System/", "/private/", "/dev/")):
            return False
        return True
    return n not in _RUTAS_PROHIBIDAS_LINUX and not (n + "/").startswith(_PREFIJOS_PROHIBIDOS_LINUX)


def backup_paths(cfg: dict, extra=None) -> list[str]:
    paths = _lista_rutas(cfg.get("backup_paths"))
    paths += _lista_rutas(extra)
    if not paths:
        paths = [str(Path.home())]
    # quitar duplicados, rutas inexistentes y rutas de sistema
    seen, result = set(), []
    for p in paths:
        if p in seen or not os.path.exists(p):
            continue
        seen.add(p)
        if not ruta_permitida(p):
            log(f"Ruta ignorada por seguridad (carpeta del sistema): {p}")
            continue
        result.append(p)
    return result


EXCLUSIONES_MAC = ["/Users/*/Library/Caches", "/Users/*/Library/Logs", "/Users/*/.Trash", "*.tmp", ".DS_Store"]
EXCLUSIONES_WINDOWS = ["C:\\Users\\*\\AppData\\Local", "C:\\Users\\*\\AppData\\LocalLow",
                       "C:\\Users\\*\\NTUSER.DAT*", "C:\\Users\\*\\ntuser.dat*", "*.tmp", "~$*"]


# Ajustes que manda el servidor en cada consulta (se pueden cambiar en el panel sin reinstalar nada)
AJUSTES_SERVIDOR: dict = {}

# ---------------------------------------------------------------- copia completa del equipo (opcional)
# Todo el disco del sistema salvo lo que no sirve para nada al recuperar (temporales, papelera, memoria virtual,
# caches). Sirve para reconstruir un equipo: se reinstala el sistema, el agente, y se recupera todo de esta copia.
EXCL_COMPLETA_WINDOWS = ["C:\\pagefile.sys", "C:\\hiberfil.sys", "C:\\swapfile.sys", "C:\\$Recycle.Bin",
                         "C:\\System Volume Information", "C:\\Windows\\Temp", "C:\\Windows\\SoftwareDistribution\\Download",
                         "C:\\Users\\*\\AppData\\Local\\Temp", "C:\\Users\\*\\AppData\\Local\\*\\Cache",
                         "C:\\ProgramData\\Microsoft\\Windows Defender\\Scans", "*.tmp"]
EXCL_COMPLETA_LINUX = ["/proc", "/sys", "/dev", "/run", "/tmp", "/var/tmp", "/var/cache", "/mnt", "/media",
                       "/lost+found", "/swapfile", "/swap.img", "/var/lib/docker", "/var/lib/containerd",
                       "/home/*/.cache", "/root/.cache"]
EXCL_COMPLETA_MAC = ["/System/Volumes/Data/private/var/vm", "/System/Volumes/Data/private/tmp",
                     "/System/Volumes/Data/private/var/folders", "/System/Volumes/Data/Volumes",
                     "/System/Volumes/Data/.Spotlight-V100", "/System/Volumes/Data/.fseventsd",
                     "/System/Volumes/Data/Users/*/Library/Caches", "/System/Volumes/Data/Users/*/.Trash"]


def rutas_completas() -> list[str]:
    # OCTOPUS_RUTA_COMPLETA: otra raiz (o varias separadas por ";"), p. ej. un servidor con los datos en otro disco
    if os.environ.get("OCTOPUS_RUTA_COMPLETA"):
        return [r for r in os.environ["OCTOPUS_RUTA_COMPLETA"].split(";") if r.strip()]
    if SYSTEM == "windows":
        return [(os.environ.get("SystemDrive") or "C:") + "\\"]
    if SYSTEM == "darwin":
        return ["/System/Volumes/Data"]   # en macOS el disco "/" del sistema es de solo lectura: los datos van aqui
    return ["/"]


def copia_completa(cfg: dict) -> dict:
    """Copia de todo el disco del sistema (etiqueta 'completa'), aparte de la copia diaria de las carpetas."""
    if not _BACKUP_LOCK.acquire(blocking=False):
        return {"status": "error", "message": "Ya hay una copia en curso en este equipo"}
    try:
        log("Copia completa del equipo")
        binary = restic_bin()
        if not _restic_ready(binary):
            return {"status": "error", "message": f"restic no encontrado: {binary}"}
        err = asegurar_repo(cfg)
        if err:
            return err
        excl = EXCL_COMPLETA_WINDOWS if SYSTEM == "windows" else EXCL_COMPLETA_MAC if SYSTEM == "darwin" else EXCL_COMPLETA_LINUX
        cmd = [binary, "backup", *rutas_completas(), "--tag", "octopus-agent", "--tag", "completa",
               "--host", agent_host(cfg), "--json"]
        for e in excl:
            cmd += ["--exclude", e]
        kbps = limite_subida(AJUSTES_SERVIDOR)
        if kbps:
            cmd += ["--limit-upload", str(kbps)]
        if SYSTEM == "windows":
            cmd.append("--use-fs-snapshot")
        else:
            cmd.append("--one-file-system")
        result = run_cmd(cmd, env=restic_env(cfg))
        if result.returncode not in (0, 3):
            log(f"Copia completa fallida: {(result.stderr or '').strip()[-300:]}")
            return {"status": "error", "message": (result.stderr or result.stdout)[-1000:]}
        snap = ""
        for line in (result.stdout or "").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("message_type") == "summary":
                snap = d.get("snapshot_id", "")
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            (STATE_DIR / "ultima_copia_completa.txt").write_text(datetime.now().isoformat(timespec="seconds"))
        except OSError:
            pass
        log(f"Copia completa OK snapshot={snap}")
        r = {"status": "success", "snapshot_id": snap, "paths": rutas_completas(), "host": agent_host(cfg), "completa": True}
        if result.returncode == 3:
            r["aviso"] = "Algunos archivos no se pudieron leer (en uso o sin permiso)"
        return r
    finally:
        _BACKUP_LOCK.release()


def toca_copia_completa(ahora: datetime | None = None) -> bool:
    """Si esta activada y la ultima copia completa tiene mas de N dias (7 por defecto)."""
    if not AJUSTES_SERVIDOR.get("copia_completa"):
        return False
    try:
        dias = float(AJUSTES_SERVIDOR.get("copia_completa_dias") or 7)
    except (TypeError, ValueError):
        dias = 7
    try:
        ultima = datetime.fromisoformat((STATE_DIR / "ultima_copia_completa.txt").read_text().strip())
    except (OSError, ValueError):
        return True
    return ((ahora or datetime.now()) - ultima).total_seconds() >= dias * 86400 - 3600


def limite_subida(ajustes: dict, ahora: datetime | None = None) -> int:
    """KB/s maximos para la copia (0 = sin limite). Con 'solo_horario', solo de lunes a viernes de 8 a 20 h."""
    try:
        kbps = int(ajustes.get("limite_kbps") or 0)
    except (TypeError, ValueError):
        return 0
    if kbps <= 0:
        return 0
    ahora = ahora or datetime.now()
    if ajustes.get("solo_horario", True) and not (ahora.weekday() < 5 and 8 <= ahora.hour < 20):
        return 0
    return kbps


def opciones_backup(cfg: dict) -> list[str]:
    """Exclusiones (cache, temporales, archivos bloqueados de Windows), instantanea VSS en Windows
    y limite de velocidad si se ha elegido en el panel."""
    opts = []
    kbps = limite_subida(AJUSTES_SERVIDOR)
    if kbps:
        opts += ["--limit-upload", str(kbps)]
    excl = cfg.get("exclude")
    if excl is None:
        excl = (EXCLUSIONES_WINDOWS if SYSTEM == "windows" else EXCLUSIONES_MAC if SYSTEM == "darwin"
                else ["/home/*/.cache", "*.tmp"])
    for e in _lista_rutas(excl) if not isinstance(excl, list) else excl:
        opts += ["--exclude", str(e)]
    if SYSTEM == "windows" and cfg.get("vss", True):
        opts.append("--use-fs-snapshot")  # copia coherente aunque haya archivos abiertos
    return opts


def _restic_ready(binary: str) -> bool:
    return bool(shutil.which(binary)) or Path(binary).is_file()


def asegurar_repo(cfg: dict) -> dict | None:
    """Inicializa el repositorio si aun no existe. Devuelve dict de error o None si OK."""
    env = restic_env(cfg)
    binary = restic_bin()
    if run_cmd([binary, "cat", "config"], env=env, timeout=120).returncode == 0:
        return None
    init = run_cmd([binary, "init"], env=env, timeout=300)
    if init.returncode != 0 and "already" not in (init.stderr or "").lower():
        return {"status": "error", "message": "No se pudo abrir/inicializar el repositorio: " + (init.stderr or init.stdout)}
    return None


ULTIMA_COPIA = STATE_DIR / "ultima_copia.txt"
HORAS_COPIA_ATRASADA = 26


def _apuntar_copia() -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ULTIMA_COPIA.write_text(datetime.now().isoformat(timespec="seconds"))
    except OSError:
        pass


def horas_desde_ultima_copia() -> float | None:
    try:
        return (datetime.now() - datetime.fromisoformat(ULTIMA_COPIA.read_text().strip())).total_seconds() / 3600
    except (OSError, ValueError):
        return None


def copia_atrasada_loop() -> None:
    """Si el equipo estaba apagado a la hora de la copia diaria (o hubo un corte de luz), la copia se hace sola en
    cuanto el equipo vuelve a estar encendido, sin esperar al dia siguiente."""
    time.sleep(300)   # deja arrancar el equipo con calma
    while True:
        try:
            h = horas_desde_ultima_copia()
            if h is None:
                _apuntar_copia()          # recien instalado: se cuenta desde ahora (la primera copia la pide el panel)
            elif h > HORAS_COPIA_ATRASADA and not esta_aislado():
                log(f"La ultima copia es de hace {int(h)} h (el equipo estuvo apagado): copia atrasada ahora")
                copia_programada()
        except Exception as exc:
            log(f"Copia atrasada: {exc}")
        time.sleep(1800)


def backup_forense(cfg: dict, path=None) -> dict:
    if not _BACKUP_LOCK.acquire(blocking=False):
        return {"status": "error", "message": "Ya hay una copia en curso en este equipo"}
    try:
        return _backup_forense(cfg, path)
    finally:
        _BACKUP_LOCK.release()


def _backup_forense(cfg: dict, path=None) -> dict:
    pasos: list[str] = []
    inicio = time.time()

    def paso(texto: str) -> None:
        pasos.append(f"[{datetime.now():%H:%M:%S}] {texto}")
        log(texto)
    res = _backup_forense_pasos(cfg, path, paso)
    paso(f"Fin de la copia ({int(time.time() - inicio)} s): {res.get('status')}")
    res["pasos"] = pasos
    return res


def _backup_forense_pasos(cfg: dict, path, paso) -> dict:
    paso("Copia de seguridad: empieza")
    env = restic_env(cfg)
    binary = restic_bin()
    if not _restic_ready(binary):
        return {"status": "error", "message": f"restic no encontrado: {binary}"}
    targets = backup_paths(cfg, path)
    if not targets:
        paso("No existe ninguna de las carpetas a copiar")
        return {"status": "error", "message": "Ninguna ruta de backup existe en esta maquina"}
    paso(f"Carpetas a copiar: {len(targets)}")
    err = asegurar_repo(cfg)
    if err:
        paso("No se pudo abrir el almacen del servidor")
        return err
    paso("Almacen del servidor accesible; copiando...")
    cmd = [binary, "backup", *targets, "--tag", "octopus-agent", "--host", agent_host(cfg), "--json",
           *opciones_backup(cfg)]
    result = run_cmd(cmd, env=env)
    if result.returncode not in (0, 3) and "lock" in (result.stderr or "").lower():
        # una copia anterior se corto (apagon, reinicio...) y dejo el almacen bloqueado: se quitan los bloqueos
        # viejos (no se borra ninguna copia) y se repite una vez
        paso("El almacen estaba bloqueado por una copia que se corto: se quita el bloqueo y se repite")
        run_cmd([binary, "unlock"], env=env, timeout=300)
        result = run_cmd(cmd, env=env)
    # restic devuelve 3 cuando la copia SE HA HECHO pero algun archivo no se pudo leer (en uso en Windows,
    # protegido por la privacidad de macOS...): es una copia valida, con aviso.
    incompleta = result.returncode == 3
    if result.returncode != 0 and not incompleta:
        log(f"Backup fallido: {result.stderr.strip()}")
        return {"status": "error", "message": result.stderr or result.stdout, "paths": targets}
    snapshot_id = ""
    for line in (result.stdout or "").splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if data.get("message_type") == "summary":
            snapshot_id = data.get("snapshot_id", "")
    if incompleta:
        omitidos = [l for l in (result.stderr or "").splitlines() if l.strip()][:20]
        log(f"Backup OK con avisos snapshot={snapshot_id}: {len(omitidos)} archivos no se pudieron leer")
        _apuntar_copia()
        return {"status": "success", "snapshot_id": snapshot_id, "paths": targets, "host": agent_host(cfg),
                "aviso": "Algunos archivos no se pudieron leer (en uso o sin permiso)", "omitidos": omitidos}
    log(f"Backup OK snapshot={snapshot_id} rutas={targets}")
    _apuntar_copia()
    return {"status": "success", "snapshot_id": snapshot_id, "paths": targets, "host": agent_host(cfg)}


def listar_snapshots(cfg: dict) -> dict:
    env = restic_env(cfg)
    result = run_cmd([restic_bin(), "snapshots", "--json", "--host", agent_host(cfg)], env=env, timeout=300)
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr or result.stdout}
    try:
        snaps = json.loads(result.stdout or "[]") or []
    except ValueError:
        snaps = []
    return {"status": "success", "host": agent_host(cfg), "count": len(snaps),
            "snapshots": [{"id": s.get("short_id"), "time": s.get("time"), "paths": s.get("paths")} for s in snaps]}


def listar_archivos(cfg: dict, snapshot: str, path: str) -> dict:
    """Contenido de una carpeta dentro de una copia (para el explorador del panel)."""
    if not path_protegida(cfg, path):
        return {"status": "error", "message": "Esa carpeta no forma parte de las copias de este equipo"}
    env = restic_env(cfg)
    folder = snapshot_path(path).rstrip("/") or "/"
    cmd = [restic_bin(), "ls", "--json", snapshot, folder]
    if snapshot == "latest":
        cmd[3:3] = ["--host", agent_host(cfg)]
    result = run_cmd(cmd, env=env, timeout=300)
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr or result.stdout}
    items = []
    for line in (result.stdout or "").splitlines():
        try:
            node = json.loads(line)
        except ValueError:
            continue
        if node.get("struct_type") != "node":
            continue
        npath = node.get("path", "")
        parent = npath.rsplit("/", 1)[0] or "/"
        if parent != folder:
            continue
        items.append({"name": node.get("name"), "type": node.get("type"), "size": node.get("size", 0),
                      "mtime": node.get("mtime"), "path": npath})
    items.sort(key=lambda x: (x["type"] != "dir", (x["name"] or "").lower()))
    return {"status": "success", "path": path, "items": items}


def restaurar_backup(cfg: dict, target: str = "/", snapshot: str = "latest") -> dict:
    """Restauracion completa del ultimo snapshot DE ESTA MAQUINA."""
    log(f"Restauracion completa snapshot={snapshot} target={target}")
    env = restic_env(cfg)
    cmd = [restic_bin(), "restore", snapshot, "--target", target]
    if snapshot == "latest":
        cmd += ["--host", agent_host(cfg)]
    suspender_detector(600)
    result = run_cmd(cmd, env=env)
    aceptar_senuelos_actuales()
    if result.returncode != 0:
        return {"status": "error", "message": result.stderr or result.stdout}
    return {"status": "success", "output": result.stdout}


def restaurar_archivo(cfg: dict, path_archivo: str, snapshot: str = "latest", destino: str = "original") -> dict:
    """Restaura un archivo o carpeta. destino='original' sustituye la version actual;
    destino='aparte' lo deja al lado con el sufijo .restaurado-AAAAMMDD-HHMM."""
    log(f"Restauracion selectiva: {path_archivo} (destino={destino})")
    suspender_detector(60)
    if not path_protegida(cfg, path_archivo):
        return {"status": "error", "message": "Esa ruta no forma parte de las copias de este equipo"}
    if destino != "aparte" and not en_rutas_normales(cfg, path_archivo):
        destino = "aparte"   # desde la copia completa nunca se sobrescribe nada del sistema: se deja al lado
    env = restic_env(cfg)
    source = os.path.abspath(path_archivo)
    in_snapshot = snapshot_path(source)
    original = source
    if destino == "aparte":
        original = source.rstrip("/\\") + ".restaurado-" + datetime.now().strftime("%Y%m%d-%H%M")
    with tempfile.TemporaryDirectory(prefix="octopus_restore_") as tmp:
        cmd = [restic_bin(), "restore", snapshot, "--target", tmp, "--include", in_snapshot]
        if snapshot == "latest":
            cmd += ["--host", agent_host(cfg)]
        result = run_cmd(cmd, env=env)
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr or result.stdout}
        restored = Path(tmp) / in_snapshot.lstrip("/")
        if not restored.exists():
            return {"status": "error", "message": f"{path_archivo} no esta en el snapshot {snapshot}"}
        if restored.is_dir():
            shutil.copytree(restored, original, dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(original), exist_ok=True)
            shutil.copy2(restored, original)
    aceptar_senuelos_actuales()
    log(f"Restaurado: {original}")
    return {"status": "success", "file": original}


def despachar(cfg: dict, metodo: str, ruta: str, datos: dict | None = None) -> dict:
    """Ejecuta una orden (llegue por la cola del servidor o por el puerto local)."""
    datos = datos or {}
    if metodo == "GET":
        if ruta in ("/health", "/"):
            return {"status": "ok", "agent": "octopus", "os": SYSTEM, "host": agent_host(cfg), "version": AGENT_VERSION}
        if ruta == "/snapshots":
            return listar_snapshots(cfg)
        if ruta.startswith("/ls?"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(ruta).query)
            return listar_archivos(cfg, q.get("snapshot", ["latest"])[0], q.get("path", ["/"])[0])
        if ruta == "/estado":
            return {"status": "success", "aislado": esta_aislado(), "detector": bool(cfg.get("detector", True))}
        if ruta == "/info":
            return {"status": "success", **info_equipo(cfg)}
        return {"status": "error", "message": "Orden desconocida"}
    log(f"Orden {ruta}")
    if ruta == "/webhook/aislamiento":
        return aislar_maquina(cfg)
    if ruta == "/webhook/reincorporacion":
        return reincorporar_red()
    if ruta == "/webhook/copia-completa":
        if not AJUSTES_SERVIDOR.get("copia_completa"):
            return {"status": "error", "message": "La copia completa no esta activada para este equipo"}
        return copia_completa(cfg)
    if ruta in ("/webhook/backup-forense", "/webhook/backup"):
        return backup_forense(cfg, datos.get("paths") or datos.get("path"))
    if ruta == "/webhook/forense":
        return copia_forense(cfg, str(datos.get("incidente") or datetime.now().strftime("%Y%m%d%H%M%S")))
    if ruta == "/webhook/restaurar-limpio":
        if not datos.get("snapshot"):
            return {"status": "error", "message": "Falta la copia (snapshot)"}
        return restaurar_limpio(cfg, str(datos["snapshot"]))
    if ruta == "/webhook/aviso":
        return mostrar_aviso(str(datos.get("titulo", "Aviso de seguridad"))[:200], str(datos.get("mensaje", ""))[:2000])
    if ruta == "/webhook/eliminar":
        rutas = datos.get("rutas") or []
        return eliminar_amenaza(cfg, rutas if isinstance(rutas, list) else [rutas])
    if ruta == "/webhook/quitar-aviso":
        return quitar_aviso()
    if ruta == "/webhook/restauracion":
        return restaurar_backup(cfg, datos.get("target", "/"), datos.get("snapshot", "latest"))
    if ruta == "/webhook/restaurar-archivo":
        archivo = datos.get("archivo") or datos.get("path")
        if not archivo:
            return {"status": "error", "message": "Falta parametro archivo"}
        return restaurar_archivo(cfg, archivo, datos.get("snapshot", "latest"), datos.get("destino", "original"))
    return {"status": "error", "message": "Orden desconocida"}


def info_equipo(cfg: dict) -> dict:
    return {"host": agent_host(cfg), "os": SYSTEM, "os_version": platform.platform(), "version": AGENT_VERSION,
            "backup_paths": backup_paths(cfg), "aislado": esta_aislado()}


class ZeroTouchHandler(http.server.BaseHTTPRequestHandler):
    """Puerto local (127.0.0.1): comprobaciones del instalador y uso desde el propio equipo."""

    def send_json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _permitido(self, cfg: dict, abierto: bool = False) -> bool:
        if not source_allowed(self, cfg):
            self.send_json({"status": "error", "message": "Origen no permitido"}, 403)
            return False
        if not abierto and not authorized(self, cfg):
            self.send_json({"status": "error", "message": "No autorizado"}, 401)
            return False
        return True

    def do_GET(self) -> None:
        cfg = load_config()
        if not self._permitido(cfg, abierto=self.path in ("/health", "/")):
            return
        res = despachar(cfg, "GET", self.path)
        self.send_json(res, 404 if res.get("message") == "Orden desconocida" else 200)

    def do_POST(self) -> None:
        cfg = load_config()
        if not self._permitido(cfg):
            return
        length = min(int(self.headers.get("Content-Length") or 0), 65536)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {}
        res = despachar(cfg, "POST", self.path, data)
        self.send_json(res, 200 if res.get("status") == "success" else 500)

    def log_message(self, fmt: str, *args) -> None:
        return


def _ejecutar_orden(orden: dict) -> None:
    cfg = load_config()
    try:
        res = despachar(cfg, orden.get("metodo", "GET"), orden.get("ruta", ""), orden.get("datos"))
    except Exception as exc:  # una orden fallida nunca debe tumbar el agente
        res = {"status": "error", "message": f"Error en el equipo: {exc}"}
    for intento in range(10):
        try:
            _https(load_config(), "/api/agente/resultado", {"id": orden.get("id"), "resultado": res}, timeout=60)
            return
        except Exception:
            time.sleep(min(2 * (intento + 1), 30))
    log(f"No se pudo entregar el resultado de la orden {orden.get('ruta')}")


def bucle_ordenes() -> None:
    """Pregunta al servidor cada pocos segundos si hay ordenes. Asi el equipo no necesita puertos abiertos."""
    log("Conexion con el servidor: el agente recoge sus ordenes por HTTPS")
    espera, fallos, ultimo_info, en_curso = 2.0, 0, 0.0, set()
    while True:
        cfg = load_config()
        if not cfg.get("agent_token") or not (cfg.get("panel_url") or cfg.get("servidor")):
            log("Falta la clave o la direccion del servidor en la configuracion; reintento en 60 s")
            time.sleep(60)
            continue
        datos = {"version": AGENT_VERSION}
        if time.time() - ultimo_info > 300:
            datos["info"] = info_equipo(cfg)
        try:
            r = _https(cfg, "/api/agente/ordenes", datos, timeout=30)
            if isinstance(r.get("ajustes"), dict):
                AJUSTES_SERVIDOR.clear()
                AJUSTES_SERVIDOR.update(r["ajustes"])
            if "info" in datos:
                ultimo_info = time.time()
            if fallos:
                log("Conexion con el servidor recuperada")
            fallos = 0
            for orden in r.get("ordenes", []):
                if orden.get("id") in en_curso:
                    continue
                en_curso.add(orden.get("id"))
                threading.Thread(target=_ejecutar_orden, args=(orden,), daemon=True).start()
            if len(en_curso) > 1000:
                en_curso.clear()
            espera = float(r.get("espera", 2))
            m = r.get("monitor")
            if isinstance(m, dict):
                antes = dict(MONITOR_ESTADO)
                MONITOR_ESTADO.update(activa=bool(m.get("activa")), intervalo=int(m.get("intervalo") or 60))
                if antes.get("activa") != MONITOR_ESTADO["activa"] or MONITOR_ESTADO["intervalo"] < antes.get("intervalo", 60):
                    MONITOR_EVENTO.set()     # despierta a la monitorizacion ya (no espera a su siguiente vuelta)
        except Exception as exc:
            fallos += 1
            if fallos in (1, 5) or fallos % 60 == 0:
                log(f"No se puede contactar con el servidor ({exc.__class__.__name__}: {exc}); se reintenta")
            espera = min(5 * fallos, 60)
        time.sleep(max(espera, 0.5))


MONITOR_ESTADO: dict = {}
MONITOR_EVENTO = threading.Event()


def monitor_loop() -> None:
    """Monitorizacion (solo si esta activada para este equipo en el panel). El servidor dice cada cuanto mandar:
    unos segundos mientras alguien mira la pantalla del equipo, cada minuto si no, y nada si esta desactivada."""
    try:
        import octopus_monitor
    except ImportError:
        log("Monitorizacion no disponible (falta octopus_monitor.py junto al agente)")
        return
    mon, espera, activa = None, 30, False
    while True:
        MONITOR_EVENTO.wait(espera)
        MONITOR_EVENTO.clear()
        if MONITOR_ESTADO:
            activa = MONITOR_ESTADO.get("activa", activa)
        try:
            cfg = load_config()
            nuevo = activa and mon is None
            if activa:
                mon = mon or octopus_monitor.Monitor()
                datos = mon.muestra()
            else:
                datos = {"t": time.time(), "inactivo": True}
            r = _https(cfg, "/api/agente/metricas", datos, timeout=20)
            activa = bool(r.get("activa"))
            espera = max(2, min(600, int(r.get("intervalo") or (60 if activa else 300))))
            if nuevo:     # recien activada: la segunda muestra enseguida (las velocidades necesitan dos)
                espera = 2
            if not activa:
                mon = None
        except Exception as exc:  # sin conexion: se reintenta sin molestar
            espera = 120
            if "urlopen" not in str(exc):
                log(f"Monitorizacion: {exc.__class__.__name__}")


def main() -> None:
    log("Iniciando agente OCTOPUS")
    log(f"Directorio: {app_dir()}")
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    # El puerto local solo escucha en 127.0.0.1: las ordenes del servidor llegan por bucle_ordenes (HTTPS saliente)
    threading.Thread(target=detector_loop, daemon=True).start()
    threading.Thread(target=bucle_ordenes, daemon=True).start()
    threading.Thread(target=copia_atrasada_loop, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()
    binds = load_config().get("bind_addresses") or ["127.0.0.1"]

    def escuchar(addr: str) -> None:
        # la IP del tunel puede no existir aun al arrancar el equipo: se reintenta hasta que aparezca
        espera = 2
        while True:
            try:
                srv = socketserver.ThreadingTCPServer((addr, PORT), ZeroTouchHandler)
                log(f"Escuchando en {addr}:{PORT}")
                srv.serve_forever()
                return
            except OSError as exc:
                log(f"Aun no se puede escuchar en {addr}:{PORT} ({exc}); reintento en {espera} s")
                time.sleep(espera)
                espera = min(espera * 2, 60)

    hilos = [threading.Thread(target=escuchar, args=(a,), daemon=True) for a in binds]
    for h in hilos:
        h.start()
    while True:
        time.sleep(3600)


def copia_programada() -> int:
    """`zerotouch_agent.py --copia`: copia de seguridad diaria (la lanza cron o el Programador de tareas)."""
    cfg = load_config()
    if esta_aislado():
        log("Copia programada omitida: el equipo esta aislado por un incidente")
        return 0
    try:  # limite de velocidad elegido en el panel (si no se puede preguntar, se copia sin limite)
        r = _https(cfg, "/api/agente/ajustes", {}, timeout=15)
        if isinstance(r.get("ajustes"), dict):
            AJUSTES_SERVIDOR.update(r["ajustes"])
    except Exception as exc:
        log(f"No se pudieron leer los ajustes del servidor ({exc.__class__.__name__}); copia sin limite de velocidad")
    res = backup_forense(cfg)
    log(f"Copia programada: {res.get('status')} {res.get('message', '')}".strip())
    if toca_copia_completa():
        rc = copia_completa(cfg)
        log(f"Copia completa programada: {rc.get('status')} {rc.get('message', '')}".strip())
    return 0 if res.get("status") == "success" else 1


if __name__ == "__main__":
    if "--copia" in sys.argv:
        sys.exit(copia_programada())
    main()
