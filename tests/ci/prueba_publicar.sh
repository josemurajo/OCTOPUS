#!/usr/bin/env bash
# Prueba del camino de publicación (preparar → firmar → comprobar), con una clave de PRUEBA en una copia del
# repositorio: una versión bien firmada pasa; una manipulada, firmada con otra clave o con archivos de más, no.
set -uo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FALLOS=0
ok()  { echo "PASS $*"; }
mal() { echo "FAIL $*"; FALLOS=$((FALLOS+1)); }

git clone -q "$RAIZ" "$T/repo" && cd "$T/repo" || exit 1
git config user.email prueba@ejemplo.invalid; git config user.name prueba
ssh-keygen -q -t ed25519 -N '' -C prueba -f "$T/clave"
ssh-keygen -q -t ed25519 -N '' -C otra -f "$T/otra"
cp "$T/clave.pub" install/firma_publicacion.pub
grep -q "^## 9.9.9" CHANGELOG.md || printf '\n## 9.9.9 - prueba\n- prueba\n' >> CHANGELOG.md
git commit -qam "prueba: clave y changelog"

bash herramientas/preparar_version.sh 9.9.9 >/dev/null && ok "preparar la versión" || mal "preparar la versión"
[ "$(cat VERSION)" = "9.9.9" ] && [ -f MANIFIESTO ] && ok "pone VERSION y crea el MANIFIESTO" || mal "VERSION/MANIFIESTO"
bash herramientas/preparar_version.sh 1.2 >/dev/null 2>&1 && mal "acepta un número raro" || ok "no acepta un número de versión raro"

bash herramientas/comprobar_publicacion.sh >/dev/null 2>&1 && mal "publica sin firma" || ok "sin firma no se publica"

ssh-keygen -q -Y sign -f "$T/clave" -n octopus-version MANIFIESTO && git add MANIFIESTO.sig && git commit -qm firma
salida="$(bash herramientas/comprobar_publicacion.sh 2>&1)" && ok "bien firmada: se puede publicar" || { mal "bien firmada"; echo "$salida"; }

# lo mismo que haría el actualizador de un servidor con esa versión: debe aceptarla
mkdir -p "$T/srv" && git archive HEAD | tar -x -C "$T/srv"
bash herramientas/comprobar_publicacion.sh "$T/srv" >/dev/null 2>&1 && ok "la carpeta descargada también pasa" || mal "carpeta descargada"

echo "# cambio" >> lib/avisos.py && git commit -qam "cambio despues de firmar"
bash herramientas/comprobar_publicacion.sh >/dev/null 2>&1 && mal "acepta un archivo cambiado" || ok "un archivo cambiado después de firmar: no"
git reset -q --hard HEAD~1

echo "hola" > nuevo.txt && git add nuevo.txt && git commit -qm "archivo de mas"
salida="$(bash herramientas/comprobar_publicacion.sh 2>&1)" && mal "acepta un archivo de más" || { echo "$salida" | grep -q "no están en el MANIFIESTO" && ok "un archivo que no estaba firmado: no" || mal "archivo de más ($salida)"; }
git reset -q --hard HEAD~1

rm MANIFIESTO.sig && ssh-keygen -q -Y sign -f "$T/otra" -n octopus-version MANIFIESTO && git commit -qam "firma de otra clave"
bash herramientas/comprobar_publicacion.sh >/dev/null 2>&1 && mal "acepta otra clave" || ok "firmada con otra clave: no"

echo "FALLOS: $FALLOS"
[ $FALLOS -eq 0 ]
