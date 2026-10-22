#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - Comprueba que una versión está lista para publicarse, EXACTAMENTE como lo comprobará el actualizador de
# cada servidor (actualizador.sh): firma de José válida, y cada archivo igual al del MANIFIESTO, ni uno más ni uno menos.
#   bash herramientas/comprobar_publicacion.sh [carpeta]     (por defecto, el commit actual del repositorio)
# Lo usa la publicación automática (.github/workflows/publicar.yml) antes de pasar una versión a la rama «publicado».
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
fallo() { echo "NO SE PUEDE PUBLICAR: $*" >&2; exit 1; }

T=""
if [ -n "${1:-}" ]; then
    DIR="$(cd "$1" && pwd)"
else
    # lo que de verdad descargarán los servidores: el contenido del commit (no los archivos sueltos de la carpeta)
    T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
    git -C "$RAIZ" archive HEAD | tar -x -C "$T"
    DIR="$T"
fi
cd "$DIR"
[ -f MANIFIESTO ] || fallo "falta el MANIFIESTO (se crea con herramientas/crear_manifiesto.sh)"
[ -f MANIFIESTO.sig ] || fallo "falta la firma MANIFIESTO.sig (la crea José con herramientas/firmar_version.sh)"
grep -q "ssh-" install/firma_publicacion.pub 2>/dev/null || fallo "falta la clave pública de publicación (install/firma_publicacion.pub)"

FIRMANTES="$(mktemp)"
printf 'octopus namespaces="octopus-version" %s\n' "$(grep -m1 'ssh-' install/firma_publicacion.pub)" > "$FIRMANTES"
ssh-keygen -Y verify -f "$FIRMANTES" -I octopus -n octopus-version -s MANIFIESTO.sig < MANIFIESTO >/dev/null 2>&1 \
    || { rm -f "$FIRMANTES"; fallo "la firma no es válida (no es de la clave de José o el MANIFIESTO ha cambiado después de firmar)"; }
rm -f "$FIRMANTES"

if command -v sha256sum >/dev/null; then
    sha256sum -c --quiet --strict MANIFIESTO >/dev/null 2>&1 || fallo "hay archivos distintos de los firmados (algo cambió después de crear el MANIFIESTO)"
else
    shasum -a 256 -c --quiet MANIFIESTO >/dev/null 2>&1 || fallo "hay archivos distintos de los firmados"
fi
EN_MANIF="$(sed -E 's/^[0-9a-f]{64} [ *]//' MANIFIESTO | LC_ALL=C sort)"
EN_DISCO="$(find . -type f ! -name MANIFIESTO ! -name MANIFIESTO.sig | sed 's|^\./||' | LC_ALL=C sort)"
[ "$EN_MANIF" = "$EN_DISCO" ] || fallo "hay archivos que no están en el MANIFIESTO (o faltan): $(diff <(echo "$EN_MANIF") <(echo "$EN_DISCO") | grep '^[<>]' | head -5 | tr '\n' ' ')"

V="$(tr -cd '0-9.' < VERSION)"
[[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fallo "el archivo VERSION no tiene una versión válida ($V)"
grep -q "^## $V" CHANGELOG.md 2>/dev/null || fallo "CHANGELOG.md no explica la versión $V (falta la línea «## $V»)"
echo "OK: versión $V firmada por José y completa ($(wc -l < MANIFIESTO) archivos). Lista para publicar."
