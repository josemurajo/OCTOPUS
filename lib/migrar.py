#!/usr/bin/env python3
"""
OCTOPUS Zero-Touch - Pasa una instalacion anterior (sin contenedor) al servidor en contenedor.

La lanza el instalador una sola vez, con la instalacion antigua montada en solo lectura:
  /antiguo      carpeta del proyecto antiguo (.env, data/, ansible/)
  /sshantiguo   /root/.ssh del anfitrion (clave octopus_ed25519)
  /wgantiguo    volumen de wg-easy (wg0.json): los equipos conservan su tunel sin tocarlos
No modifica nada de lo antiguo.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

DATA = Path(os.environ.get("OCTOPUS_DATA", "/data"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def copiar(origen: Path, destino: Path) -> bool:
    if not origen.exists():
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    if origen.is_dir():
        shutil.copytree(origen, destino, dirs_exist_ok=True)
    else:
        shutil.copy2(origen, destino)
    print(f"  {origen} -> {destino}")
    return True


def main() -> int:
    antiguo = Path("/antiguo")
    if (DATA / ".env").is_file():
        print("El servidor ya tiene configuracion: no se migra nada")
        return 0
    if not (antiguo / ".env").is_file():
        print("No hay instalacion anterior que migrar")
        return 0
    print("Migrando la instalacion anterior...")
    for d in ("panel", "wg", "ssh", "logs", "ansible"):
        (DATA / d).mkdir(parents=True, exist_ok=True)
    copiar(antiguo / ".env", DATA / ".env")
    os.chmod(DATA / ".env", 0o600)
    db = "admin_panel.db"
    for linea in (antiguo / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith("DB_PATH="):
            db = Path(linea.split("=", 1)[1].strip()).name
    copiar(antiguo / "data" / db, DATA / "panel" / "admin_panel.db")
    copiar(antiguo / "data" / "tls", DATA / "panel" / "tls")
    copiar(antiguo / "data" / "mantenimiento.json", DATA / "panel" / "mantenimiento.json")
    copiar(antiguo / "ansible" / "equipos.ini", DATA / "ansible" / "equipos.ini")
    for f in Path("/sshantiguo").glob("octopus_ed25519*"):
        copiar(f, DATA / "ssh" / f.name)
    # la base de datos va a /data/panel: DB_PATH relativo al proyecto
    import configuracion
    configuracion.fijar("DB_PATH", "./data/admin_panel.db")
    wg = Path("/wgantiguo/wg0.json")
    if wg.is_file():
        import tunel
        tunel.WG_DIR = DATA / "wg"
        tunel.ESTADO = tunel.WG_DIR / "servidor.json"
        print(f"  Tunel: {tunel.importar_wg_easy(str(wg))} equipos conservan su acceso")
    for f in (DATA / "ssh").glob("*"):
        os.chmod(f, 0o600 if not f.name.endswith(".pub") else 0o644)
    print("Migracion terminada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
