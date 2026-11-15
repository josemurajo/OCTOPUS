#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - USB DE RESCATE (el programa que arranca dentro del pendrive).

Para el día en que un ordenador ya no arranca. Se arranca desde el pendrive de rescate de OCTOPUS y:
  1. pide la dirección del servidor y el CÓDIGO que da el panel (ficha del equipo → «USB de rescate»);
  2. con el código, el servidor le manda (cifrado con ese código) cómo llegar a las copias de ESE equipo;
  3. deja elegir qué hacer:
     - «Dejar el ordenador como estaba» (Linux): borra el disco elegido y pone la copia completa del equipo, con su
       arranque (GRUB, UEFI y BIOS antiguas). Para Windows, la forma es la «imagen de disco» (USB de Windows).
     - «Sacar los archivos a un disco USB» (cualquier sistema): copia lo de la copia elegida a otro disco.

El código vale una sola vez y una hora. Sin el código, lo que viaja por la red no se puede leer.
Uso con menús: `octopus_rescate.py`.  Sin menús (lo usan las pruebas):
  octopus_rescate.py config  SERVIDOR CODIGO SALIDA.json
  octopus_rescate.py copias  CONFIG.json [--completas]
  octopus_rescate.py restaurar CONFIG.json COPIA /dev/DISCO --si-borrar-todo
  octopus_rescate.py sacar   CONFIG.json COPIA CARPETA
  octopus_rescate.py desplegar CONFIG.json COPIA /dev/DISCO NUEVO.json --si-borrar-todo
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# ----------------------------------------------------------------------------------------------- el código del panel
VERSION = "1.0"
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # sin 0/O, 1/I/L: que no haya dudas al copiarlo de la pantalla
LARGO = 12


def nuevo_codigo() -> str:
    c = "".join(secrets.choice(ALFABETO) for _ in range(LARGO))
    return "-".join(c[i:i + 4] for i in range(0, LARGO, 4))


def normalizar(codigo: str) -> str:
    c = re.sub(r"[\s-]", "", (codigo or "").upper())
    return c if len(c) == LARGO and all(x in ALFABETO for x in c) else ""


def _derivar(codigo: str, para: bytes) -> bytes:
    # scrypt: aunque alguien vea lo que viaja por la red, probar códigos uno a uno le llevaría siglos
    return hashlib.scrypt(normalizar(codigo).encode(), salt=b"octopus-rescate-" + para, n=2 ** 14, r=8, p=1,
                          dklen=32)


def identificador(codigo: str) -> str:
    """Lo que el USB manda al servidor para decir «vengo con este código» (no es el código)."""
    return _derivar(codigo, b"id").hex()


def clave(codigo: str) -> bytes:
    """La clave con la que viaja lo que manda el servidor (sale del código; el código no viaja nunca)."""
    return _derivar(codigo, b"clave")


def cifrar_con_clave(k: bytes, datos: dict) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(k).encrypt(nonce, json.dumps(datos).encode(), b"octopus-rescate")).decode()


def cifrar(codigo: str, datos: dict) -> str:
    return cifrar_con_clave(clave(codigo), datos)


def descifrar(codigo: str, texto: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(texto)
    return json.loads(AESGCM(_derivar(codigo, b"clave")).decrypt(raw[:12], raw[12:], b"octopus-rescate"))


def mi_mac() -> str:
    """La dirección física de la tarjeta de red por cable (sirve para darle nombre a un ordenador desplegado)."""
    for t in sorted(Path("/sys/class/net").glob("*")):
        if t.name != "lo" and not (t / "wireless").exists():
            try:
                return (t / "address").read_text().strip()
            except OSError:
                pass
    return ""


def pedir_config(servidor: str, codigo: str, timeout: int = 30) -> dict:
    """Pide al panel cómo llegar a las copias del equipo. La respuesta va cifrada con el código: por eso no hace falta
    fiarse del certificado del servidor (alguien en medio no puede leerla ni cambiarla sin el código)."""
    if not normalizar(codigo):
        raise ValueError("[OCT-RES-01] El código no es válido: son 12 letras y números, como ABCD-EFGH-JKMN.")
    url = servidor.strip().rstrip("/")
    if not re.match(r"^https?://", url):
        url = "https://" + url
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    req = urllib.request.Request(url + "/api/rescate", data=json.dumps({"id": identificador(codigo),
                                                                      "mac": mi_mac()}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError("[OCT-RES-01] El servidor no acepta el código (¿mal escrito, ya usado o ha pasado más de "
                           "una hora?). Pide otro en el panel. Si es de un despliegue: [OCT-DESP-01] la tanda se ha "
                           "terminado.") from exc
    except OSError as exc:
        raise RuntimeError(f"[OCT-RES-02] No se llega al servidor {url}: ¿está el cable de red puesto? ({exc})") from exc
    try:
        return descifrar(codigo, resp["datos"])
    except Exception as exc:
        raise RuntimeError("[OCT-RES-01] La respuesta del servidor no cuadra con el código. Pide otro en el panel.") from exc


# ------------------------------------------------------------------------------------------------------------ restic
def entorno(cfg: dict) -> dict:
    """Lo mismo que usa el agente para llegar al almacén del servidor (agentes/zerotouch_agent.py: restic_env)."""
    env = os.environ.copy()
    password = cfg.get("password_restic") or cfg.get("restic_password") or ""
    env["RESTIC_PASSWORD"] = str(password)
    env["RESTIC_REPOSITORY"] = cfg.get("restic_repository") or \
        f"s3:http://{cfg.get('ip_cerebro', '127.0.0.1')}:{cfg.get('minio_port', 9000)}/{cfg.get('bucket', 'octopus-backups')}"
    env["AWS_ACCESS_KEY_ID"] = str(cfg.get("minio_access_key") or "admin")
    env["AWS_SECRET_ACCESS_KEY"] = str(cfg.get("minio_secret_key") or password)
    env["AWS_DEFAULT_REGION"] = cfg.get("aws_region", "us-east-1")
    if cfg.get("ca_pem"):
        f = Path(tempfile.gettempdir()) / "octopus_rescate_ca.pem"
        f.write_text(cfg["ca_pem"], encoding="utf-8")
        env["RESTIC_CACERT"] = str(f)
    env.setdefault("RESTIC_CACHE_DIR", str(Path(tempfile.gettempdir()) / "octopus_rescate_cache"))
    return env


def _restic() -> str:
    return os.environ.get("OCTOPUS_RESTIC") or shutil.which("restic") or "restic"


def _run(cmd, env=None, timeout=None, check=True) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout, errors="replace")
    except FileNotFoundError:
        if check:
            raise RuntimeError(f"Falta el programa {cmd[0]} en el rescate") from None
        return subprocess.CompletedProcess(cmd, 127, "", "")
    if check and r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} falló: {(r.stderr or r.stdout).strip()[-600:]}")
    return r


def copias(cfg: dict, completas: bool = False) -> list[dict]:
    """Copias de este equipo, la más nueva primero. completas=True: solo las «copia completa» (para levantarlo)."""
    cmd = [_restic(), "snapshots", "--json", "--host", cfg["hostname"]]
    if completas:
        cmd += ["--tag", "completa"]
    lista = json.loads(_run(cmd, env=entorno(cfg), timeout=600).stdout or "[]")
    lista = [s for s in lista if "forense" not in (s.get("tags") or []) and "vm" not in (s.get("tags") or [])]
    lista.sort(key=lambda s: s.get("time", ""), reverse=True)
    return [{"id": s["short_id"], "fecha": s.get("time", "")[:16].replace("T", " "), "rutas": s.get("paths", []),
             "completa": "completa" in (s.get("tags") or [])} for s in lista]


def tamano_copia(cfg: dict, copia: str) -> int:
    r = _run([_restic(), "stats", copia, "--mode", "restore-size", "--json"], env=entorno(cfg), timeout=3600)
    return int(json.loads(r.stdout).get("total_size") or 0)


# ------------------------------------------------------------------------------------------------------------ discos
def discos() -> list[dict]:
    """Discos enteros del ordenador (sin el propio pendrive de rescate)."""
    r = _run(["lsblk", "-J", "-b", "-d", "-o", "NAME,PATH,SIZE,TYPE,MODEL,TRAN,RM,RO"])
    arranque = disco_de_arranque()
    out = []
    for d in json.loads(r.stdout).get("blockdevices", []):
        if d.get("type") != "disk" or d.get("ro") in (True, "1") or d.get("path") == arranque:
            continue
        out.append({"ruta": d["path"], "tamano": int(d.get("size") or 0),
                    "nombre": (d.get("model") or "").strip() or d["name"], "usb": d.get("tran") == "usb"})
    return out


def disco_de_arranque() -> str:
    """El pendrive desde el que ha arrancado el rescate (nunca se ofrece para borrar)."""
    for punto in ("/run/live/medium", "/lib/live/mount/medium", "/cdrom"):
        r = subprocess.run(["findmnt", "-n", "-o", "SOURCE", punto], capture_output=True, text=True)
        dev = r.stdout.strip()
        if dev:
            p = subprocess.run(["lsblk", "-n", "-o", "PKNAME", dev], capture_output=True, text=True).stdout.strip()
            return "/dev/" + p if p else dev
    return ""


def particion(disco: str, n: int) -> str:
    return f"{disco}{'p' if disco[-1].isdigit() else ''}{n}"


def _uuid(dev: str) -> str:
    return _run(["blkid", "-s", "UUID", "-o", "value", dev]).stdout.strip()


# ------------------------------------------------------------------------------- dejar un Linux como estaba
NUEVAS_CARPETAS = {"proc": 0o555, "sys": 0o555, "dev": 0o755, "run": 0o755, "tmp": 0o1777, "var/tmp": 0o1777,
                   "mnt": 0o755, "media": 0o755, "var/cache": 0o755}
_MONTAJES_NUEVOS = ("/", "/boot", "/boot/efi", "/efi")


def arreglar_fstab(texto: str, uuid_raiz: str, uuid_efi: str, tipo_raiz: str = "ext4") -> str:
    """El fstab del equipo copiado, con el disco nuevo: la raíz y el arranque pasan a las particiones nuevas; el
    intercambio que ya no existe se comenta, y el resto de discos lleva «nofail» (si ya no están, arranca igual)."""
    salida = ["# Disco puesto por el USB de rescate de OCTOPUS",
              f"UUID={uuid_raiz} / {tipo_raiz} errors=remount-ro 0 1",
              f"UUID={uuid_efi} /boot/efi vfat umask=0077 0 1"]
    for linea in texto.splitlines():
        campos = linea.split()
        if not campos or linea.lstrip().startswith("#") or len(campos) < 3:
            salida.append(linea)
            continue
        if campos[1] in _MONTAJES_NUEVOS or campos[2] == "swap":
            salida.append("# (antes) " + linea)
            continue
        if len(campos) >= 4 and "nofail" not in campos[3].split(","):
            campos[3] += ",nofail"
            linea = "\t".join(campos)
        salida.append(linea)
    return "\n".join(salida) + "\n"


def _chroot(raiz: str, cmd: list[str], check=True) -> subprocess.CompletedProcess:
    return _run(["chroot", raiz, *cmd], check=check, timeout=1800)


def _existe_en(raiz: str, *programas: str) -> str:
    for p in programas:
        for d in ("usr/sbin", "usr/bin", "sbin", "bin"):
            if os.path.exists(os.path.join(raiz, d, p)):
                return p
    return ""


def poner_arranque(raiz: str, disco: str, avisar=print) -> list[str]:
    """GRUB del propio sistema copiado: UEFI (como «disco extraíble», vale en cualquier placa) y BIOS antigua."""
    grub = _existe_en(raiz, "grub-install", "grub2-install")
    if not grub:
        raise RuntimeError("[OCT-RES-04] El sistema copiado no tiene GRUB (el programa de arranque): no se puede hacer arrancable.")
    libgrub = next((os.path.join(raiz, d) for d in ("usr/lib/grub", "usr/lib/grub2") if os.path.isdir(os.path.join(raiz, d))), "")
    hechos = []
    if libgrub and os.path.isdir(os.path.join(libgrub, "x86_64-efi")):
        _chroot(raiz, [grub, "--target=x86_64-efi", "--efi-directory=/boot/efi", "--removable", "--no-nvram"])
        hechos.append("UEFI")
    if libgrub and os.path.isdir(os.path.join(libgrub, "i386-pc")):
        _chroot(raiz, [grub, "--target=i386-pc", disco])
        hechos.append("BIOS")
    if not hechos:
        raise RuntimeError("[OCT-RES-04] Al GRUB del sistema copiado le faltan sus piezas (x86_64-efi / i386-pc).")
    avisar(f"Arranque puesto ({' y '.join(hechos)}).")
    if _existe_en(raiz, "update-initramfs"):
        _chroot(raiz, ["update-initramfs", "-u", "-k", "all"])
    elif _existe_en(raiz, "dracut"):
        _chroot(raiz, ["dracut", "--regenerate-all", "-f"])
    if _existe_en(raiz, "update-grub"):
        _chroot(raiz, ["update-grub"])
    else:
        mk = _existe_en(raiz, "grub-mkconfig", "grub2-mkconfig")
        destino = "/boot/grub2/grub.cfg" if mk == "grub2-mkconfig" else "/boot/grub/grub.cfg"
        _chroot(raiz, [mk, "-o", destino])
    return hechos


def restaurar_linux(cfg: dict, copia: str, disco: str, avisar=print, nuevo: dict | None = None) -> dict:
    """BORRA el disco y pone en él la copia completa de un Linux, lista para arrancar."""
    if not os.path.exists(disco):
        raise RuntimeError(f"No existe el disco {disco}")
    if disco == disco_de_arranque():
        raise RuntimeError("Ese es el propio pendrive de rescate.")
    necesita = tamano_copia(cfg, copia)
    tiene = int(_run(["blockdev", "--getsize64", disco]).stdout.strip() or 0)
    if necesita and tiene and necesita > (tiene - 600 * 1024 ** 2) * 0.95:
        raise RuntimeError(f"[OCT-RES-03] El disco es pequeño: la copia ocupa {necesita // 1024 ** 3 + 1} GB y el disco tiene "
                           f"{tiene // 1024 ** 3} GB.")
    avisar(f"Preparando {disco} (se borra todo lo que tenía)...")
    for p in sorted(Path("/dev").glob(Path(disco).name + "*"), reverse=True):
        subprocess.run(["umount", "-q", str(p)], capture_output=True)
    _run(["wipefs", "-a", disco])
    _run(["sgdisk", "-Z", disco])
    _run(["sgdisk", "-n", "1:0:+512M", "-t", "1:ef00", "-c", "1:EFI", "-n", "2:0:+1M", "-t", "2:ef02", "-c", "2:BIOS",
          "-n", "3:0:0", "-t", "3:8300", "-c", "3:OCTOPUS", disco])
    _run(["partprobe", disco], check=False)
    _run(["udevadm", "settle"], check=False)
    efi, raiz_dev = particion(disco, 1), particion(disco, 3)
    for _ in range(30):   # las particiones nuevas tardan un momento en aparecer
        if os.path.exists(efi) and os.path.exists(raiz_dev):
            break
        import time
        time.sleep(1)
    _run(["mkfs.vfat", "-F", "32", "-n", "EFI", efi])
    _run(["mkfs.ext4", "-F", "-q", "-L", "octopus-raiz", raiz_dev])
    raiz = tempfile.mkdtemp(prefix="octopus_raiz_")
    montados = []

    def montar(*args):
        _run(["mount", *args])
        montados.append(args[-1])
    try:
        montar(raiz_dev, raiz)
        os.makedirs(os.path.join(raiz, "boot", "efi"), exist_ok=True)
        montar(efi, os.path.join(raiz, "boot", "efi"))
        avisar(f"Poniendo la copia {copia} (puede tardar mucho; depende de la red y del tamaño)...")
        r = _run([_restic(), "restore", copia, "--target", raiz], env=entorno(cfg), timeout=48 * 3600, check=False)
        if r.returncode not in (0, 3):   # 3: algunos archivos no se pudieron leer de la copia (se avisa)
            raise RuntimeError(f"restic restore falló: {(r.stderr or r.stdout).strip()[-600:]}")
        if not os.path.isdir(os.path.join(raiz, "etc")):
            raise RuntimeError("Esa copia no es de un sistema entero (le falta /etc): elige una «copia completa».")
        for c, modo in NUEVAS_CARPETAS.items():
            p = os.path.join(raiz, c)
            os.makedirs(p, exist_ok=True)
            os.chmod(p, modo)
        fstab = Path(raiz) / "etc" / "fstab"
        viejo = fstab.read_text(encoding="utf-8", errors="replace") if fstab.exists() else ""
        if viejo:
            (Path(raiz) / "etc" / "fstab.antes-del-rescate").write_text(viejo, encoding="utf-8")
        fstab.write_text(arreglar_fstab(viejo, _uuid(raiz_dev), _uuid(efi)), encoding="utf-8")
        for d in ("dev", "proc", "sys", "run"):
            montar("--bind", f"/{d}", os.path.join(raiz, d))
        if os.path.isdir("/sys/firmware/efi/efivars"):
            montar("--bind", "/sys/firmware/efi/efivars", os.path.join(raiz, "sys/firmware/efi/efivars"))
        if nuevo:
            personalizar(raiz, nuevo, avisar)
        hechos = poner_arranque(raiz, disco, avisar)
        aviso = "Algunos archivos no se pudieron leer de la copia." if r.returncode == 3 else ""
        return {"status": "success", "disco": disco, "arranque": hechos, "aviso": aviso}
    finally:
        _run(["sync"], check=False)
        for m in reversed(montados):
            subprocess.run(["umount", "-l", m], capture_output=True)
        try:
            os.rmdir(raiz)
        except OSError:
            pass


def personalizar(raiz: str, nuevo: dict, avisar=print) -> None:
    """Despliegue: la copia de un equipo «de referencia» pasa a ser OTRO ordenador. Nombre nuevo, identidad nueva
    (machine-id, claves SSH) y su propio OCTOPUS (se da de alta solo en el panel con su clave)."""
    r = Path(raiz)
    nombre = nuevo["hostname"]
    viejo = (r / "etc/hostname").read_text().strip() if (r / "etc/hostname").exists() else ""
    (r / "etc/hostname").write_text(nombre + "\n")
    hosts = r / "etc/hosts"
    if hosts.exists() and viejo:
        hosts.write_text(re.sub(rf"(?<![\w.-]){re.escape(viejo)}(?![\w.-])", nombre, hosts.read_text()))
    # identidad de la máquina: vacía = systemd crea una nueva al arrancar
    (r / "etc/machine-id").write_text("")
    dbus = r / "var/lib/dbus/machine-id"
    if dbus.exists() and not dbus.is_symlink():
        dbus.unlink()
    # claves SSH propias (si no, todos los clones tendrían la misma y se podrían suplantar entre ellos)
    claves = list((r / "etc/ssh").glob("ssh_host_*")) if (r / "etc/ssh").is_dir() else []
    for f in claves:
        f.unlink()
    if claves and _existe_en(raiz, "ssh-keygen"):
        _chroot(raiz, ["ssh-keygen", "-A"])
    # su propio agente de OCTOPUS: configuración nueva, y fuera lo que recordaba el equipo de referencia
    if nuevo.get("agente"):
        d = r / "etc/octopus"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps(nuevo["agente"], indent=1))
        os.chmod(d / "config.json", 0o600)
        estado = r / "var/lib/octopus"
        if estado.is_dir():
            for f in estado.iterdir():
                if f.is_file():
                    f.unlink()
    avisar(f"Este ordenador se llamará {nombre}.")


def disco_principal() -> str:
    """El disco interno más grande (para desplegar sin tener que elegir)."""
    ds = [d for d in discos() if not d["usb"]]
    return max(ds, key=lambda d: d["tamano"])["ruta"] if ds else ""


def sacar_archivos(cfg: dict, copia: str, carpeta: str, avisar=print) -> dict:
    """Copia lo de una copia a una carpeta (un disco USB montado), sin borrar nada de lo que haya."""
    destino = Path(carpeta) / f"OCTOPUS-{cfg['hostname']}-{copia}"
    destino.mkdir(parents=True, exist_ok=True)
    avisar(f"Sacando la copia {copia} a {destino}...")
    r = _run([_restic(), "restore", copia, "--target", str(destino)], env=entorno(cfg), timeout=48 * 3600, check=False)
    if r.returncode not in (0, 3):
        raise RuntimeError(f"restic restore falló: {(r.stderr or r.stdout).strip()[-600:]}")
    return {"status": "success", "carpeta": str(destino)}


# ------------------------------------------------------------------------------------------------------- con menús
class Menu:
    """Ventanitas en la consola (whiptail; si no está, preguntas normales)."""

    def __init__(self):
        self.w = shutil.which("whiptail")

    def _w(self, *args) -> str | None:
        r = subprocess.run([self.w, "--title", "OCTOPUS - USB de rescate", *args], stderr=subprocess.PIPE, text=True)
        return r.stderr.strip() if r.returncode == 0 else None

    def aviso(self, texto):
        if self.w:
            self._w("--msgbox", texto, "16", "74")
        else:
            input(texto + "\n[Enter] ")

    def pregunta(self, texto, defecto=""):
        if self.w:
            return self._w("--inputbox", texto, "12", "74", defecto)
        r = input(f"{texto} [{defecto}]: ").strip()
        return r or defecto

    def elegir(self, texto, opciones):
        if self.w:
            pares = [x for clave, et in opciones for x in (clave, et)]
            return self._w("--menu", texto, "20", "78", "10", *pares)
        for i, (_, et) in enumerate(opciones, 1):
            print(f" {i}) {et}")
        try:
            return opciones[int(input(texto + " (número): ")) - 1][0]
        except (ValueError, IndexError):
            return None

    def si(self, texto):
        if self.w:
            return subprocess.run([self.w, "--title", "OCTOPUS - USB de rescate", "--defaultno", "--yesno", texto,
                                   "14", "74"]).returncode == 0
        return input(texto + " (escribe SI): ").strip().upper() == "SI"


def _gb(n: int) -> str:
    return f"{n / 1024 ** 3:.0f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.0f} MB"


def servidor_del_arranque() -> str:
    """Si ha arrancado por red desde el servidor de OCTOPUS, su dirección (así no hay que escribirla)."""
    try:
        for x in Path("/proc/cmdline").read_text().split():
            if x.startswith("octopus.servidor="):
                return x.split("=", 1)[1]
    except OSError:
        pass
    return ""


AYUDA = ("\n\nCon el código [OCT-…] del principio, qué hacer está en el panel → Avisos → «Ver todos los avisos "
         "posibles», o en SOLUCIONES.md en GitHub.")


def con_menus() -> int:
    m = Menu()
    m.aviso("Bienvenido al rescate de OCTOPUS.\n\nNecesitas: el cable de red puesto y, en el panel de OCTOPUS (desde "
            "otro ordenador o el móvil), la ficha del equipo → «USB de rescate» → «Dar código».")
    cfg = None
    por_red = servidor_del_arranque()
    while cfg is None:
        servidor = m.pregunta("Dirección del servidor OCTOPUS (sale en la misma pantalla del código):", por_red)
        if servidor is None:
            return 1
        codigo = m.pregunta("Código (12 letras y números):")
        if codigo is None:
            return 1
        try:
            cfg = pedir_config(servidor, codigo)
        except Exception as exc:
            m.aviso(str(exc))
    if cfg.get("despliegue"):
        return desplegar_con_menus(m, cfg)
    que = m.elegir(f"Equipo: {cfg['hostname']}. ¿Qué quieres hacer?",
                   [("levantar", "Dejar este ordenador como estaba (borra su disco)"),
                    ("sacar", "Sacar los archivos a un disco USB (no borra nada)")])
    if not que:
        return 1
    try:
        lista = copias(cfg, completas=(que == "levantar"))
    except Exception as exc:
        m.aviso(f"No se pueden ver las copias: {exc}")
        return 1
    if not lista:
        m.aviso("Este equipo no tiene " + ("«copia completa» (actívala en su ficha cuando vuelva a funcionar)."
                                           if que == "levantar" else "copias."))
        return 1
    copia = m.elegir("¿Qué copia? (la primera es la más nueva)",
                     [(c["id"], f"{c['fecha']}  {'(completa)' if c['completa'] else ', '.join(c['rutas'])[:40]}")
                      for c in lista[:10]])
    if not copia:
        return 1
    try:
        if que == "levantar":
            if cfg.get("os_family") == "windows":
                m.aviso("Este equipo es Windows: para dejarlo como estaba usa su «imagen de disco» con un USB de "
                        "instalación de Windows (los pasos están en su ficha). Aquí puedes sacar sus archivos.")
                return 1
            ds = discos()
            disco = m.elegir("¿En qué disco lo pongo? SE BORRARÁ ENTERO.",
                             [(d["ruta"], f"{d['nombre']}  {_gb(d['tamano'])}{'  (USB)' if d['usb'] else ''}") for d in ds])
            if not disco or not m.si(f"Se BORRARÁ TODO lo que hay en {disco} y se pondrá la copia {copia}.\n\n¿Seguro?"):
                return 1
            r = restaurar_linux(cfg, copia, disco, avisar=print)
            m.aviso("Listo. Quita el pendrive y reinicia: el ordenador arrancará como estaba el día de la copia."
                    + (f"\n\nAviso: {r['aviso']}" if r.get("aviso") else ""))
        else:
            ds = [d for d in discos() if d["usb"]]
            if not ds:
                m.aviso("Conecta un disco USB (que no sea el del rescate) y vuelve a empezar.")
                return 1
            disco = m.elegir("¿A qué disco USB? (no se borra nada)",
                             [(d["ruta"], f"{d['nombre']}  {_gb(d['tamano'])}") for d in ds])
            if not disco:
                return 1
            parte = _particion_grande(disco)
            punto = tempfile.mkdtemp(prefix="octopus_usb_")
            _run(["mount", parte, punto])
            try:
                r = sacar_archivos(cfg, copia, punto)
            finally:
                _run(["umount", punto], check=False)
            m.aviso(f"Listo: los archivos están en el disco USB, carpeta {Path(r['carpeta']).name}.")
    except Exception as exc:
        m.aviso(f"No ha salido bien: {exc}" + AYUDA)
        return 1
    return 0


def desplegar_con_menus(m, cfg) -> int:
    dep = cfg["despliegue"]
    disco = disco_principal()
    if not disco:
        m.aviso("No encuentro ningún disco interno en este ordenador.")
        return 1
    tam = next((d for d in discos() if d["ruta"] == disco), {}).get("tamano", 0)
    if not m.si(f"Instalar «{cfg['hostname']}» (copia del {dep.get('fecha', '')}) en este ordenador.\n\n"
                f"Se llamará {dep['nuevo']['hostname']}.\nSe BORRARÁ TODO el disco {disco} ({_gb(tam)}).\n\n¿Seguro?"):
        return 1
    try:
        r = restaurar_linux(cfg, dep["copia"], disco, avisar=print, nuevo=dep["nuevo"])
    except Exception as exc:
        m.aviso(f"No ha salido bien: {exc}" + AYUDA)
        return 1
    m.aviso(f"Listo: {dep['nuevo']['hostname']} instalado. Quita el pendrive (o desconecta el arranque por red) y "
            "reinicia. Aparecerá solo en el panel." + (f"\n\nAviso: {r['aviso']}" if r.get("aviso") else ""))
    return 0


def _particion_grande(disco: str) -> str:
    r = json.loads(_run(["lsblk", "-J", "-b", "-o", "PATH,SIZE,TYPE,FSTYPE", disco]).stdout)
    partes = [p for d in r.get("blockdevices", []) for p in (d.get("children") or []) if p.get("fstype")]
    if not partes:
        raise RuntimeError("El disco USB no tiene ninguna partición que se pueda usar.")
    return max(partes, key=lambda p: int(p.get("size") or 0))["path"]


def main(argv: list[str]) -> int:
    if not argv:
        return con_menus()
    orden, args = argv[0], argv[1:]
    if orden == "version":
        print("OCTOPUS rescate", VERSION)
        return 0
    if orden == "config" and len(args) == 3:
        Path(args[2]).write_text(json.dumps(pedir_config(args[0], args[1])), encoding="utf-8")
        return 0
    cfg = json.loads(Path(args[0]).read_text(encoding="utf-8")) if args else {}
    if orden == "copias":
        print(json.dumps(copias(cfg, completas="--completas" in args), indent=1))
    elif orden == "restaurar" and len(args) >= 3 and "--si-borrar-todo" in args:
        print(json.dumps(restaurar_linux(cfg, args[1], args[2])))
    elif orden == "desplegar" and len(args) >= 4 and "--si-borrar-todo" in args:
        nuevo = json.loads(Path(args[3]).read_text(encoding="utf-8"))
        print(json.dumps(restaurar_linux(cfg, args[1], args[2], nuevo=nuevo)))
    elif orden == "sacar" and len(args) == 3:
        print(json.dumps(sacar_archivos(cfg, args[1], args[2])))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
