#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - Firma la versión (el archivo MANIFIESTO) para que los servidores puedan actualizarse solos a distancia.
# Lo ejecuta SOLO quien publica OCTOPUS (José), en su PC, desde la carpeta del proyecto:
#   bash herramientas/firmar_version.sh            (en Windows: botón derecho en la carpeta -> "Git Bash Here")
#
# La primera vez crea la clave de publicación en ~/.ssh/octopus_publicar. LA PARTE PRIVADA NO SE COMPARTE CON NADIE
# (ni con Claude): con ella se firman las versiones. Su parte PÚBLICA se copia a install/firma_publicacion.pub
# (esa sí se publica; los servidores la usan para comprobar que una versión es tuya de verdad).
set -euo pipefail
cd "$(dirname "$0")/.."
CLAVE="${OCTOPUS_CLAVE_PUBLICAR:-$HOME/.ssh/octopus_publicar}"
command -v ssh-keygen >/dev/null || { echo "Falta ssh-keygen (usa Git Bash en Windows)"; exit 1; }
if [ ! -f "$CLAVE" ]; then
    echo "== Primera vez: creando tu clave de publicación en $CLAVE"
    echo "   Te pedirá una frase de paso: pon una larga y guárdala en tu gestor de contraseñas."
    mkdir -p "$(dirname "$CLAVE")"
    ssh-keygen -t ed25519 -C "publicacion-octopus" -f "$CLAVE"
    cp "$CLAVE.pub" install/firma_publicacion.pub
    echo
    echo "Clave creada. Avisa a Claude: tiene que publicar install/firma_publicacion.pub y preparar el MANIFIESTO nuevo."
    echo "Después vuelve a ejecutar este mismo script para firmar."
    exit 0
fi
[ -f MANIFIESTO ] || { echo "No hay MANIFIESTO que firmar (se crea con herramientas/crear_manifiesto.sh)"; exit 1; }
cmp -s "$CLAVE.pub" install/firma_publicacion.pub || { echo "AVISO: install/firma_publicacion.pub no es tu clave pública actual. No se firma."; exit 1; }
rm -f MANIFIESTO.sig
ssh-keygen -Y sign -f "$CLAVE" -n octopus-version MANIFIESTO
echo
echo "Versión $(cat VERSION) firmada: se ha creado MANIFIESTO.sig. Avisa a Claude para que la publique."
