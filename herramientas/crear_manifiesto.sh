#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - Crea MANIFIESTO: la huella SHA-256 de cada archivo de la versión (lo que luego se firma).
# Se ejecuta en la copia del repositorio que se va a publicar (usa la lista de archivos de git si la hay).
set -euo pipefail
cd "$(dirname "$0")/.."
SUM="sha256sum"; command -v sha256sum >/dev/null || SUM="shasum -a 256"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files
else
    find . -type f ! -path './.git/*' ! -name '*.pyc' ! -path '*/__pycache__/*' ! -path './install/.env' \
         ! -name 'CREDENCIALES_INICIALES.txt' ! -name '*.log' | sed 's|^\./||'
fi | grep -vx 'MANIFIESTO' | grep -vx 'MANIFIESTO.sig' | LC_ALL=C sort | while read -r f; do $SUM "$f"; done > MANIFIESTO
rm -f MANIFIESTO.sig
echo "MANIFIESTO creado ($(wc -l < MANIFIESTO) archivos, versión $(cat VERSION)). Ahora hay que firmarlo: bash herramientas/firmar_version.sh"
