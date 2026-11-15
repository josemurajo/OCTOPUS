#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Prueba: si una copia se corta (reinicio, cuelgue, apagón) o falla, el agente la repite sola enseguida."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["OCTOPUS_STATE_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agentes"))
import zerotouch_agent as z  # noqa: E402

F = []


def chk(c, n, x=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else x, flush=True)
    if not c:
        F.append(n)


chk(not z.copia_cortada() and z.toca_reintentar() == "", "sin nada pendiente, no hay que repetir nada")
# una copia que se quedó a medias: el proceso que copiaba ya no existe (el equipo se reinició)
z.COPIA_EN_MARCHA.write_text(json.dumps({"pid": 999999, "t": time.time() - 600}))
chk(z.copia_cortada() and "se cortó" in z.toca_reintentar(), "copia cortada por un reinicio: se sigue sola", z.toca_reintentar())
# mientras copia este mismo proceso, no cuenta como cortada
z._marcar_copia_en_marcha(True)
chk(not z.copia_cortada(), "mientras se está copiando, no se repite")
z._marcar_copia_en_marcha(False)
chk(not z.COPIA_EN_MARCHA.exists(), "al terminar, se quita la marca")
# la marca se pone y se quita sola alrededor de la copia, aunque la copia falle
z._backup_forense_marcada = lambda cfg, path=None: (_ for _ in ()).throw(RuntimeError("fallo de prueba"))
try:
    z._backup_forense({})
except RuntimeError:
    pass
chk(not z.COPIA_EN_MARCHA.exists(), "si la copia falla, tampoco queda marcada como cortada")
# copia diaria fallida: se repite a los 20 minutos, hasta 3 veces más
z._apuntar_resultado_diaria(False, "sin red")
chk(z.toca_reintentar() == "", "justo después de fallar, espera un poco")
d = json.loads(z.COPIA_FALLIDA.read_text())
d["t"] = time.time() - 25 * 60
z.COPIA_FALLIDA.write_text(json.dumps(d))
chk("intento 2" in z.toca_reintentar(), "a los 20 minutos, lo intenta otra vez", z.toca_reintentar())
for _ in range(3):
    z._apuntar_resultado_diaria(False, "sin red")
d = json.loads(z.COPIA_FALLIDA.read_text())
d["t"] = 0
z.COPIA_FALLIDA.write_text(json.dumps(d))
chk(z.toca_reintentar() == "", "tras 4 intentos para (lo verá el panel como copia antigua y avisará)")
z._apuntar_resultado_diaria(True)
chk(not z.COPIA_FALLIDA.exists(), "cuando sale bien, se olvida")
print("FALLOS:", F or "ninguno")
sys.exit(1 if F else 0)
