#!/bin/bash
# OCTOPUS Zero-Touch - Instalador del SERVIDOR para macOS 13 (Ventura) o posterior, Intel y Apple Silicon
#
#   bash instalar_servidor_mac.sh                     instalar o actualizar (con tu usuario, NO con sudo)
#   OCTOPUS_IP=192.168.1.10 bash instalar_servidor_mac.sh
#
# Instala con Homebrew (si falta, lo instala tambien) Colima + Docker: gratis y de codigo abierto, sin
# Docker Desktop. Colima arranca solo al iniciar sesion. Despues arranca OCTOPUS en un contenedor (el mismo
# que en Linux) y comprueba que los equipos de la red llegan a los puertos 8080 y 8000; si Docker solo
# escucha en este Mac, crea un reenvio (socat) que arranca solo.
# Volver a ejecutarlo actualiza a la version de esta carpeta sin perder datos ni copias.
set -uo pipefail
RAIZ="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$RAIZ/install/docker-compose.yml"
HOST_ENV="$RAIZ/install/.env"

PROGRESO="${OCTOPUS_PROGRESO:-$HOME/Library/Logs/OCTOPUS/instalacion_progreso.txt}"   # banderines: cada paso con la hora (para saber donde se paro)
marca() { { mkdir -p "$(dirname "$PROGRESO")" && echo "[$(date '+%F %T')] $*" >> "$PROGRESO"; } 2>/dev/null || true; }
paso() { marca "==> $*"; echo; printf '\033[1;36m==> %s\033[0m\n' "$*"; }
bien() { marca "OK  $*"; printf '    \033[32m%s\033[0m\n' "$*"; }
aviso() { marca "..  $*"; printf '    \033[33m%s\033[0m\n' "$*"; }
fallo() { marca "ERROR $*"; printf '\n\033[1;31mERROR: %s\033[0m\n' "$*"; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fallo "Este instalador es para Mac. En Linux: sudo bash instalar_servidor.sh"
[ "$(id -u)" -ne 0 ] || fallo "Ejecutalo con tu usuario, sin sudo (Homebrew no funciona como root): bash $0"
[ -f "$COMPOSE_FILE" ] || fallo "No encuentro $COMPOSE_FILE: ejecuta el script desde la carpeta de OCTOPUS"
MAYOR="$(sw_vers -productVersion | cut -d. -f1)"
[ "$MAYOR" -ge 13 ] 2>/dev/null || fallo "Hace falta macOS 13 (Ventura) o posterior."
printf '\033[1mOCTOPUS Zero-Touch - instalacion del servidor en Mac\033[0m   (macOS %s, %s)\n' "$(sw_vers -productVersion)" "$(uname -m)"

# ------------------------------------------------------------------ Homebrew, Colima y Docker
paso "Docker (Colima)"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
if ! command -v brew >/dev/null 2>&1; then
    aviso "Instalando Homebrew (pedira la contrasena de este Mac)..."
    sudo -v || fallo "Hace falta un usuario administrador"
    NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
        || fallo "No se pudo instalar Homebrew"
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
fi
command -v brew >/dev/null 2>&1 || fallo "Homebrew no esta disponible"
for p in colima docker docker-compose docker-buildx socat; do
    brew list --formula "$p" >/dev/null 2>&1 || { aviso "Instalando $p..."; brew install -q "$p" >/dev/null || fallo "No se pudo instalar $p"; }
done
# docker compose / buildx como complementos de docker
mkdir -p "$HOME/.docker"
python3 - "$HOME/.docker/config.json" "$(brew --prefix)/lib/docker/cli-plugins" <<'PYEOF' 2>/dev/null || true
import json, os, sys
f, d = sys.argv[1], sys.argv[2]
cfg = json.load(open(f)) if os.path.isfile(f) else {}
dirs = cfg.setdefault("cliPluginsExtraDirs", [])
if d not in dirs:
    dirs.append(d)
json.dump(cfg, open(f, "w"), indent=2)
PYEOF
if ! docker info >/dev/null 2>&1; then
    aviso "Arrancando Colima (la primera vez descarga una maquina virtual pequena: 2-5 minutos)..."
    colima start --cpu 2 --memory 4 --disk 100 >/dev/null 2>&1 || colima start >/dev/null 2>&1 || fallo "Colima no arranca (colima status)"
fi
brew services start colima >/dev/null 2>&1 || true   # que arranque solo al iniciar sesion
for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 3; done
docker info >/dev/null 2>&1 || fallo "Docker no responde (colima status)"
docker compose version >/dev/null 2>&1 || fallo "Falta 'docker compose' (brew install docker-compose)"
bien "$(docker version --format 'Docker {{.Server.Version}}' 2>/dev/null) con Colima"

# ------------------------------------------------------------------ direccion
paso "Direccion del servidor"
leer() { [ -f "$HOST_ENV" ] || return 0; { grep -E "^$1=" "$HOST_ENV" 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d '\r"'; }
IP="${OCTOPUS_IP:-$(leer OCTOPUS_IP)}"
if [ -z "$IP" ]; then
    IF="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
    IP="$(ipconfig getifaddr "${IF:-en0}" 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
fi
[ -n "$IP" ] || fallo "No se pudo averiguar la IP. Ejecuta: OCTOPUS_IP=<ip> bash $0"
bien "Los equipos llegaran al servidor por $IP (cambialo con OCTOPUS_IP=... si usas otra IP o un nombre)"
TZ_HOST="$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||')"
P_PANEL="$(leer PANEL_PUERTO)"; P_ALM="$(leer ALMACEN_PUERTO)"; VOL="$(leer OCTOPUS_VOLUMEN_BOVEDA)"
cat > "$HOST_ENV.tmp" <<EOF
# OCTOPUS - ajustes del anfitrion (los usa docker compose). Cambia y vuelve a ejecutar el instalador
OCTOPUS_IP=$IP
OCTOPUS_PUBLIC_HOST=${OCTOPUS_PUBLIC_HOST:-$(leer OCTOPUS_PUBLIC_HOST)}
OCTOPUS_NOMBRES_EXTRA=${OCTOPUS_NOMBRES_EXTRA:-$(leer OCTOPUS_NOMBRES_EXTRA)}
PANEL_PUERTO=${P_PANEL:-8080}
ALMACEN_PUERTO=${P_ALM:-8000}
TZ=${TZ_HOST:-Europe/Madrid}
OCTOPUS_VOLUMEN_BOVEDA=${VOL:-octopus_boveda}
OCTOPUS_VERSION=$(cat "$RAIZ/VERSION" 2>/dev/null || echo local)
EOF
mv "$HOST_ENV.tmp" "$HOST_ENV"; chmod 600 "$HOST_ENV"
DC=(docker compose --env-file "$HOST_ENV" -f "$COMPOSE_FILE")
PUERTO="$(leer PANEL_PUERTO)"; P_A="$(leer ALMACEN_PUERTO)"

# ------------------------------------------------------------------ imagen y arranque
paso "Construyendo OCTOPUS (la primera vez tarda unos minutos)"
ANTERIOR="$(docker image inspect -f '{{.Id}}' "octopus-servidor:$(leer OCTOPUS_VERSION)" 2>/dev/null || true)"
[ -n "$ANTERIOR" ] && docker tag "$ANTERIOR" octopus-servidor:anterior >/dev/null 2>&1 || true
"${DC[@]}" build --pull >/dev/null || "${DC[@]}" build || fallo "No se pudo construir la imagen"
paso "Arrancando OCTOPUS"
"${DC[@]}" up -d --remove-orphans octopus || fallo "No se pudo arrancar el contenedor"
for i in $(seq 1 90); do
    curl -fsk -m 3 "https://127.0.0.1:$PUERTO/login" >/dev/null 2>&1 && break
    sleep 2
done
if ! curl -fsk -m 3 "https://127.0.0.1:$PUERTO/login" >/dev/null 2>&1; then
    docker logs --tail 40 octopus
    # Una actualizacion nunca debe dejar el servidor sin funcionar: se vuelve sola a la version anterior
    if [ -n "${ANTERIOR:-}" ] && docker image inspect octopus-servidor:anterior >/dev/null 2>&1; then
        aviso "La version nueva no arranca bien: volviendo a la anterior automaticamente..."
        sed -i.bak 's/^OCTOPUS_VERSION=.*/OCTOPUS_VERSION=anterior/' "$HOST_ENV"
        "${DC[@]}" up -d --no-build octopus >/dev/null 2>&1
        sleep 20
        curl -fsk -m 5 "https://127.0.0.1:$PUERTO/login" >/dev/null 2>&1 \
            && fallo "La version nueva no arrancaba y se ha vuelto a la anterior (todo sigue funcionando como antes). Manda el diagnostico al soporte." \
            || fallo "El panel no responde ni con la version anterior. Mira  sudo bash octopus.sh logs"
    fi
    fallo "El panel no responde"
fi
bien "panel en marcha"

# ------------------------------------------------------------------ red
paso "Red"
SOCAT="$(brew --prefix)/bin/socat"
for p in "$PUERTO" "$P_A"; do
    if nc -z -G 3 "$IP" "$p" >/dev/null 2>&1; then
        bien "puerto $p accesible por $IP"
        continue
    fi
    # Docker solo escucha en 127.0.0.1: reenvio IP:puerto -> 127.0.0.1:puerto que arranca solo con la sesion
    PL="$HOME/Library/LaunchAgents/com.octopus.reenvio-$p.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    launchctl unload "$PL" >/dev/null 2>&1 || true
    cat > "$PL" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.octopus.reenvio-$p</string>
  <key>ProgramArguments</key><array>
    <string>$SOCAT</string><string>TCP-LISTEN:$p,bind=$IP,fork,reuseaddr</string><string>TCP:127.0.0.1:$p</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
EOF
    launchctl load -w "$PL" >/dev/null 2>&1
    sleep 2
    if nc -z -G 3 "$IP" "$p" >/dev/null 2>&1; then bien "puerto $p reenviado a Docker (socat)"
    else aviso "No se llega al puerto $p por $IP: revisa el cortafuegos (Ajustes -> Red -> Cortafuegos)"; fi
done
if /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null | grep -qi "enabled"; then
    aviso "El cortafuegos de macOS esta activado: si los equipos no conectan, permite 'socat' y 'colima' en"
    aviso "Ajustes del Sistema -> Red -> Cortafuegos -> Opciones."
fi

# --------------------------------------------------------------------------- actualizador seguro (a distancia)
if [ "${OCTOPUS_SIN_ACTUALIZADOR:-0}" != 1 ]; then
    PLA="$HOME/Library/LaunchAgents/com.octopus.actualizador.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLA" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.octopus.actualizador</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$RAIZ/octopus.sh</string><string>actualizar-pedido</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(brew --prefix)/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StartInterval</key><integer>300</integer>
</dict></plist>
PL
    launchctl unload "$PLA" >/dev/null 2>&1 || true
    launchctl load -w "$PLA" >/dev/null 2>&1 && bien "actualizador seguro activado (Ajustes -> Actualizaciones en el panel)" \
        || aviso "No se pudo activar el actualizador a distancia (se puede actualizar a mano con octopus.sh actualizar)"
fi

CRED="$RAIZ/CREDENCIALES_INICIALES.txt"
if docker exec octopus test -f /data/panel/CREDENCIALES_INICIALES.txt 2>/dev/null; then
    docker exec octopus cat /data/panel/CREDENCIALES_INICIALES.txt > "$CRED"; chmod 600 "$CRED"
fi
echo
printf '\033[1;32m=== OCTOPUS instalado ===\033[0m\n'
echo "  Panel:        https://$IP:$PUERTO   (el navegador avisara del certificado propio la primera vez)"
echo "  Usuario:      admin"
[ -f "$CRED" ] && echo "  Contrasena:   en $CRED (un solo uso; borralo despues de entrar)"
echo "  Gestion:      bash $RAIZ/octopus.sh ayuda"
echo "  IMPORTANTE:   este Mac tiene que quedarse encendido y con la sesion iniciada (Colima arranca al"
echo "                iniciar sesion). Ajustes -> Pantalla de bloqueo / Energia: que no entre en reposo."
