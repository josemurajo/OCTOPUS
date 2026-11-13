#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
Prueba de la copia «imagen de disco» de Windows (agentes/octopus_imagen.py).

  python tests/ci/prueba_imagen.py           -> lo que se puede comprobar en cualquier sistema (destinos, avisos)
  python tests/ci/prueba_imagen.py real D:   -> en Windows con wbadmin: hace una copia de verdad de una carpeta
                                               pequeña en D: y comprueba que Windows la ve como versión
"""
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "agentes"))
import octopus_imagen as oi  # noqa: E402

FALLOS = []


def chk(c, n, x=""):
    print(("PASS " if c else "FAIL ") + n, x if not c else "")
    if not c:
        FALLOS.append(n)


def basica():
    v = oi.destino_valido
    chk(v("E:") == "E:" and v("e:\\") == "E:", "una unidad (E:)")
    chk(v("\\\\NAS\\copias") == "\\\\NAS\\copias" and v("\\\\NAS\\copias\\") == "\\\\NAS\\copias",
        "una carpeta de red (\\\\NAS\\copias)")
    for malo in ("", "C:/x", "E:\\carpeta", "rm -rf /", "\\\\solo", "E: & calc", "\\\\s\\c\" x"):
        chk(v(malo) is None, f"no vale: {malo!r}")
    if oi.SYSTEM != "windows":
        chk(oi.disponible()[0] is False and "Windows" in oi.disponible()[1], "fuera de Windows lo dice claro")
        chk(oi.hacer("E:")["status"] == "error" and oi.versiones("E:") == [], "fuera de Windows no hace nada")
    chk(len(oi.COMO_RECUPERAR) >= 4 and any("Recuperación de imagen" in p for p in oi.COMO_RECUPERAR),
        "pasos para recuperar el ordenador entero")


def real(destino):
    ok, motivo = oi.disponible()
    chk(ok, "wbadmin está en este Windows", motivo)
    if not ok:
        return
    sistema = os.environ.get("SystemDrive", "C:")
    r = oi.hacer(sistema, mirar_si_ocupado=False)
    chk(r["status"] == "error" and "mismo disco" in r["message"], "no guarda la imagen en el disco de Windows", r)
    carpeta = Path(tempfile.mkdtemp(prefix="octopus_imagen_", dir=sistema + "\\"))
    (carpeta / "documento.txt").write_text("hola desde la prueba de imagen\n" * 100, encoding="utf-8")
    antes = oi.versiones(destino)
    r = oi.hacer(destino, incluir=str(carpeta), mirar_si_ocupado=False)
    chk(r["status"] == "success", "wbadmin hace la copia", r)
    despues = oi.versiones(destino)
    chk(len(despues) > len(antes), "Windows ve la copia nueva como versión", (antes, despues))
    chk((Path(destino + "\\") / "WindowsImageBackup").is_dir(), "la carpeta WindowsImageBackup está en el destino")


if __name__ == "__main__":
    basica()
    if len(sys.argv) > 2 and sys.argv[1] == "real":
        real(oi.destino_valido(sys.argv[2]) or sys.argv[2])
    print("FALLOS:", FALLOS or "ninguno")
    sys.exit(1 if FALLOS else 0)
