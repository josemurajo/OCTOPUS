#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS Zero-Touch - Instalador del agente para Linux (Debian/Ubuntu, RHEL/Rocky/Alma/Fedora)
# Uso:  sudo bash instalar_linux.sh            (instalar o actualizar)
#       sudo bash instalar_linux.sh --quitar   (desinstalar; las copias del servidor NO se borran)
#
# Hace lo mismo que el despliegue con Ansible (ansible/desplegar_agentes.yml) para un solo equipo.
set -euo pipefail
AQUI="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
DIR=/opt/zerotouch
RESTIC_VER=0.16.4

PROGRESO="${OCTOPUS_PROGRESO:-/var/log/octopus/instalacion_agente_progreso.txt}"   # banderines: cada paso con la hora (para saber donde se paro)
marca() { { mkdir -p "$(dirname "$PROGRESO")" && echo "[$(date '+%F %T')] $*" >> "$PROGRESO"; } 2>/dev/null || true; }
paso() { marca "==> $*"; echo; echo -e "\033[1;36m==> $*\033[0m"; }
bien() { marca "OK  $*"; echo -e "    \033[32m$*\033[0m"; }
fallo() { marca "ERROR $*"; echo -e "\n\033[1;31mERROR: $*\033[0m"; exit 1; }
[ "$(id -u)" -eq 0 ] || fallo "Ejecutalo con sudo: sudo bash $0"

if [ "${1:-}" = "--quitar" ]; then
    paso "Quitando OCTOPUS"
    systemctl disable --now octopus-agent 2>/dev/null || true
    systemctl disable --now wg-quick@octopus 2>/dev/null || true
    rm -f /etc/systemd/system/octopus-agent.service /etc/cron.d/octopus /etc/wireguard/octopus.conf
    rm -rf "$DIR/zerotouch_agent.py" "$DIR/octopus_monitor.py" /etc/octopus
    # por si estaba aislado por un incidente
    nft delete table inet octopus 2>/dev/null || true
    iptables -D OUTPUT -j OCTOPUS_OUT 2>/dev/null || true; iptables -D INPUT -j OCTOPUS_IN 2>/dev/null || true
    systemctl daemon-reload
    bien "OCTOPUS se ha quitado. Las copias del servidor siguen alli."
    exit 0
fi

for f in zerotouch_agent.py config.json; do [ -f "$AQUI/$f" ] || fallo "Falta $f junto a este script. Descarga de nuevo el instalador desde el panel."; done
NOMBRE=$(sed -n 's/.*"hostname"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$AQUI/config.json" | head -1)   # sin python (aun puede no estar)
[ -n "$NOMBRE" ] || fallo "config.json no tiene el nombre del equipo. Descarga de nuevo el instalador desde el panel."
[ "$NOMBRE" = "$(hostname -s)" ] || { echo "AVISO: el paquete es para '$NOMBRE' y este equipo se llama '$(hostname -s)'. Las copias usaran '$NOMBRE'."; sleep 5; }
TUNEL=0; [ -f "$AQUI/octopus.conf" ] && TUNEL=1

paso "Paquetes necesarios"
if command -v apt-get >/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq || true
    apt-get install -y -qq python3 curl bzip2 iputils-ping $([ $TUNEL = 1 ] && echo wireguard-tools) >/dev/null
    # salud de los discos para la monitorizacion (sin paquetes recomendados: nada de servidores de correo); si no se puede, sigue
    apt-get install -y -qq --no-install-recommends smartmontools >/dev/null 2>&1 || true
elif command -v dnf >/dev/null; then
    dnf install -y -q python3 curl bzip2 iputils $([ $TUNEL = 1 ] && echo wireguard-tools) >/dev/null
    dnf install -y -q --setopt=install_weak_deps=False smartmontools >/dev/null 2>&1 || true
else
    fallo "Distribucion no soportada (hace falta apt o dnf)"
fi
bien "listo"

paso "Motor de copias (restic)"
if ! command -v restic >/dev/null && [ ! -x /usr/local/bin/restic ]; then
    curl -fsSL "https://github.com/restic/restic/releases/download/v${RESTIC_VER}/restic_${RESTIC_VER}_linux_amd64.bz2" \
        | bunzip2 > /usr/local/bin/restic.tmp && install -m 0755 /usr/local/bin/restic.tmp /usr/local/bin/restic \
        || { rm -f /usr/local/bin/restic.tmp; apt-get install -y -qq restic 2>/dev/null || dnf install -y -q restic; }
    rm -f /usr/local/bin/restic.tmp
fi
bien "$(restic version 2>/dev/null || /usr/local/bin/restic version)"

if [ $TUNEL = 1 ]; then
    paso "Tunel cifrado con el servidor (WireGuard)"
    install -m 0600 "$AQUI/octopus.conf" /etc/wireguard/octopus.conf
    systemctl enable wg-quick@octopus >/dev/null 2>&1
    systemctl restart wg-quick@octopus
    for i in $(seq 1 15); do ping -c1 -W2 10.8.0.1 >/dev/null 2>&1 && break; sleep 2; done
    ping -c1 -W2 10.8.0.1 >/dev/null 2>&1 || fallo "El tunel no conecta. Comprueba que el puerto UDP 51820 del servidor es accesible."
    bien "tunel activo: el servidor responde en 10.8.0.1"
fi

paso "Agente OCTOPUS"
mkdir -p "$DIR" /etc/octopus /var/log/octopus
install -m 0755 "$AQUI/zerotouch_agent.py" "$DIR/zerotouch_agent.py"
[ -f "$AQUI/octopus_monitor.py" ] && install -m 0644 "$AQUI/octopus_monitor.py" "$DIR/octopus_monitor.py"
install -m 0600 "$AQUI/config.json" /etc/octopus/config.json
cat > /etc/systemd/system/octopus-agent.service <<EOF
[Unit]
Description=OCTOPUS Zero-Touch Agent
After=network-online.target$([ $TUNEL = 1 ] && echo " wg-quick@octopus.service")
Wants=network-online.target$([ $TUNEL = 1 ] && echo " wg-quick@octopus.service")

[Service]
Type=simple
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
Environment=OCTOPUS_CONFIG=/etc/octopus/config.json
ExecStart=/usr/bin/python3 $DIR/zerotouch_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
echo "0 20 * * * root /usr/bin/python3 $DIR/zerotouch_agent.py --copia >/dev/null 2>&1" > /etc/cron.d/octopus
chmod 644 /etc/cron.d/octopus
# El equipo no abre ningun puerto: el agente se conecta el al servidor por HTTPS (9999 solo en 127.0.0.1)
systemctl daemon-reload
systemctl enable octopus-agent >/dev/null 2>&1
systemctl restart octopus-agent
for i in $(seq 1 20); do curl -fs -m 3 http://127.0.0.1:9999/health >/dev/null && break; sleep 2; done
curl -fs -m 3 http://127.0.0.1:9999/health >/dev/null || fallo "El agente no arranca: journalctl -u octopus-agent"
bien "agente en marcha (arranca solo con el equipo)"

paso "Primera copia de seguridad"
( /usr/bin/python3 "$DIR/zerotouch_agent.py" --copia >/dev/null 2>&1 & )
bien "en marcha en segundo plano; despues, una copia cada dia a las 20:00"
echo
echo -e "\033[1;32mOCTOPUS instalado. En el panel este equipo aparecera como protegido en unos minutos.\033[0m"
echo -e "\033[1;33mIMPORTANTE: borra ahora esta carpeta y el .zip (contienen claves).\033[0m"
