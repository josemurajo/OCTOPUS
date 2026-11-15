#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""Escribe SOLUCIONES.md (qué hacer si algo falla) a partir del catálogo de avisos (lib/avisos.py).
Uso: python3 herramientas/generar_soluciones.py          (lo escribe)
     python3 herramientas/generar_soluciones.py --comprobar   (falla si SOLUCIONES.md no está al día; lo usa la CI)"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "lib"))
import avisos  # noqa: E402

texto = avisos.guia_markdown()
destino = RAIZ / "SOLUCIONES.md"
if "--comprobar" in sys.argv:
    if not destino.exists() or destino.read_text(encoding="utf-8") != texto:
        print("SOLUCIONES.md no está al día: ejecuta  python3 herramientas/generar_soluciones.py")
        sys.exit(1)
    print("SOLUCIONES.md al día")
else:
    destino.write_text(texto, encoding="utf-8")
    print(f"Escrito {destino.name} ({texto.count('### ')} avisos)")
