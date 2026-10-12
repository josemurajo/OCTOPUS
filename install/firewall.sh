#!/bin/bash
# OCTOPUS Zero-Touch - Cortafuegos del servidor (se aplica al instalar y en cada arranque).
#
#   Abierto a la red :  SSH, panel web (8080/tcp) y tunel WireGuard (51820/udp)
#   Almacen (8000)   :  solo desde el tunel 10.8.0.0/24 y desde OCTOPUS_STORAGE_ALLOW
#   Todo lo demas    :  cerrado (n8n, gestion de WireGuard y la API solo escuchan en el propio servidor)
#
# Variables en .env:
#   OCTOPUS_FIREWALL=0                 no tocar el cortafuegos (si ya gestionas el tuyo)
#   OCTOPUS_PANEL_ALLOW=10.0.0.0/8     redes desde las que se puede abrir el panel (por defecto, todas)
#   OCTOPUS_STORAGE_ALLOW=192.168.1.0/24  redes extra que pueden dejar copias sin tunel
#
# Uso: sudo bash install/firewall.sh [aplicar|quitar|estado]
set -uo pipefail
ROOT="$(cd "$(dirname "$(realpath "$0")")/.." && pwd)"
ENV_FILE="$ROOT/.env"
val() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r"'"'"; }

ACCION="${1:-aplicar}"
[ "$(val OCTOPUS_FIREWALL)" = "0" ] && [ "$ACCION" = aplicar ] && { echo "Cortafuegos desactivado en .env (OCTOPUS_FIREWALL=0)"; exit 0; }

PANEL_PORT="$(val ADMIN_PORT)"; PANEL_PORT="${PANEL_PORT:-8080}"
TUNEL="10.8.0.0/24"
PANEL_ALLOW="$(val OCTOPUS_PANEL_ALLOW | tr ',' ' ')"
STORAGE_ALLOW="$(val OCTOPUS_STORAGE_ALLOW | tr ',' ' ')"
SSH_PORTS="$(ss -tlnpH 2>/dev/null | awk '/sshd/ {n=split($4,a,":"); print a[n]}' | sort -u | tr '\n' ' ')"
SSH_PORTS="${SSH_PORTS:-22}"

almacen_docker() {
    command -v iptables >/dev/null 2>&1 || return 0
    iptables -L DOCKER-USER -n >/dev/null 2>&1 || { echo "  (Docker aun no ha creado DOCKER-USER; se aplicara al arrancar)"; return 0; }
    iptables -N OCTOPUS-BOVEDA 2>/dev/null || iptables -F OCTOPUS-BOVEDA
    iptables -A OCTOPUS-BOVEDA -s "$TUNEL" -j RETURN
    for c in $STORAGE_ALLOW; do iptables -A OCTOPUS-BOVEDA -s "$c" -j RETURN; done
    iptables -A OCTOPUS-BOVEDA -j DROP
    local regla=(-p tcp -m conntrack --ctorigdstport 8000 --ctstate NEW -j OCTOPUS-BOVEDA)
    iptables -C DOCKER-USER "${regla[@]}" 2>/dev/null || iptables -I DOCKER-USER 1 "${regla[@]}"
    echo "  Almacen (8000): solo desde $TUNEL ${STORAGE_ALLOW:+y $STORAGE_ALLOW}"
}

quitar_almacen() {
    iptables -D DOCKER-USER -p tcp -m conntrack --ctorigdstport 8000 --ctstate NEW -j OCTOPUS-BOVEDA 2>/dev/null
    iptables -F OCTOPUS-BOVEDA 2>/dev/null; iptables -X OCTOPUS-BOVEDA 2>/dev/null
    true
}

case "$ACCION" in
aplicar)
    echo "Cortafuegos OCTOPUS:"
    if command -v ufw >/dev/null 2>&1; then
        for p in $SSH_PORTS; do ufw allow "$p/tcp" comment 'SSH' >/dev/null; done
        ufw allow 51820/udp comment 'OCTOPUS tunel WireGuard' >/dev/null
        if [ -n "$PANEL_ALLOW" ]; then
            for c in $PANEL_ALLOW; do ufw allow from "$c" to any port "$PANEL_PORT" proto tcp comment 'OCTOPUS panel' >/dev/null; done
        else
            ufw allow "$PANEL_PORT/tcp" comment 'OCTOPUS panel' >/dev/null
        fi
        # el panel tambien desde el tunel (los equipos avisan de ataques por ahi)
        ufw allow in on wg0 to any port "$PANEL_PORT" proto tcp comment 'OCTOPUS panel por tunel' >/dev/null
        ufw default deny incoming >/dev/null; ufw default allow outgoing >/dev/null
        ufw --force enable >/dev/null
        echo "  ufw activo: SSH ($SSH_PORTS), panel $PANEL_PORT/tcp${PANEL_ALLOW:+ desde $PANEL_ALLOW}, tunel 51820/udp"
    elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        for p in $SSH_PORTS; do firewall-cmd -q --permanent --add-port="$p/tcp"; done
        firewall-cmd -q --permanent --add-port=51820/udp
        firewall-cmd -q --permanent --add-port="$PANEL_PORT/tcp"
        firewall-cmd -q --permanent --zone=trusted --add-interface=wg0 2>/dev/null || true
        firewall-cmd -q --reload
        echo "  firewalld: SSH ($SSH_PORTS), panel $PANEL_PORT/tcp, tunel 51820/udp"
    else
        echo "  AVISO: no hay ufw ni firewalld; solo se protege el almacen. Instala ufw para cerrar el resto."
    fi
    almacen_docker ;;
quitar)
    quitar_almacen
    echo "Regla del almacen quitada (ufw/firewalld se dejan como estan)" ;;
estado)
    command -v ufw >/dev/null 2>&1 && ufw status verbose
    iptables -L OCTOPUS-BOVEDA -n -v 2>/dev/null ;;
*) echo "uso: $0 aplicar|quitar|estado"; exit 1 ;;
esac
