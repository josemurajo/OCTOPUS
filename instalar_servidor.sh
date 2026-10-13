#!/bin/bash
# OCTOPUS Zero-Touch - Instalador del SERVIDOR para Linux (maquina recien instalada, sin nada)
#   Ubuntu 20.04+, Debian 11+, Rocky/Alma/RHEL 8+, Fedora, CentOS Stream
#
#   sudo bash instalar_servidor.sh                 instalar o actualizar
#   sudo OCTOPUS_IP=203.0.113.5 bash instalar_servidor.sh   fijar la direccion que usaran los equipos
#
# Instala Docker Engine (gratis, de codigo abierto) si no esta y arranca OCTOPUS en un contenedor.
# Volver a ejecutarlo actualiza a la version de esta carpeta sin perder datos ni copias.
set -euo pipefail
RAIZ="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
COMPOSE_FILE="$RAIZ/install/docker-compose.yml"
HOST_ENV="$RAIZ/install/.env"

PROGRESO="${OCTOPUS_PROGRESO:-/var/log/octopus/instalacion_progreso.txt}"   # banderines: cada paso con la hora (para saber donde se paro)
marca() { { mkdir -p "$(dirname "$PROGRESO")" && echo "[$(date '+%F %T')] $*" >> "$PROGRESO"; } 2>/dev/null || true; }
paso() { marca "==> $*"; echo; echo -e "\033[1;36m==> $*\033[0m"; }
bien() { marca "OK  $*"; echo -e "    \033[32m$*\033[0m"; }
aviso() { marca "..  $*"; echo -e "    \033[33m$*\033[0m"; }
fallo() { marca "ERROR $*"; echo -e "\n\033[1;31mERROR: $*\033[0m"; exit 1; }
[ "$(id -u)" -eq 0 ] || fallo "Ejecutalo con sudo: sudo bash $0"
[ -f "$COMPOSE_FILE" ] || fallo "No encuentro $COMPOSE_FILE: ejecuta el script desde la carpeta de OCTOPUS"

. /etc/os-release 2>/dev/null || true
echo -e "\033[1mOCTOPUS Zero-Touch - instalacion del servidor\033[0m   (${PRETTY_NAME:-Linux})"

# --------------------------------------------------------------------------- Docker
paso "Docker"
instalar_docker() {
    case "${ID:-} ${ID_LIKE:-}" in
        *ubuntu*|*debian*)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq ca-certificates curl >/dev/null
            if ! curl -fsSL https://get.docker.com | sh >/dev/null 2>&1; then
                aviso "El instalador oficial de Docker fallo; uso los paquetes de la distribucion"
                apt-get install -y -qq docker.io >/dev/null
                apt-get install -y -qq docker-compose-v2 >/dev/null 2>&1 || apt-get install -y -qq docker-compose-plugin >/dev/null 2>&1 || true
            fi ;;
        *fedora*)
            dnf -y -q install dnf-plugins-core >/dev/null
            dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo >/dev/null 2>&1 \
                || dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/fedora/docker-ce.repo >/dev/null
            dnf -y -q install docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null ;;
        *rhel*|*centos*|*rocky*|*almalinux*)
            dnf -y -q install dnf-plugins-core >/dev/null
            dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo >/dev/null
            dnf -y -q install docker-ce docker-ce-cli containerd.io docker-compose-plugin >/dev/null ;;
        *)
            curl -fsSL https://get.docker.com | sh || fallo "No se pudo instalar Docker en ${PRETTY_NAME:-este sistema}" ;;
    esac
}
if ! command -v docker >/dev/null 2>&1; then
    aviso "Instalando Docker Engine (1-3 minutos)..."
    instalar_docker
fi
systemctl enable --now docker >/dev/null 2>&1 || service docker start >/dev/null 2>&1 || true
for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done
docker info >/dev/null 2>&1 || fallo "Docker no arranca (systemctl status docker)"
docker compose version >/dev/null 2>&1 || fallo "Falta 'docker compose'. Instala el paquete docker-compose-plugin."
bien "$(docker --version)"

# --------------------------------------------------------------------------- direccion
paso "Direccion del servidor"
# Lee un ajuste de install/.env. En una maquina nueva el archivo aun no existe: devuelve vacio (nunca falla,
# porque con "set -e" un fallo aqui pararia el instalador sin decir nada).
leer() { [ -f "$HOST_ENV" ] || return 0; { grep -E "^$1=" "$HOST_ENV" 2>/dev/null || true; } | tail -1 | cut -d= -f2- | tr -d '\r"'; }
IP="${OCTOPUS_IP:-$(leer OCTOPUS_IP)}"
if [ -z "$IP" ]; then
    IP="$( { ip -4 route get 1.1.1.1 2>/dev/null || true; } | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
    [ -n "$IP" ] || IP="$( { hostname -I 2>/dev/null || true; } | awk '{print $1}')"
fi
[ -n "$IP" ] || fallo "No se pudo averiguar la IP. Ejecuta: sudo OCTOPUS_IP=<ip> bash $0"
bien "Los equipos llegaran al servidor por $IP (cambialo con OCTOPUS_IP=... si usas un nombre o IP publica)"

# --------------------------------------------------------------------------- instalacion anterior
paso "Comprobando instalaciones anteriores"
VOL_BOVEDA="$(leer OCTOPUS_VOLUMEN_BOVEDA)"
MIGRAR=0
if systemctl list-unit-files 2>/dev/null | grep -q '^octopus-panel'; then
    aviso "Instalacion antigua (sin contenedor) encontrada: se pasa al contenedor conservando todo"
    for u in octopus-panel octopus-api octopus-mantenimiento.timer octopus-mantenimiento octopus-firewall; do
        systemctl disable --now "$u" >/dev/null 2>&1 || true
        rm -f "/etc/systemd/system/$u" "/etc/systemd/system/$u.service"
    done
    systemctl daemon-reload
    [ -x "$RAIZ/install/firewall.sh" ] && bash "$RAIZ/install/firewall.sh" quitar >/dev/null 2>&1 || true
    MIGRAR=1
fi
for c in cerebro_boveda cerebro_wg_easy cerebro_n8n cerebro_minio; do
    docker rm -f "$c" >/dev/null 2>&1 && { aviso "Contenedor antiguo $c retirado (sus datos se conservan)"; MIGRAR=1; } || true
done
if [ -z "$VOL_BOVEDA" ] && docker volume inspect install_boveda_data >/dev/null 2>&1; then
    VOL_BOVEDA=install_boveda_data   # las copias de la version anterior se siguen usando tal cual
fi
VOL_BOVEDA="${VOL_BOVEDA:-octopus_boveda}"
bien "Almacen de copias: volumen $VOL_BOVEDA"

TZ_HOST="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo Europe/Madrid)"
P_PANEL="$(leer PANEL_PUERTO)"; P_ALM="$(leer ALMACEN_PUERTO)"
cat > "$HOST_ENV.tmp" <<EOF
# OCTOPUS - ajustes del anfitrion (los usa docker compose). Cambia y vuelve a ejecutar instalar_servidor.sh
OCTOPUS_IP=$IP
OCTOPUS_PUBLIC_HOST=${OCTOPUS_PUBLIC_HOST:-$(leer OCTOPUS_PUBLIC_HOST)}
OCTOPUS_NOMBRES_EXTRA=${OCTOPUS_NOMBRES_EXTRA:-$(leer OCTOPUS_NOMBRES_EXTRA)}
PANEL_PUERTO=${P_PANEL:-8080}
ALMACEN_PUERTO=${P_ALM:-8000}
TZ=$TZ_HOST
OCTOPUS_VOLUMEN_BOVEDA=$VOL_BOVEDA
OCTOPUS_VERSION=$(cat "$RAIZ/VERSION" 2>/dev/null || echo local)
EOF
mv "$HOST_ENV.tmp" "$HOST_ENV"
chmod 600 "$HOST_ENV"
DC=(docker compose --env-file "$HOST_ENV" -f "$COMPOSE_FILE")

# --------------------------------------------------------------------------- imagen
paso "Construyendo OCTOPUS (la primera vez tarda unos minutos)"
ANTERIOR="$(docker image inspect -f '{{.Id}}' "octopus-servidor:$(leer OCTOPUS_VERSION)" 2>/dev/null || true)"
[ -n "$ANTERIOR" ] && docker tag "$ANTERIOR" octopus-servidor:anterior >/dev/null 2>&1 || true
"${DC[@]}" build --pull >/dev/null || "${DC[@]}" build || fallo "No se pudo construir la imagen"
bien "imagen octopus-servidor:$(leer OCTOPUS_VERSION) lista"

if [ "$MIGRAR" = 1 ] && [ -f "$RAIZ/.env" ]; then
    paso "Pasando la configuracion antigua al contenedor"
    "${DC[@]}" run --rm --no-deps --entrypoint python -v "$RAIZ:/antiguo:ro" -v /root/.ssh:/sshantiguo:ro \
        octopus /app/lib/migrar.py
fi

# --------------------------------------------------------------------------- arranque
paso "Arrancando OCTOPUS"
"${DC[@]}" up -d --remove-orphans octopus
PUERTO="$(leer PANEL_PUERTO)"
for i in $(seq 1 90); do
    curl -fsk -m 3 "https://127.0.0.1:$PUERTO/login" >/dev/null 2>&1 && break
    docker inspect -f '{{.State.Running}}' octopus 2>/dev/null | grep -q true || { docker logs --tail 40 octopus; fallo "El contenedor se ha parado"; }
    sleep 2
done
curl -fsk -m 3 "https://127.0.0.1:$PUERTO/login" >/dev/null 2>&1 || { docker logs --tail 40 octopus; fallo "El panel no responde"; }
bien "panel en marcha"
curl -fsk -m 5 "https://127.0.0.1:$(leer ALMACEN_PUERTO)/" -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q '^[24]' \
    && bien "almacen de copias en marcha (HTTPS $(leer ALMACEN_PUERTO))" || aviso "El almacen no responde: docker logs octopus"

# --------------------------------------------------------------------------- cortafuegos del anfitrion
# Solo los dos puertos de OCTOPUS (TCP). Si el sistema no tiene cortafuegos activo no se toca nada.
P_A="$(leer ALMACEN_PUERTO)"
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd -q --permanent --add-port="$PUERTO/tcp" --add-port="$P_A/tcp" && firewall-cmd -q --reload \
        && bien "cortafuegos (firewalld): abiertos $PUERTO y $P_A" || aviso "No se pudieron abrir los puertos en firewalld"
elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "$PUERTO/tcp" >/dev/null && ufw allow "$P_A/tcp" >/dev/null \
        && bien "cortafuegos (ufw): abiertos $PUERTO y $P_A" || aviso "No se pudieron abrir los puertos en ufw"
fi

CRED="$RAIZ/CREDENCIALES_INICIALES.txt"
if docker exec octopus test -f /data/panel/CREDENCIALES_INICIALES.txt; then
    docker exec octopus cat /data/panel/CREDENCIALES_INICIALES.txt > "$CRED"; chmod 600 "$CRED"
fi
if [ -n "${OCTOPUS_RUNTIME_DIR:-}" ]; then   # laboratorio: copia de las credenciales y de la config de agentes
    mkdir -p "$OCTOPUS_RUNTIME_DIR"
    [ -f "$CRED" ] && cp "$CRED" "$OCTOPUS_RUNTIME_DIR/"
    docker exec octopus cat /data/ansible/config.json > "$OCTOPUS_RUNTIME_DIR/agent_config.json" 2>/dev/null || true
fi

echo
echo -e "\033[1;32m=== OCTOPUS instalado ===\033[0m"
echo "  Panel:        https://$IP:$PUERTO   (el navegador avisara del certificado propio la primera vez)"
echo "  Usuario:      admin"
[ -f "$CRED" ] && echo "  Contrasena:   en $CRED (un solo uso; borralo despues de entrar)"
echo "  Puertos:      $PUERTO (panel) y $(leer ALMACEN_PUERTO) (almacen), TCP. Para equipos fuera de la oficina,"
echo "                abrelos en el router, pon el nombre publico en OCTOPUS_PUBLIC_HOST (install/.env) y vuelve a ejecutar esto"
echo "  Gestion:      sudo bash $RAIZ/octopus.sh ayuda"
