#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - Deja una versión lista para que José la firme (lo hace quien mantiene el código, no José):
#   bash herramientas/preparar_version.sh 3.0.0
# Pone el número en VERSION, comprueba que CHANGELOG.md la explica, crea el MANIFIESTO y quita una firma vieja.
# Después: commit + push, y José firma (herramientas/firmar_version.sh) y sube MANIFIESTO.sig. A partir de ahí la
# publicación es automática (.github/workflows/publicar.yml).
# IMPORTANTE: entre preparar y que José firme, no se toca nada más en main (cambiaría la huella de algún archivo y
# la firma dejaría de valer). Si hace falta cambiar algo, se vuelve a ejecutar esto y José firma el MANIFIESTO nuevo.
set -euo pipefail
cd "$(dirname "$0")/.."
V="${1:-}"
[[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Uso: bash herramientas/preparar_version.sh 3.0.0"; exit 2; }
grep -q "^## $V" CHANGELOG.md || { echo "Antes, explica la versión en CHANGELOG.md con una sección «## $V - fecha»"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "Hay cambios sin guardar en git: haz commit primero"; exit 1; }
printf '%s\n' "$V" > VERSION
git rm -q --cached MANIFIESTO.sig 2>/dev/null || true
rm -f MANIFIESTO.sig
git add VERSION
git commit -q -m "Versión $V: número de versión" 2>/dev/null || true
bash herramientas/crear_manifiesto.sh >/dev/null
git add MANIFIESTO
git commit -q -m "Versión $V lista para firmar (MANIFIESTO)"
echo "Versión $V preparada ($(wc -l < MANIFIESTO) archivos). Sube los cambios (push) y pide a José que la firme:"
echo "  doble clic en FIRMAR_VERSION.bat, frase de paso, y pega en el chat la firma que le copia."
