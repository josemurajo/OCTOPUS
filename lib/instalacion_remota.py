"""
OCTOPUS Zero-Touch - Instalacion a distancia desde el panel (Linux y Mac, por SSH).

El administrador escribe UNA vez la IP, el usuario y la contrasena del equipo. El servidor:
  1. entra por SSH (con su clave si ya la tiene; si no, con la contrasena)
  2. copia el mismo instalador que se descarga en el panel y lo ejecuta con sudo
  3. deja autorizada la clave SSH del servidor (y, si se pide, desactiva el acceso con contrasena)
  4. espera a que el agente se conecte

La contrasena nunca se guarda ni se escribe en ningun registro: viaja por la entrada estandar de ssh/sudo
y por la variable SSHPASS del proceso hijo, y se olvida al terminar.
"""
from __future__ import annotations

import os
import secrets
import shlex
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

CLAVE = Path("/root/.ssh/octopus_ed25519")
SSH_OPC = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
           "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=6"]

# Se ejecuta EN EL EQUIPO como root (sudo). Argumentos: <carpeta> <usuario> <so> <solo_clave 0|1>
REMOTO = r'''
set -u
DIR="$1"; USUARIO="$2"; SO="$3"; SOLO_CLAVE="$4"
cd "$DIR" || exit 10
if command -v unzip >/dev/null 2>&1; then unzip -oq octopus.zip; else python3 -m zipfile -e octopus.zip .; fi || { echo "ERROR: no se pudo descomprimir"; exit 11; }
# clave SSH del servidor para el mantenimiento sin contrasena
CASA=$(eval echo "~$USUARIO")
mkdir -p "$CASA/.ssh" && chmod 700 "$CASA/.ssh"
touch "$CASA/.ssh/authorized_keys"
grep -qF "$(cat servidor.pub)" "$CASA/.ssh/authorized_keys" || cat servidor.pub >> "$CASA/.ssh/authorized_keys"
chmod 600 "$CASA/.ssh/authorized_keys"
chown -R "$USUARIO" "$CASA/.ssh" 2>/dev/null || true
echo "PASO clave del servidor autorizada"
if [ "$SO" = macos ]; then
    bash ./INSTALAR.command --sin-preguntas; RC=$?
else
    bash ./instalar_linux.sh; RC=$?
fi
if [ $RC -eq 0 ] && [ "$SOLO_CLAVE" = 1 ] && [ "$SO" = linux ]; then
    mkdir -p /etc/ssh/sshd_config.d
    printf '# OCTOPUS: solo acceso con clave\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nChallengeResponseAuthentication no\n' > /etc/ssh/sshd_config.d/00-octopus.conf
    grep -q '^Include /etc/ssh/sshd_config.d' /etc/ssh/sshd_config || sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config
    sed -i 's/^PasswordAuthentication[[:space:]]\+yes/#PasswordAuthentication yes  # desactivado por OCTOPUS/' /etc/ssh/sshd_config
    if "$(command -v sshd || echo /usr/sbin/sshd)" -t 2>/dev/null; then
        (systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null) && echo "PASO acceso SSH solo con clave"
    else
        rm -f /etc/ssh/sshd_config.d/00-octopus.conf; echo "AVISO: no se cambio SSH (configuracion no valida)"
    fi
fi
cd / && rm -rf "$DIR"
exit $RC
'''


def _clave_servidor() -> None:
    if not CLAVE.is_file():
        CLAVE.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(CLAVE.parent, 0o700)
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "octopus-servidor", "-f", str(CLAVE), "-q"],
                       check=True, capture_output=True, timeout=60)


def _con_clave(destino: str) -> bool:
    r = subprocess.run(["ssh", "-i", str(CLAVE), "-o", "BatchMode=yes", *SSH_OPC, destino, "true"],
                       capture_output=True, timeout=40)
    return r.returncode == 0


def _cmd(base: list[str], usar_clave: bool, password: str) -> tuple[list[str], dict]:
    env = dict(os.environ)
    if usar_clave:
        return [base[0], "-i", str(CLAVE), "-o", "BatchMode=yes", *base[1:]], env
    env["SSHPASS"] = password
    return ["sshpass", "-e", base[0], "-o", "PubkeyAuthentication=no", "-o", "PreferredAuthentications=password,keyboard-interactive",
            *base[1:]], env


def _limpiar(texto: str, password: str) -> str:
    """Nunca devolver la contrasena en un mensaje (por si algun programa la repitiera)."""
    return (texto or "").replace(password, "********") if password else (texto or "")


def instalar(equipo: str, so: str, ip: str, usuario: str, password: str, paquete: bytes, solo_clave: bool,
             paso=lambda texto: None, en_linea=lambda: False) -> tuple[bool, str]:
    """Hace la instalacion. Devuelve (ok, mensaje). `paso` informa del progreso; `en_linea` dice si ya conecto."""
    if so == "windows":
        return instalar_windows(equipo, ip, usuario, password, paquete, paso, en_linea)
    if so not in ("linux", "macos"):
        return False, "Sistema no reconocido: elige Windows, Linux o Mac."
    _clave_servidor()
    destino = f"{usuario}@{ip}"
    paso(f"Conectando con {ip}...")
    usar_clave = _con_clave(destino)
    if not usar_clave and not password:
        return False, "Hace falta la contrasena del equipo (el servidor aun no tiene acceso con su clave)."
    carpeta = f"/tmp/octopus_inst_{secrets.token_hex(6)}"
    with tempfile.TemporaryDirectory(prefix="octopus_remoto_") as tmp:
        t = Path(tmp)
        (t / "octopus.zip").write_bytes(paquete)
        (t / "servidor.pub").write_text(Path(str(CLAVE) + ".pub").read_text())
        (t / "remoto.sh").write_text(REMOTO)
        for f in t.iterdir():
            os.chmod(f, 0o600)
        cmd, env = _cmd(["ssh", *SSH_OPC, destino, f"mkdir -m 700 {carpeta}"], usar_clave, password)
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            err = _limpiar(r.stderr or r.stdout, password).strip()
            if "Permission denied" in err or r.returncode == 5:
                return False, "Usuario o contrasena incorrectos (o el equipo no permite entrar por SSH con contrasena)."
            if "timed out" in err or "No route" in err or "refused" in err:
                return False, f"No se puede llegar a {ip} por SSH (puerto 22). ¿Esta encendido y con SSH activado? {err[-150:]}"
            return False, f"No se pudo entrar en el equipo: {err[-300:]}"
        paso("Copiando el instalador al equipo...")
        cmd, env = _cmd(["scp", *SSH_OPC, str(t / "octopus.zip"), str(t / "servidor.pub"), str(t / "remoto.sh"),
                         f"{destino}:{carpeta}/"], usar_clave, password)
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, "No se pudo copiar el instalador: " + _limpiar(r.stderr, password)[-300:]
    paso("Instalando OCTOPUS en el equipo (1-5 minutos)...")
    remoto = (f"sudo -S -p '' bash {carpeta}/remoto.sh {carpeta} {shlex.quote(usuario)} {so} {1 if solo_clave else 0}")
    cmd, env = _cmd(["ssh", *SSH_OPC, destino, remoto], usar_clave, password)
    # la contrasena de sudo va por la entrada estandar (no aparece en la lista de procesos del equipo)
    r = subprocess.run(cmd, env=env, input=(password + "\n") if password else "", capture_output=True, text=True,
                       timeout=1800)
    salida = _limpiar((r.stdout or "") + "\n" + (r.stderr or ""), password)
    if r.returncode != 0:
        if "incorrect password" in salida.lower() or "contraseña incorrecta" in salida.lower() or "sorry, try again" in salida.lower():
            return False, "La contrasena no vale para sudo (el usuario debe ser administrador del equipo)."
        lineas = [l for l in salida.splitlines() if l.strip()]
        return False, "La instalacion fallo: " + " | ".join(lineas[-4:])[-400:]
    paso("Instalado. Esperando a que el equipo se conecte...")
    for _ in range(45):
        if en_linea():
            como = "con la clave del servidor" if usar_clave else "con la contrasena (ya no hara falta)"
            extra = " El acceso SSH queda solo con la clave del servidor." if "solo con clave" in salida else ""
            return True, f"{equipo} instalado y conectado (se entro {como}).{extra}"
        time.sleep(2)
    return False, "Se instalo, pero el equipo no se ha conectado al servidor. Revisa que llega a este servidor (puerto 8080)."


def instalar_windows(equipo: str, ip: str, usuario: str, password: str, paquete: bytes, paso, en_linea) -> tuple[bool, str]:
    """Windows 10/11 o Server con el «Servidor OpenSSH» activado: se copia el mismo instalador del panel y se ejecuta.
    El usuario tiene que ser administrador del equipo (por SSH, Windows le da permisos completos)."""
    if not password:
        return False, "Hace falta la contrasena de un administrador del equipo Windows."
    destino = f"{usuario}@{ip}"
    carpeta_win = f"C:\\Windows\\Temp\\octopus_inst_{secrets.token_hex(6)}"
    carpeta_scp = carpeta_win.replace("\\", "/")
    paso(f"Conectando con {ip} (Windows, SSH)...")
    ps = (f"New-Item -ItemType Directory -Force -Path '{carpeta_win}' | Out-Null; "
          f"$a=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent())"
          f".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator); Write-Output \"ADMIN=$a\"")
    cmd, env = _cmd(["ssh", *SSH_OPC, destino, f'powershell -NoProfile -NonInteractive -Command "{ps}"'], False, password)
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=90)
    salida = _limpiar((r.stdout or "") + (r.stderr or ""), password)
    if r.returncode != 0:
        if "Permission denied" in salida or r.returncode == 5:
            return False, "Usuario o contrasena incorrectos (en Windows: usa EQUIPO\\usuario o el usuario de la cuenta local)."
        if "timed out" in salida or "refused" in salida or "No route" in salida:
            return False, (f"No se puede llegar a {ip} por SSH. En Windows hay que activar el «Servidor OpenSSH» "
                           f"(Configuracion > Sistema > Caracteristicas opcionales) o usar el instalador de doble clic.")
        return False, f"No se pudo entrar en el equipo Windows: {salida[-300:]}"
    if "ADMIN=False" in salida:
        return False, "Ese usuario no es administrador del equipo Windows. Usa una cuenta de administrador."
    paso("Copiando el instalador al equipo...")
    with tempfile.TemporaryDirectory(prefix="octopus_remoto_") as tmp:
        z = Path(tmp) / "octopus.zip"
        z.write_bytes(paquete)
        os.chmod(z, 0o600)
        cmd, env = _cmd(["scp", *SSH_OPC, str(z), f"{destino}:{carpeta_scp}/octopus.zip"], False, password)
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, "No se pudo copiar el instalador: " + _limpiar(r.stderr, password)[-300:]
    paso("Instalando OCTOPUS en el equipo Windows (2-8 minutos)...")
    ps = (f"$ProgressPreference='SilentlyContinue'; Expand-Archive -Force '{carpeta_win}\\octopus.zip' '{carpeta_win}\\inst'; "
          f"& powershell -NoProfile -ExecutionPolicy Bypass -File '{carpeta_win}\\inst\\instalar_windows.ps1' 2>&1 | "
          f"ForEach-Object {{ \"$_\" }}; $rc=$LASTEXITCODE; Remove-Item -Recurse -Force '{carpeta_win}' -ErrorAction SilentlyContinue; exit $rc")
    cmd, env = _cmd(["ssh", *SSH_OPC, destino, f'powershell -NoProfile -NonInteractive -Command "{ps}"'], False, password)
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=1800)
    salida = _limpiar((r.stdout or "") + "\n" + (r.stderr or ""), password)
    if r.returncode != 0:
        lineas = [l for l in salida.splitlines() if l.strip()]
        return False, "La instalacion en Windows fallo: " + " | ".join(lineas[-4:])[-400:]
    paso("Instalado. Esperando a que el equipo se conecte...")
    for _ in range(60):
        if en_linea():
            return True, f"{equipo} instalado y conectado."
        time.sleep(2)
    return False, "Se instalo, pero el equipo no se ha conectado al servidor. Revisa que llega a este servidor (puerto 8080)."


# ---------------------------------------------------------------- trabajo en segundo plano (lo usa el panel)
def lanzar(system: dict, ip: str, usuario: str, password: str, solo_clave: bool, jobs: dict, lock: threading.Lock,
           hacer_paquete, en_linea, al_terminar=None) -> str:
    job_id = uuid.uuid4().hex[:10]
    with lock:
        jobs[job_id] = {"id": job_id, "system_id": system["id"], "equipo": system["hostname"], "tipo": "instalacion",
                        "estado": "en_curso", "mensaje": "Preparando la instalacion...",
                        "inicio": datetime.now(timezone.utc), "fin": None}

    def paso(texto):
        with lock:
            jobs[job_id]["mensaje"] = texto

    def _run():
        pwd = password
        try:
            ok, msg = instalar(system["hostname"], system["os_family"], ip, usuario, pwd, hacer_paquete(), solo_clave,
                               paso=paso, en_linea=lambda: en_linea(system["hostname"]))
        except Exception as exc:  # nunca dejar el trabajo colgado
            ok, msg = False, f"Error inesperado: {_limpiar(str(exc), pwd)}"
        finally:
            pwd = None
        with lock:
            jobs[job_id].update(estado="ok" if ok else "error", mensaje=msg, fin=datetime.now(timezone.utc))
        if al_terminar:
            try:
                al_terminar(system, ok, msg)
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()
    return job_id
