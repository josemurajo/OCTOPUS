#!/bin/bash
# OCTOPUS - Actualizador seguro del servidor (Linux y Mac). Lo lanza solo un temporizador cada 5 minutos:
#   sudo bash octopus.sh actualizar-pedido
#
# Cómo funciona (pensado para que NO abra ninguna brecha):
#   - El panel web NUNCA ejecuta nada en el equipo: solo deja una petición («actualizar a la versión X») dentro del
#     contenedor. Este script, que corre en el equipo, la recoge.
#   - Solo descarga de la dirección oficial fija (GitHub de OCTOPUS, por HTTPS). No escucha en ningún puerto.
#   - Solo instala si la versión viene FIRMADA con la clave de publicación de OCTOPUS: el MANIFIESTO (lista de todos los
#     archivos con su huella SHA-256) va firmado y la clave pública que lo comprueba es la de ESTA instalación
#     (install/firma_publicacion.pub), no la que venga en la descarga. Un archivo de más, de menos o cambiado = no se instala.
#   - Nunca instala una versión más antigua que la que hay (para volver atrás está «octopus.sh volver», a mano).
#   - Guarda una copia de la carpeta actual y, si la versión nueva no arranca, el instalador vuelve solo a la anterior.
set -uo pipefail
RAIZ="$(cd "$(dirname "$(realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
HOST_ENV="$RAIZ/install/.env"
leer() { [ -f "$HOST_ENV" ] || return 0; { grep -E "^$1=" "$HOST_ENV" 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d '\r"'; }
URL="$(leer OCTOPUS_URL_CODIGO)"; URL="${URL:-https://codeload.github.com/josemurajo/OCTOPUS/tar.gz/refs/heads/main}"
CLAVE="$RAIZ/install/firma_publicacion.pub"
D=/data/actualizacion
C=octopus
NATIVO=0
# servidor nativo de Mac (sin Docker): la peticion del panel esta directamente en la carpeta de datos
PY3=python3
if [ -x "$RAIZ/python/bin/python3" ]; then NATIVO=1; D="$RAIZ/datos/actualizacion"; PY3="$RAIZ/python/bin/python3"; fi

en_c() { if [ $NATIVO = 1 ]; then sh -c "$1"; else docker exec -i "$C" sh -c "$1"; fi; }
estado() { printf '%s' "$1" | en_c "mkdir -p $D && cat > $D/estado"; echo "[$(date '+%F %T')] $1"; }
resultado() { # resultado <ok|error> <texto>
    printf '{"ok": %s, "fecha": "%s", "detalle": %s}' "$( [ "$1" = ok ] && echo true || echo false )" "$(date -Iseconds 2>/dev/null || date)" \
        "$(printf '%s' "$2" | "$PY3" -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$2")" \
        | en_c "cat > $D/resultado.json; rm -f $D/pedida"
    estado "$2"
}
version_mayor() { # version_mayor A B -> 0 si A > B
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]
}

[ $NATIVO = 1 ] || docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$C" || exit 0
# señal de vida: el panel sabe que el actualizador está activado en este equipo
date -Iseconds 2>/dev/null | en_c "mkdir -p $D && cat > $D/actualizador_vivo" || true
en_c "test -f $D/pedida" 2>/dev/null || exit 0

PEDIDA="$(en_c "cat $D/pedida" | tr -cd '0-9.' | head -c 20)"
ACTUAL="$(cat "$RAIZ/VERSION" 2>/dev/null | tr -cd '0-9.')"
estado "Petición recibida: actualizar de $ACTUAL a ${PEDIDA:-la última versión}"
command -v ssh-keygen >/dev/null || { resultado error "Falta ssh-keygen en el equipo (paquete openssh-client): no se puede comprobar la firma"; exit 1; }
grep -q "ssh-" "$CLAVE" 2>/dev/null || { resultado error "Esta instalación no tiene la clave de publicación de OCTOPUS (install/firma_publicacion.pub): por seguridad la actualización a distancia está desactivada. Actualiza a mano con  sudo bash octopus.sh actualizar"; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
estado "Descargando la versión nueva desde GitHub..."
curl -fsSL --proto "$(leer OCTOPUS_PROTO_DESCARGA | grep . || echo =https)" --max-time 600 "$URL" -o "$TMP/codigo.tar.gz" || { resultado error "No se pudo descargar la versión nueva (¿hay Internet?). Se reintentará cuando lo vuelvas a pedir."; exit 1; }
mkdir "$TMP/x" && tar -xzf "$TMP/codigo.tar.gz" -C "$TMP/x" --no-same-owner || { resultado error "La descarga está dañada"; exit 1; }
NUEVO="$(find "$TMP/x" -mindepth 1 -maxdepth 1 -type d | head -1)"
[ -f "$NUEVO/MANIFIESTO" ] && [ -f "$NUEVO/MANIFIESTO.sig" ] || { resultado error "La versión publicada no está firmada todavía: no se instala. Inténtalo más tarde."; exit 1; }

estado "Comprobando la firma de la versión nueva..."
FIRMANTES="$TMP/firmantes"
printf 'octopus namespaces="octopus-version" %s\n' "$(grep -m1 'ssh-' "$CLAVE")" > "$FIRMANTES"
ssh-keygen -Y verify -f "$FIRMANTES" -I octopus -n octopus-version -s "$NUEVO/MANIFIESTO.sig" < "$NUEVO/MANIFIESTO" >/dev/null 2>&1 \
    || { resultado error "La firma de la versión descargada NO es válida: no se instala nada (puede ser una descarga manipulada). Avisa al soporte."; exit 1; }
# cada archivo tiene que estar en el manifiesto con su huella exacta, y no puede sobrar ninguno
( cd "$NUEVO" && { command -v sha256sum >/dev/null && sha256sum -c --quiet --strict MANIFIESTO || shasum -a 256 -c --quiet MANIFIESTO; } ) >/dev/null 2>&1 \
    || { resultado error "Algún archivo de la versión descargada no coincide con lo firmado: no se instala nada. Avisa al soporte."; exit 1; }
EN_MANIF="$(sed -E 's/^[0-9a-f]{64} [ *]//' "$NUEVO/MANIFIESTO" | sort)"
EN_DISCO="$(cd "$NUEVO" && find . -type f ! -name MANIFIESTO ! -name MANIFIESTO.sig | sed 's|^\./||' | sort)"
[ "$EN_MANIF" = "$EN_DISCO" ] || { resultado error "La versión descargada trae archivos que no están firmados: no se instala nada. Avisa al soporte."; exit 1; }

VNUEVA="$(tr -cd '0-9.' < "$NUEVO/VERSION")"
version_mayor "$VNUEVA" "$ACTUAL" || { resultado error "La versión publicada ($VNUEVA) no es más nueva que la instalada ($ACTUAL): no hay nada que actualizar."; exit 0; }

if [ $NATIVO = 1 ]; then
    # el instalador de la version nueva (ya comprobada) guarda la actual, instala y, si no arranca, vuelve sola a ella
    estado "Firma correcta (versión $VNUEVA). Instalando (unos minutos; el panel se reinicia)..."
    if OCTOPUS_DESTINO="$RAIZ" bash "${OCTOPUS_INSTALADOR:-$NUEVO/instalar_servidor_mac.sh}" --sin-preguntas > "$RAIZ/datos/logs/actualizacion_$VNUEVA.log" 2>&1; then
        resultado ok "Actualizado a la versión $VNUEVA. Todo funciona. (Copia de la versión anterior en $RAIZ.anterior)"
        exit 0
    fi
    resultado error "La instalación de $VNUEVA dio problemas y se ha dejado todo como estaba: $(tail -3 "$RAIZ/datos/logs/actualizacion_$VNUEVA.log" | tr '\n' ' ' | cut -c1-300)"
    exit 1
fi
estado "Firma correcta (versión $VNUEVA). Guardando la versión actual por si hay que volver..."
COPIA="$RAIZ/../$(basename "$RAIZ").antes-de-$VNUEVA"
rm -rf "$COPIA"; cp -a "$RAIZ" "$COPIA" || { resultado error "No se pudo guardar la versión actual (¿disco lleno?): no se actualiza."; exit 1; }
# se copian los archivos nuevos; se conservan los propios de esta instalación (ajustes, credenciales, kit, clave de publicación)
( cd "$NUEVO" && find . -type f ! -name MANIFIESTO.sig | while read -r f; do
    case "$f" in ./install/.env|./CREDENCIALES_INICIALES.txt|./install/firma_publicacion.pub) continue ;; esac
    mkdir -p "$RAIZ/$(dirname "$f")" && cp -p "$f" "$RAIZ/$f"
  done )
estado "Instalando la versión $VNUEVA (unos minutos; el panel se reinicia)..."
INSTALADOR="${OCTOPUS_INSTALADOR:-$RAIZ/instalar_servidor.sh}"
[ "$(uname)" = Darwin ] && INSTALADOR="${OCTOPUS_INSTALADOR:-$RAIZ/instalar_servidor_mac.sh}"
if bash "$INSTALADOR" > "$RAIZ/actualizacion_$VNUEVA.log" 2>&1; then
    resultado ok "Actualizado a la versión $VNUEVA. Todo funciona. (Copia de la versión anterior en $COPIA)"
else
    # se dejan los archivos como estaban (el instalador ya ha vuelto solo a la versión anterior del servidor)
    cp -a "$COPIA/." "$RAIZ/" 2>/dev/null
    resultado error "La instalación de $VNUEVA dio problemas y se ha dejado todo como estaba: $(tail -3 "$RAIZ/actualizacion_$VNUEVA.log" | tr '\n' ' ' | cut -c1-300)"
    exit 1
fi
