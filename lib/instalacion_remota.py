"""
OCTOPUS Zero-Touch - Instalacion a distancia desde el panel (Linux y Mac, por SSH).

El administrador escribe UNA vez la IP, el usuario y la contrasena del equipo. El servidor:
  1. entra por SSH (con su clave si ya la tiene; si no, con la contrasena)
  2. copia el mismo instalador que se descarga en el panel y lo ejecuta con sudo
  3. deja autorizada la clave SSH del servidor (y, si se pide, desactiva el acceso con contrasena)
  4. espera a que el agente se conecte

La contrasena nunca se guarda ni se escribe en ningun registro: solo viaja dentro de la conexion SSH cifrada
(para entrar y por la entrada estandar de sudo) y se olvida al terminar.

La conexion se hace con paramiko (SSH escrito en Python): funciona igual con el servidor en Linux, Mac o Windows,
sin necesitar los programas ssh/scp/sshpass.
"""
from __future__ import annotations

import os
import secrets
import shlex
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# En el contenedor /data/ssh es la misma carpeta que /root/.ssh (la clave de siempre)
CLAVE = Path(os.environ.get("OCTOPUS_DATA", "/data")) / "ssh" / "octopus_ed25519"

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
    """Clave SSH propia del servidor (ed25519), para volver a entrar en los equipos sin contrasena."""
    if CLAVE.is_file():
        return
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric import ed25519
    k = ed25519.Ed25519PrivateKey.generate()
    CLAVE.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CLAVE.parent, 0o700)
    except OSError:
        pass
    for ruta, datos, modo in (
            (CLAVE, k.private_bytes(s.Encoding.PEM, s.PrivateFormat.OpenSSH, s.NoEncryption()), 0o600),
            (Path(str(CLAVE) + ".pub"), k.public_key().public_bytes(s.Encoding.OpenSSH, s.PublicFormat.OpenSSH)
             + b" octopus-servidor\n", 0o644)):
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, modo)
        with os.fdopen(fd, "wb") as fh:
            fh.write(datos)


class ErrorSSH(Exception):
    """Fallo al conectar, con un mensaje ya explicado para el panel."""


class _Conexion:
    """Una conexion SSH al equipo (con la clave del servidor o con usuario y contrasena)."""

    def __init__(self, ip: str, usuario: str, password: str | None = None, usar_clave: bool = False):
        import paramiko
        self.c = paramiko.SSHClient()
        # igual que antes (StrictHostKeyChecking=no): es la primera vez que se entra en un equipo de la oficina
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = dict(hostname=ip, port=int(os.environ.get("OCTOPUS_SSH_PUERTO", "22")), username=usuario, timeout=15, banner_timeout=20, auth_timeout=25,
                  allow_agent=False, look_for_keys=False)
        if usar_clave:
            kw["pkey"] = paramiko.Ed25519Key.from_private_key_file(str(CLAVE))
        else:
            kw["password"] = password or ""
        try:
            self.c.connect(**kw)
        except paramiko.AuthenticationException as exc:
            self.c.close()
            raise ErrorSSH("auth") from exc
        except (socket.timeout, TimeoutError, paramiko.ssh_exception.NoValidConnectionsError, OSError) as exc:
            self.c.close()
            raise ErrorSSH(f"red: {exc.__class__.__name__} {exc}") from exc
        except paramiko.SSHException as exc:
            self.c.close()
            raise ErrorSSH(f"ssh: {exc}") from exc
        self.c.get_transport().set_keepalive(10)

    def ejecutar(self, comando: str, entrada: str = "", timeout: int = 60) -> tuple[int, str]:
        """Ejecuta un comando y devuelve (codigo, salida+errores)."""
        canal = self.c.get_transport().open_session()
        canal.set_combine_stderr(True)
        canal.settimeout(timeout)
        canal.exec_command(comando)
        if entrada:
            canal.sendall(entrada.encode("utf-8"))
        canal.shutdown_write()
        trozos, fin = [], time.time() + timeout
        try:
            while True:
                d = canal.recv(65536)
                if not d:
                    break
                trozos.append(d)
                if time.time() > fin:
                    raise socket.timeout()
        except socket.timeout:
            canal.close()
            return 124, b"".join(trozos).decode("utf-8", "replace") + "\n(tiempo agotado)"
        codigo = canal.recv_exit_status()
        canal.close()
        return codigo, b"".join(trozos).decode("utf-8", "replace")

    def subir(self, datos: bytes, remoto: str, modo: int | None = 0o600) -> None:
        sftp = self.c.open_sftp()
        try:
            with sftp.open(remoto, "wb") as fh:
                fh.write(datos)
            if modo is not None:
                try:
                    sftp.chmod(remoto, modo)
                except OSError:
                    pass
        finally:
            sftp.close()

    def cerrar(self) -> None:
        self.c.close()


def _con_clave(ip: str, usuario: str) -> bool:
    try:
        _Conexion(ip, usuario, usar_clave=True).cerrar()
        return True
    except Exception:
        return False


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
    paso(f"Conectando con {ip}...")
    usar_clave = _con_clave(ip, usuario)
    if not usar_clave and not password:
        return False, "Hace falta la contrasena del equipo (el servidor aun no tiene acceso con su clave)."
    try:
        con = _Conexion(ip, usuario, password, usar_clave)
    except ErrorSSH as exc:
        if str(exc) == "auth":
            return False, "Usuario o contrasena incorrectos (o el equipo no permite entrar por SSH con contrasena)."
        if str(exc).startswith("red"):
            return False, (f"No se puede llegar a {ip} por SSH (puerto 22). ¿Esta encendido y con SSH activado? "
                           f"{_limpiar(str(exc), password)[-150:]}")
        return False, f"No se pudo entrar en el equipo: {_limpiar(str(exc), password)[-300:]}"
    try:
        carpeta = f"/tmp/octopus_inst_{secrets.token_hex(6)}"
        rc, salida = con.ejecutar(f"mkdir -m 700 {carpeta}")
        if rc != 0:
            return False, f"No se pudo preparar el equipo: {_limpiar(salida, password)[-300:]}"
        paso("Copiando el instalador al equipo...")
        try:
            con.subir(paquete, f"{carpeta}/octopus.zip")
            con.subir(Path(str(CLAVE) + ".pub").read_bytes(), f"{carpeta}/servidor.pub")
            con.subir(REMOTO.encode("utf-8"), f"{carpeta}/remoto.sh")
        except Exception as exc:
            return False, "No se pudo copiar el instalador: " + _limpiar(str(exc), password)[-300:]
        paso("Instalando OCTOPUS en el equipo (1-5 minutos)...")
        remoto = f"sudo -S -p '' bash {carpeta}/remoto.sh {carpeta} {shlex.quote(usuario)} {so} {1 if solo_clave else 0}"
        # la contrasena de sudo va por la entrada estandar (no aparece en la lista de procesos del equipo)
        rc, salida = con.ejecutar(remoto, entrada=(password + "\n") if password else "", timeout=1800)
    finally:
        con.cerrar()
    salida = _limpiar(salida, password)
    if rc != 0:
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
    carpeta_win = f"C:\\Windows\\Temp\\octopus_inst_{secrets.token_hex(6)}"
    carpeta_sftp = "/" + carpeta_win.replace("\\", "/")     # el SFTP de Windows usa /C:/Windows/...
    paso(f"Conectando con {ip} (Windows, SSH)...")
    try:
        con = _Conexion(ip, usuario, password)
    except ErrorSSH as exc:
        if str(exc) == "auth":
            return False, "Usuario o contrasena incorrectos (en Windows: usa EQUIPO\\usuario o el usuario de la cuenta local)."
        if str(exc).startswith("red"):
            return False, (f"No se puede llegar a {ip} por SSH. En Windows hay que activar el «Servidor OpenSSH» "
                           f"(Configuracion > Sistema > Caracteristicas opcionales) o usar el instalador de doble clic.")
        return False, f"No se pudo entrar en el equipo Windows: {_limpiar(str(exc), password)[-300:]}"
    try:
        ps = (f"New-Item -ItemType Directory -Force -Path '{carpeta_win}' | Out-Null; "
              f"$a=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent())"
              f".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator); Write-Output \"ADMIN=$a\"")
        rc, salida = con.ejecutar(f'powershell -NoProfile -NonInteractive -Command "{ps}"', timeout=90)
        salida = _limpiar(salida, password)
        if rc != 0:
            return False, f"No se pudo preparar el equipo Windows: {salida[-300:]}"
        if "ADMIN=False" in salida:
            return False, "Ese usuario no es administrador del equipo Windows. Usa una cuenta de administrador."
        paso("Copiando el instalador al equipo...")
        try:
            con.subir(paquete, f"{carpeta_sftp}/octopus.zip", modo=None)
        except Exception as exc:
            return False, "No se pudo copiar el instalador: " + _limpiar(str(exc), password)[-300:]
        paso("Instalando OCTOPUS en el equipo Windows (2-8 minutos)...")
        ps = (f"$ProgressPreference='SilentlyContinue'; Expand-Archive -Force '{carpeta_win}\\octopus.zip' '{carpeta_win}\\inst'; "
              f"& powershell -NoProfile -ExecutionPolicy Bypass -File '{carpeta_win}\\inst\\instalar_windows.ps1' 2>&1 | "
              f"ForEach-Object {{ \"$_\" }}; $rc=$LASTEXITCODE; Remove-Item -Recurse -Force '{carpeta_win}' -ErrorAction SilentlyContinue; exit $rc")
        rc, salida = con.ejecutar(f'powershell -NoProfile -NonInteractive -Command "{ps}"', timeout=1800)
    finally:
        con.cerrar()
    salida = _limpiar(salida, password)
    if rc != 0:
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
