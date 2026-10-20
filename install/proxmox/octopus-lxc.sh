#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
#
# OCTOPUS en Proxmox VE, en un solo paso: crea un contenedor LXC con Debian 12, le pone Docker y arranca OCTOPUS.
#
#   En la consola de Proxmox (el nodo > Shell), pega:
#     bash -c "$(curl -fsSL https://raw.githubusercontent.com/josemurajo/OCTOPUS/main/install/proxmox/octopus-lxc.sh)"
#
# Te hace 3 preguntas (pulsa Enter para aceptar lo que sale entre corchetes) y al terminar te dice la dirección
# del panel y la primera contraseña. No toca ninguna otra máquina ni contenedor de tu Proxmox.
#
# Sin preguntas (para automatizar):  OCTOPUS_SIN_PREGUNTAS=1 OCTOPUS_DISCO=100 bash octopus-lxc.sh
#   OCTOPUS_CTID     número del contenedor          (por defecto: el siguiente libre)
#   OCTOPUS_DISCO    tamaño del disco en GB          (por defecto: 64; ahí van las copias)
#   OCTOPUS_ALMACEN  almacenamiento de Proxmox       (por defecto: el primero que admite contenedores)
#   OCTOPUS_PUENTE   puente de red                   (por defecto: vmbr0, dirección por DHCP)
#   OCTOPUS_RAM      memoria en MB                   (por defecto: 2048)
set -euo pipefail

COMPOSE_URL="${OCTOPUS_COMPOSE_URL:-https://raw.githubusercontent.com/josemurajo/OCTOPUS/main/install/nas/docker-compose.yml}"
PLANTILLA_PATRON="${OCTOPUS_PLANTILLA:-debian-12-standard}"

paso()  { echo; echo -e "\033[1;36m==> $*\033[0m"; }
bien()  { echo -e "    \033[32m$*\033[0m"; }
fallo() { echo -e "\n\033[1;31mERROR: $*\033[0m"; exit 1; }
preguntar() {   # preguntar VARIABLE "texto" "por defecto"
    local var="$1" texto="$2" def="$3" resp=""
    if [ -n "${!var:-}" ]; then return; fi
    if [ -n "${OCTOPUS_SIN_PREGUNTAS:-}" ] || [ ! -t 0 ]; then printf -v "$var" '%s' "$def"; return; fi
    read -r -p "    $texto [$def]: " resp || true
    printf -v "$var" '%s' "${resp:-$def}"
}

echo -e "\033[1mOCTOPUS Zero-Touch - instalación en Proxmox VE\033[0m"
[ "$(id -u)" -eq 0 ] || fallo "Ejecútalo como root en la consola de Proxmox (el nodo > Shell)."
command -v pct >/dev/null 2>&1 && command -v pveam >/dev/null 2>&1 \
    || fallo "Esto no parece un Proxmox VE (no encuentro 'pct'). Ejecútalo en la consola del nodo de Proxmox."

# --------------------------------------------------------------------------- preguntas
paso "Tres preguntas (Enter = aceptar)"
SIGUIENTE="$(pvesh get /cluster/nextid 2>/dev/null || echo 900)"
ALMACEN_DEF="$(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}')"
[ -n "$ALMACEN_DEF" ] || fallo "No encuentro un almacenamiento de Proxmox que admita contenedores (Datacenter > Storage)."
preguntar OCTOPUS_CTID "Número del contenedor" "$SIGUIENTE"
preguntar OCTOPUS_DISCO "Espacio para las copias, en GB" "64"
preguntar OCTOPUS_ALMACEN "Almacenamiento de Proxmox donde crearlo" "$ALMACEN_DEF"
OCTOPUS_PUENTE="${OCTOPUS_PUENTE:-vmbr0}"
OCTOPUS_RAM="${OCTOPUS_RAM:-2048}"
[[ "$OCTOPUS_CTID" =~ ^[0-9]+$ ]] || fallo "El número del contenedor tiene que ser un número (por ejemplo $SIGUIENTE)."
[[ "$OCTOPUS_DISCO" =~ ^[0-9]+$ ]] && [ "$OCTOPUS_DISCO" -ge 8 ] || fallo "El espacio tiene que ser un número de GB, 8 o más."
if pct status "$OCTOPUS_CTID" >/dev/null 2>&1; then
    fallo "Ya existe un contenedor con el número $OCTOPUS_CTID. No lo toco: elige otro número."
fi
bien "Contenedor $OCTOPUS_CTID, ${OCTOPUS_DISCO} GB en '$OCTOPUS_ALMACEN', red $OCTOPUS_PUENTE (DHCP)"

# --------------------------------------------------------------------------- plantilla Debian
paso "Plantilla Debian 12"
pveam update >/dev/null 2>&1 || true
PLANTILLA="$(pveam available --section system 2>/dev/null | awk '{print $2}' | grep "^${PLANTILLA_PATRON}" | sort -V | tail -1)"
[ -n "$PLANTILLA" ] || fallo "No encuentro la plantilla ${PLANTILLA_PATRON} (¿tiene Internet el Proxmox?)."
ALMACEN_PLANTILLAS="$(pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}')"
[ -n "$ALMACEN_PLANTILLAS" ] || fallo "Ningún almacenamiento admite plantillas (activa 'Container template' en 'local')."
if ! pveam list "$ALMACEN_PLANTILLAS" 2>/dev/null | grep -q "$PLANTILLA"; then
    pveam download "$ALMACEN_PLANTILLAS" "$PLANTILLA" >/dev/null || fallo "No se pudo descargar $PLANTILLA"
fi
bien "$PLANTILLA"

# --------------------------------------------------------------------------- contenedor
paso "Creando el contenedor"
# Sin privilegios (más seguro) y con 'nesting' + 'keyctl', que es lo que necesita Docker dentro de un LXC.
pct create "$OCTOPUS_CTID" "${ALMACEN_PLANTILLAS}:vztmpl/${PLANTILLA}" \
    --hostname octopus --description "OCTOPUS Zero-Touch - copias de seguridad (https://github.com/josemurajo/OCTOPUS)" \
    --unprivileged 1 --features nesting=1,keyctl=1 \
    --cores 2 --memory "$OCTOPUS_RAM" --swap 512 \
    --rootfs "${OCTOPUS_ALMACEN}:${OCTOPUS_DISCO}" \
    --net0 "name=eth0,bridge=${OCTOPUS_PUENTE},ip=dhcp" \
    --onboot 1 --start 1 >/dev/null || fallo "Proxmox no pudo crear el contenedor"
bien "creado y encendido (arrancará solo cuando reinicies Proxmox)"

dentro() { pct exec "$OCTOPUS_CTID" -- bash -c "$1"; }
IP=""
for _ in $(seq 1 60); do
    IP="$(dentro "hostname -I 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true)"
    [ -n "$IP" ] && dentro "getent hosts deb.debian.org >/dev/null" 2>/dev/null && break
    sleep 2
done
[ -n "$IP" ] || fallo "El contenedor no recibe dirección de red. Mira que el puente $OCTOPUS_PUENTE tenga DHCP."
bien "dirección del contenedor: $IP"

# --------------------------------------------------------------------------- Docker y OCTOPUS
paso "Instalando Docker (1-3 minutos)"
dentro "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null \
        && curl -fsSL https://get.docker.com | sh >/dev/null 2>&1 && systemctl enable --now docker >/dev/null 2>&1" \
    || fallo "No se pudo instalar Docker dentro del contenedor"
bien "Docker listo"

paso "Arrancando OCTOPUS"
ZONA="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo Europe/Madrid)"
[[ "$ZONA" =~ ^[A-Za-z0-9_/+-]+$ ]] || ZONA=Europe/Madrid
dentro "mkdir -p /opt/octopus && cd /opt/octopus && curl -fsSL '$COMPOSE_URL' -o docker-compose.yml \
        && sed -i 's/OCTOPUS_IP=.*/OCTOPUS_IP=$IP/' docker-compose.yml \
        && sed -i 's|TZ=.*|TZ=$ZONA|' docker-compose.yml \
        && docker compose up -d >/dev/null 2>&1" || fallo "No se pudo arrancar OCTOPUS (pct enter $OCTOPUS_CTID; cd /opt/octopus; docker compose logs)"
for _ in $(seq 1 90); do
    dentro "curl -fsk -m 3 https://127.0.0.1:8443/healthz >/dev/null" 2>/dev/null && break
    sleep 2
done
dentro "curl -fsk -m 3 https://127.0.0.1:8443/healthz >/dev/null" 2>/dev/null \
    || fallo "El panel no responde todavía. Espera un minuto y abre https://$IP:8443 (o mira: pct enter $OCTOPUS_CTID; docker logs octopus)"
CLAVE="$(dentro "grep -i 'contrase' /opt/octopus/datos/panel/CREDENCIALES_INICIALES.txt 2>/dev/null | head -1 | sed 's/.*: //'" || true)"

echo
echo -e "\033[1;32m================================================================\033[0m"
echo -e "\033[1;32m  OCTOPUS ya está funcionando\033[0m"
echo
echo "  Abre en el navegador:   https://$IP:8443"
echo "  Usuario:                admin"
echo "  Contraseña (1 uso):     ${CLAVE:-mira: pct exec $OCTOPUS_CTID -- docker logs octopus}"
echo
echo "  El navegador avisará de que el certificado es propio: es normal, pulsa 'Avanzado' > 'Continuar'."
echo "  Al entrar te pedirá una contraseña nueva. Después, en el panel: Equipos > Añadir equipo."
echo "  Consejo: en el router, reserva la IP $IP para este contenedor, para que no cambie."
echo -e "\033[1;32m================================================================\033[0m"
