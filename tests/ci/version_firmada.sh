#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - (solo pruebas) crea una «version publicada» firmada con una clave de PRUEBA, como la que descargaria el
# actualizador, para probar la actualizacion a distancia sin tocar GitHub ni la clave real de publicacion.
#   bash tests/ci/version_firmada.sh <salida.tar.gz> <version> <carpeta_clave> [manipular]
# Crea (si no existe) <carpeta_clave>/clave y clave.pub. Con «manipular», cambia un archivo DESPUES de firmar.
set -euo pipefail
SALIDA="$1"; VERSION="$2"; CLAVES="$3"; MANIPULAR="${4:-}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
# Git Bash de Windows: rutas C:\... a /c/... (si no, tar confunde «C:» con otro equipo)
if command -v cygpath >/dev/null 2>&1; then SALIDA="$(cygpath -u "$SALIDA")"; CLAVES="$(cygpath -u "$CLAVES")"; fi
mkdir -p "$CLAVES"
[ -f "$CLAVES/clave" ] || ssh-keygen -q -t ed25519 -N '' -C prueba-publicacion -f "$CLAVES/clave"
T="$(mktemp -d)"
mkdir -p "$T/OCTOPUS-main"
git -C "$REPO" archive HEAD | tar -x -C "$T/OCTOPUS-main"
printf '%s\n' "$VERSION" > "$T/OCTOPUS-main/VERSION"
cp "$CLAVES/clave.pub" "$T/OCTOPUS-main/install/firma_publicacion.pub"
( cd "$T/OCTOPUS-main" && bash herramientas/crear_manifiesto.sh >/dev/null \
  && ssh-keygen -q -Y sign -f "$CLAVES/clave" -n octopus-version MANIFIESTO )
[ "$MANIPULAR" = manipular ] && echo "# cambiado despues de firmar" >> "$T/OCTOPUS-main/lib/avisos.py"
tar -czf "$SALIDA" -C "$T" OCTOPUS-main
rm -rf "$T"
echo "version $VERSION firmada en $SALIDA"
