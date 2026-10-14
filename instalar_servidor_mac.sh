#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS Zero-Touch - Instalador del SERVIDOR para macOS 12 (Monterey) o posterior, Intel y Apple Silicon
# NATIVO: sin Docker, sin Colima y sin Homebrew.
#
#   Doble clic en INSTALAR_SERVIDOR_MAC.command (pide la contrasena del Mac una vez)
#   o:  sudo bash instalar_servidor_mac.sh            [OCTOPUS_IP=192.168.1.10] [OCTOPUS_BOVEDA_DIR=/Volumes/Copias]
#
# Que hace (sin preguntar nada mas):
#   1. Descarga Python portatil, restic y rest-server (versiones fijas, comprobando su huella SHA-256: si una
#      descarga no coincide, no se instala nada).
#   2. Copia OCTOPUS a /usr/local/octopus-servidor e instala lo que necesita (solo dentro de esa carpeta).
#   3. Lo deja como servicio del sistema (LaunchDaemon): arranca solo al encender el Mac, aunque nadie inicie
#      sesion, y se vuelve a levantar solo si se para.
#   4. Deja pasar los puertos 8080 (panel) y 8000 (almacen) si el cortafuegos del Mac esta activado, y abre el panel.
#   Volver a ejecutarlo actualiza a la version de esta carpeta sin perder datos ni copias (y si la nueva no arranca,
#   vuelve sola a la anterior).
set -uo pipefail
RAIZ="$(cd "$(dirname "$0")" && pwd)"
R="${OCTOPUS_DESTINO:-/usr/local/octopus-servidor}"
SIN_PREGUNTAS=0
for a in "$@"; do [ "$a" = "--sin-preguntas" ] && SIN_PREGUNTAS=1; done

PY_TAG=20250818; PY_VER=3.12.11
case "$(uname -m)" in
    arm64)  PY_ARCH=aarch64-apple-darwin; PY_SHA=fabb5fd4de54c68ce7e70d19fb08127549da5787cd38a34d00000749f4fde478
            RA=arm64; RESTIC_SHA=10b3f5491e54c82b421980e848542f8f589ad6635f83fb2d89d9996cb37ac9c7
            REST_SHA=87dc3e4d76d848b18d8026eda874c1d698abc268a822e2e5c41c2fc8b63208a6 ;;
    x86_64) PY_ARCH=x86_64-apple-darwin;  PY_SHA=896add7763faa8012ba6a37346718b32ed0ac041230979cfe8fc802fbb0daeef
            RA=amd64; RESTIC_SHA=6b2fc43f794182788aaa8dae50f1f731c33c5126558e621d693c18455aae92cc
            REST_SHA=da87e744a772ddf9b14b8ffbf1b9d2ce99b7081ef217f4e6d6c8c2765cd4c4db ;;
    *) echo "Procesador no soportado: $(uname -m)"; exit 1 ;;
esac
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/$PY_TAG/cpython-$PY_VER%2B$PY_TAG-$PY_ARCH-install_only.tar.gz"
RESTIC_URL="https://github.com/restic/restic/releases/download/v0.16.4/restic_0.16.4_darwin_$RA.bz2"
REST_URL="https://github.com/restic/rest-server/releases/download/v0.13.0/rest-server_0.13.0_darwin_$RA.tar.gz"

PROGRESO="/Library/Logs/OCTOPUS-Servidor-instalacion.txt"   # banderines: cada paso con la hora
marca() { { echo "[$(date '+%F %T')] $*" >> "$PROGRESO"; } 2>/dev/null || true; }
paso() { marca "==> $*"; echo; printf '\033[1;36m==> %s\033[0m\n' "$*"; }
bien() { marca "OK  $*"; printf '    \033[32m%s\033[0m\n' "$*"; }
aviso() { marca "..  $*"; printf '    \033[33m%s\033[0m\n' "$*"; }
fallo() { marca "ERROR $*"; printf '\n\033[1;31mERROR: %s\033[0m\n' "$*"; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fallo "Este instalador es para Mac. En Linux: sudo bash instalar_servidor.sh"
if [ "$(id -u)" -ne 0 ]; then
    echo "OCTOPUS necesita permiso de administrador una vez para instalarse como servicio del Mac."
    exec sudo OCTOPUS_IP="${OCTOPUS_IP:-}" OCTOPUS_BOVEDA_DIR="${OCTOPUS_BOVEDA_DIR:-}" OCTOPUS_DESTINO="$R" bash "$0" "$@"
fi
[ -f "$RAIZ/lib/servidor.py" ] || fallo "No encuentro lib/servidor.py: ejecuta el script desde la carpeta de OCTOPUS"
MAYOR="$(sw_vers -productVersion | cut -d. -f1)"
[ "$MAYOR" -ge 12 ] 2>/dev/null || fallo "Hace falta macOS 12 (Monterey) o posterior."
marca "---- inicio de la instalacion (usuario ${SUDO_USER:-root}) ----"
printf '\033[1mOCTOPUS Zero-Touch - instalacion del servidor en Mac\033[0m   (macOS %s, %s)\n' "$(sw_vers -productVersion)" "$(uname -m)"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
HOST_ENV="$R/install/.env"
leer() { [ -f "$HOST_ENV" ] || return 0; { grep -E "^$1=" "$HOST_ENV" 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d '\r"'; }
descargar() { # descargar <url> <sha256> <nombre>
    local d="$TMP/$3" i
    for i in 1 2 3; do curl -fsSL --proto '=https' --max-time 600 "$1" -o "$d" && break; marca "descarga de $3 fallida (intento $i)"; sleep $((5 * i)); done
    [ -s "$d" ] || fallo "No se pudo descargar $3. Comprueba la conexion a Internet y vuelve a intentarlo."
    [ "$(shasum -a 256 "$d" | cut -d' ' -f1)" = "$2" ] || { rm -f "$d"; fallo "La descarga de $3 no es la oficial (huella distinta): por seguridad no se instala nada."; }
    bien "$3 descargado y comprobado"
}
responde() { curl -fsk -m 5 "https://127.0.0.1:${PUERTO:-8080}/healthz" >/dev/null 2>&1; }
parar() {
    launchctl bootout system/com.octopus.servidor 2>/dev/null || true
    sleep 2
    pkill -f "$R/python/bin/python" 2>/dev/null || true
    pkill -f "$R/bin/rest-server" 2>/dev/null || true
    sleep 1
}
ya_estaba=0; [ -f "$R/lib/servidor.py" ] && ya_estaba=1

# ------------------------------------------------------------------ direccion y ajustes
paso "Direccion del servidor"
IP="${OCTOPUS_IP:-$(leer OCTOPUS_IP)}"
if [ -z "$IP" ]; then
    IF="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
    IP="$(ipconfig getifaddr "${IF:-en0}" 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
fi
[ -n "$IP" ] || fallo "No se pudo averiguar la IP. Ejecuta: sudo OCTOPUS_IP=<ip> bash $0"
bien "Los equipos llegaran al servidor por $IP"
BOVEDA="${OCTOPUS_BOVEDA_DIR:-$(leer OCTOPUS_BOVEDA_DIR)}"; BOVEDA="${BOVEDA:-$R/boveda}"
PUERTO="$(leer ADMIN_PORT)"; PUERTO="${PUERTO:-8080}"

# ------------------------------------------------------------------ descargas
paso "Descargando lo necesario (Python portatil, restic y rest-server)"
descargar "$PY_URL" "$PY_SHA" python.tar.gz
descargar "$RESTIC_URL" "$RESTIC_SHA" restic.bz2
descargar "$REST_URL" "$REST_SHA" rest-server.tar.gz

# ------------------------------------------------------------------ copia de la version actual (por si hay que volver)
EXCLUIR=(--exclude datos --exclude boveda --exclude python --exclude bin --exclude data --exclude .git --exclude __pycache__)
if [ $ya_estaba = 1 ]; then
    paso "Guardando la version instalada por si hay que volver a ella"
    parar
    rm -rf "$R.anterior"; mkdir -p "$R.anterior"
    rsync -a "${EXCLUIR[@]}" "$R/" "$R.anterior/" || fallo "No se pudo guardar la version actual (¿disco lleno?)"
    bien "copia guardada en $R.anterior"
fi

# ------------------------------------------------------------------ instalar
paso "Instalando OCTOPUS en $R"
mkdir -p "$R/bin" "$R/datos/logs" "$R/install" "$BOVEDA"
chmod 755 "$R"; chmod 700 "$R/datos"
if [ "$RAIZ" != "$R" ]; then
    rsync -a "${EXCLUIR[@]}" --exclude tests --exclude .env --exclude CREDENCIALES_INICIALES.txt --exclude '*.pyc' \
        "$RAIZ/" "$R/" || fallo "No se pudieron copiar los archivos de OCTOPUS"
fi
rm -rf "$R/python"
tar -xzf "$TMP/python.tar.gz" -C "$R" || fallo "No se pudo descomprimir Python"
[ -x "$R/python/bin/python3" ] || fallo "No se pudo preparar Python"
bunzip2 -c "$TMP/restic.bz2" > "$R/bin/restic" && chmod 755 "$R/bin/restic"
mkdir -p "$TMP/rest" && tar -xzf "$TMP/rest-server.tar.gz" -C "$TMP/rest" && \
    cp "$(find "$TMP/rest" -name rest-server -type f | head -1)" "$R/bin/rest-server" && chmod 755 "$R/bin/rest-server"
xattr -dr com.apple.quarantine "$R" 2>/dev/null || true
"$R/bin/restic" version >/dev/null 2>&1 && "$R/bin/rest-server" --version >/dev/null 2>&1 || fallo "No se pudieron preparar restic y rest-server"
bien "$("$R/bin/restic" version)"
aviso "Instalando las librerias de Python (1-3 minutos)..."
"$R/python/bin/python3" -m pip install --disable-pip-version-check --no-warn-script-location -q -r "$R/requirements.txt" \
    > "$R/datos/logs/pip.log" 2>&1 || { tail -5 "$R/datos/logs/pip.log"; fallo "No se pudieron instalar las librerias de Python"; }
"$R/python/bin/python3" -c "import flask, gunicorn, paramiko, cryptography, bcrypt" || fallo "Faltan librerias de Python"
bien "librerias instaladas"

# ajustes anadidos a mano: se conservan
EXTRA="$( [ -f "$HOST_ENV" ] && grep -E '^[A-Z_][A-Z0-9_]*=' "$HOST_ENV" | grep -vE '^(OCTOPUS_NATIVO|OCTOPUS_IP|OCTOPUS_PUBLIC_HOST|OCTOPUS_NOMBRES_EXTRA|OCTOPUS_BOVEDA_DIR|ADMIN_PORT)=' || true)"
cat > "$HOST_ENV.nuevo" <<EOF
# OCTOPUS - ajustes de este equipo (servidor nativo de Mac). Cambia y vuelve a ejecutar el instalador.
OCTOPUS_NATIVO=1
OCTOPUS_IP=$IP
OCTOPUS_PUBLIC_HOST=$(leer OCTOPUS_PUBLIC_HOST)
OCTOPUS_NOMBRES_EXTRA=$(leer OCTOPUS_NOMBRES_EXTRA)
OCTOPUS_BOVEDA_DIR=$BOVEDA
ADMIN_PORT=$PUERTO
$EXTRA
EOF
mv -f "$HOST_ENV.nuevo" "$HOST_ENV"
cat > "$R/arrancar_servidor.sh" <<'EOF'
#!/bin/bash
# OCTOPUS - arranca el servidor (lo lanza el servicio com.octopus.servidor al encender el Mac). No hace falta tocarlo.
R="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$R/datos/logs"
LOG="$R/datos/logs/servidor.log"
[ -f "$LOG" ] && [ "$(stat -f %z "$LOG")" -gt 10485760 ] && mv -f "$LOG" "$LOG.1"
while IFS='=' read -r k v; do
    case "$k" in ''|\#*) continue ;; esac
    v="$(printf '%s' "$v" | tr -d '\r"')"; [ -n "$v" ] && export "$k=$v"
done < "$R/install/.env"
export OCTOPUS_NATIVO=1 OCTOPUS_DATA="$R/datos" OCTOPUS_BIN="$R/bin"
export OCTOPUS_BOVEDA_DIR="${OCTOPUS_BOVEDA_DIR:-$R/boveda}" RESTIC_CACHE_DIR="$R/datos/.cache/restic"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LANG=es_ES.UTF-8 LC_ALL=es_ES.UTF-8
export PATH="$R/bin:$R/python/bin:/usr/bin:/bin:/usr/sbin:/sbin"
echo "===== $(date '+%F %T') arrancando OCTOPUS" >> "$LOG"
cd "$R" && exec "$R/python/bin/python3" "$R/lib/servidor.py" >> "$LOG" 2>&1
EOF
chmod 755 "$R/arrancar_servidor.sh" "$R/actualizador.sh" "$R/octopus.sh" 2>/dev/null
chown -R root:wheel "$R"
bien "archivos en su sitio"

# ------------------------------------------------------------------ servicio del sistema (arranca solo con el Mac)
paso "Dejando OCTOPUS en marcha (arranca solo al encender el Mac)"
parar
if lsof -nP -iTCP:"$PUERTO" -sTCP:LISTEN >/dev/null 2>&1; then
    QUIEN="$(lsof -nP -iTCP:"$PUERTO" -sTCP:LISTEN | awk 'NR==2{print $1}')"
    fallo "El puerto $PUERTO lo esta usando otro programa ($QUIEN). Si es la version antigua de OCTOPUS con Docker, parala (bash octopus.sh parar) y vuelve a ejecutar esto."
fi
plist() { # plist <archivo> <etiqueta> <script> <extra>
    cat > "$1" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$2</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$3</string></array>
  <key>WorkingDirectory</key><string>$R</string>
  $4
  <key>StandardOutPath</key><string>$R/datos/logs/$2.log</string>
  <key>StandardErrorPath</key><string>$R/datos/logs/$2.log</string>
</dict></plist>
EOF
    chown root:wheel "$1"; chmod 644 "$1"
}
PL=/Library/LaunchDaemons/com.octopus.servidor.plist
plist "$PL" com.octopus.servidor "$R/arrancar_servidor.sh" \
    "<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>30</integer>"
PLA=/Library/LaunchDaemons/com.octopus.actualizador.plist
plist "$PLA" com.octopus.actualizador "$R/actualizador.sh" "<key>StartInterval</key><integer>300</integer>"
launchctl bootout system/com.octopus.actualizador 2>/dev/null || true
launchctl bootstrap system "$PLA" 2>/dev/null || launchctl load -w "$PLA" 2>/dev/null || true
launchctl bootstrap system "$PL" 2>/dev/null || launchctl load -w "$PL" 2>/dev/null || true
launchctl enable system/com.octopus.servidor 2>/dev/null || true
launchctl kickstart -k system/com.octopus.servidor 2>/dev/null || true
OK=0
for _ in $(seq 1 120); do responde && { OK=1; break; }; sleep 2; done
if [ $OK = 0 ]; then
    tail -n 30 "$R/datos/logs/servidor.log" 2>/dev/null
    if [ $ya_estaba = 1 ] && [ -d "$R.anterior" ]; then
        # una actualizacion nunca debe dejar el servidor sin funcionar: se vuelve sola a la version anterior
        aviso "La version nueva no arranca bien: volviendo a la anterior automaticamente..."
        parar
        rsync -a "$R.anterior/" "$R/"
        launchctl bootstrap system "$PL" 2>/dev/null || true
        launchctl kickstart -k system/com.octopus.servidor 2>/dev/null || true
        for _ in $(seq 1 60); do responde && break; sleep 2; done
        responde && fallo "La version nueva no arrancaba y se ha vuelto a la anterior (todo sigue funcionando como antes). Manda el diagnostico al soporte."
    fi
    fallo "El panel no responde. Mira $R/datos/logs/servidor.log"
fi
bien "panel en marcha"

# ------------------------------------------------------------------ red y energia
paso "Red"
FW=/usr/libexec/ApplicationFirewall/socketfilterfw
if [ -x "$FW" ] && "$FW" --getglobalstate 2>/dev/null | grep -qi "enabled"; then
    for p in "$R"/python/bin/python3.* "$R/bin/rest-server"; do
        [ -f "$p" ] && { "$FW" --add "$p" >/dev/null 2>&1; "$FW" --unblockapp "$p" >/dev/null 2>&1; }
    done
    bien "Cortafuegos del Mac: permitido OCTOPUS (panel $PUERTO y almacen 8000)"
else
    bien "Cortafuegos del Mac desactivado: los puertos $PUERTO y 8000 ya son accesibles"
fi
# un servidor no debe dormirse: sin reposo mientras este enchufado (la pantalla si se apaga)
pmset -c sleep 0 >/dev/null 2>&1 && bien "Este Mac ya no entra en reposo mientras este enchufado (la pantalla se sigue apagando)"

CRED="$R/data/CREDENCIALES_INICIALES.txt"
echo
printf '\033[1;32m=== OCTOPUS instalado ===\033[0m\n'
echo "  Panel:        https://$IP:$PUERTO   (el navegador avisara del certificado propio la primera vez)"
echo "  Usuario:      admin"
[ -f "$CRED" ] && echo "  Contrasena:   $(grep -i 'contrasena' "$CRED" | cut -d: -f2- | xargs)   (un solo uso: el panel te pedira cambiarla)"
echo "  Copias en:    $BOVEDA"
echo "  Gestion:      sudo bash $R/octopus.sh (estado, logs, parar, arrancar, mantenimiento...)"
echo "  Arranca solo al encender el Mac, aunque nadie inicie sesion."
marca "---- instalacion terminada correctamente ----"
if [ $SIN_PREGUNTAS = 0 ] && [ -t 0 ] && [ -t 1 ]; then
    echo
    read -r -p "¿Busco ahora los equipos de la red para protegerlos? [S/n] " RESP || RESP=n
    case "${RESP:-s}" in
        [sS]*|"") bash "$R/octopus.sh" buscar-equipos ;;
        *) echo "Cuando quieras: botón «Buscar los equipos de la red» en el panel, o sudo bash $R/octopus.sh buscar-equipos" ;;
    esac
fi
if [ $SIN_PREGUNTAS = 0 ] && [ -n "${SUDO_USER:-}" ]; then
    launchctl asuser "$(id -u "$SUDO_USER")" sudo -u "$SUDO_USER" open "https://$IP:$PUERTO" 2>/dev/null || true
fi
exit 0
