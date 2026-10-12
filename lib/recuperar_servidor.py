#!/usr/bin/env python3
"""
OCTOPUS Zero-Touch - Recuperar el servidor en una maquina nueva a partir de su autocopia.

Cada noche el mantenimiento guarda una copia del propio servidor (base de datos del panel, .env con las claves,
certificados y claves SSH) con el nombre de equipo "octopus-servidor", en el almacen y, si esta configurado,
en el almacen externo. Este programa la recupera y la pone en su sitio dentro del contenedor.

Se ejecuta DENTRO del contenedor (lo lanza  sudo bash octopus.sh recuperar-servidor):

    python lib/recuperar_servidor.py <almacen>
        <almacen> = /boveda/octopus-backups   (el almacen de este servidor, p. ej. copiado del disco antiguo)
                  = s3:https://...  sftp:usuario@host:/ruta ...   (el almacen externo)
    La clave de las copias se pide por teclado (o en la variable RESTIC_PASSWORD_KIT). Esta en el kit de
    recuperacion ("Clave de las copias"); para el almacen externo, "Clave del almacen externo".

Antes de sobrescribir nada guarda lo actual en /data/antes_de_recuperar_<fecha>/.
"""
from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

DATA = Path(os.environ.get("OCTOPUS_DATA", "/data"))
# donde va cada cosa de la autocopia (ruta dentro de "servidor/" -> ruta en /data)
DESTINOS = [
    (".env", ".env"),
    ("admin_panel.db", "panel/admin_panel.db"),
    ("data/tls", "panel/tls"),
    ("ssh", "ssh"),
    ("ansible/config.json", "ansible/config.json"),
    ("ansible/equipos.ini", "ansible/equipos.ini"),
    ("ansible/wg", "ansible/wg"),
]


def restic() -> str:
    return shutil.which("restic") or "/usr/local/bin/restic"


def buscar_servidor(raiz: Path) -> Path | None:
    """La autocopia se guardo desde una carpeta temporal (.../octopus_autocopia_xxx/servidor): se busca."""
    for leeme in raiz.rglob("LEEME.txt"):
        if leeme.parent.name == "servidor":
            return leeme.parent
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    repo = argv[1]
    clave = os.environ.get("RESTIC_PASSWORD_KIT") or getpass.getpass("Clave de las copias (del kit de recuperacion): ")
    env = dict(os.environ, RESTIC_REPOSITORY=repo, RESTIC_PASSWORD=clave)
    env.setdefault("RESTIC_CACHE_DIR", "/tmp/restic-cache-recuperar")
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "B2_ACCOUNT_ID", "B2_ACCOUNT_KEY"):
        if os.environ.get("OFFSITE_" + k):
            env[k] = os.environ["OFFSITE_" + k]

    print(f"Buscando la copia del servidor en {repo} ...")
    r = subprocess.run([restic(), "snapshots", "--no-lock", "--host", "octopus-servidor", "--latest", "1", "--group-by", "host"],
                       env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print("ERROR: no se puede abrir el almacen. Comprueba la ruta y la clave.\n" + (r.stderr or "")[-400:])
        return 1
    if "octopus-servidor" not in r.stdout:
        print("ERROR: en ese almacen no hay ninguna copia del servidor (equipo 'octopus-servidor').")
        return 1
    print(r.stdout.strip())

    tmp = Path(tempfile.mkdtemp(prefix="octopus_recuperar_"))
    try:
        r = subprocess.run([restic(), "restore", "latest", "--no-lock", "--host", "octopus-servidor",
                            "--target", str(tmp)], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print("ERROR al recuperar la copia del servidor:\n" + (r.stderr or "")[-400:])
            return 1
        origen = buscar_servidor(tmp)
        if not origen:
            print("ERROR: la copia recuperada no tiene el formato esperado (falta servidor/LEEME.txt).")
            return 1

        guardado = DATA / f"antes_de_recuperar_{datetime.now():%Y%m%d_%H%M%S}"
        puestos = []
        for rel_origen, rel_destino in DESTINOS:
            src, dst = origen / rel_origen, DATA / rel_destino
            if not src.exists():
                continue
            if dst.exists():  # se guarda lo que habia antes de sobrescribir
                (guardado / rel_destino).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(guardado / rel_destino))
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            puestos.append(rel_destino)
        os.chmod(DATA / ".env", 0o600)
        if (DATA / "ssh").is_dir():
            os.chmod(DATA / "ssh", 0o700)
            for f in (DATA / "ssh").iterdir():
                os.chmod(f, 0o600 if not f.name.endswith(".pub") else 0o644)
        print("Recuperado: " + ", ".join(puestos))
        if guardado.exists():
            print(f"Lo que habia antes esta en {guardado}")
        print("Listo. Hay que reiniciar OCTOPUS (octopus.sh lo hace solo).")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
