#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS - Despliegue de agentes en las VMs Linux del LABORATORIO Vagrant.
# Se ejecuta dentro del servidor:  docker exec octopus bash /app/ansible/deploy_vagrant.sh [cliente1 cliente2 ...]
#
# 1a vez: entra por SSH con contrasena, instala la clave SSH del servidor y desactiva la contrasena.
# Despues: solo con la clave. Cada equipo recibe su propia clave de agente y se conecta el solo al servidor.
set -uo pipefail

DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
ROOT="$(dirname "$DIR")"
INV="$DIR/inventario_vagrant.ini"
SSH_USER="${OCTOPUS_SSH_USER:-vagrant}"
SSH_PASS="${OCTOPUS_SSH_PASS:-vagrant123}"
KEY="/root/.ssh/octopus_ed25519"
PY="$(command -v python3 || command -v python)"

declare -A IPS=( [cliente1]=192.168.10.20 [cliente2]=192.168.20.20 [debian12]=192.168.10.60 [rocky9]=192.168.10.50 )
# Direccion del servidor que ve cada equipo (cliente2 esta en la red segura 192.168.20.0/24)
declare -A SERVIDOR=( [cliente1]=192.168.10.10 [cliente2]=192.168.20.10 [debian12]=192.168.10.10 [rocky9]=192.168.10.10 )
declare -A PATHS=(
  [cliente1]='["/home/vagrant/testfiles","/home/vagrant/datos","/etc/miapp"]'
  [cliente2]='["/home/vagrant/testfiles","/home/vagrant/database"]'
  [debian12]='["/home/vagrant/testfiles"]'
  [rocky9]='["/home/vagrant/testfiles"]'
)

[ -f "$DIR/config.json" ] || { echo "ERROR: falta $DIR/config.json (arranca antes el servidor)"; exit 1; }
if [ ! -f "$KEY" ]; then
    mkdir -p /root/.ssh && chmod 700 /root/.ssh
    ssh-keygen -t ed25519 -N '' -C "octopus-servidor" -f "$KEY" -q
    echo "Clave SSH del servidor creada"
fi

HOSTS=("$@")
[ ${#HOSTS[@]} -gt 0 ] || HOSTS=(cliente1 cliente2 debian12 rocky9)
OK_HOSTS=()
for h in "${HOSTS[@]}"; do
    ip="${IPS[$h]:-}"
    [ -n "$ip" ] || { echo "Host desconocido: $h"; continue; }
    if timeout 3 bash -c "echo > /dev/tcp/$ip/22" 2>/dev/null; then OK_HOSTS+=("$h"); echo "  + $h ($ip) accesible"
    else echo "  - $h ($ip) no responde por SSH, se omite"; fi
done
[ ${#OK_HOSTS[@]} -gt 0 ] || { echo "ERROR: ningun cliente accesible"; exit 2; }

{
echo "[seleccionados]"
for h in "${OK_HOSTS[@]}"; do
    ip="${IPS[$h]}"
    token="$("$PY" "$ROOT/lib/equipos_cli.py" alta "$h" linux "$ip" "${PATHS[$h]}")"
    line="$h ansible_host=$ip octopus_backup_paths=${PATHS[$h]} octopus_servidor=${SERVIDOR[$h]} octopus_agent_token=$token"
    if ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
           -o ConnectTimeout=5 -o LogLevel=ERROR "$SSH_USER@$ip" true 2>/dev/null; then
        line="$line ansible_ssh_private_key_file=$KEY"; echo "    $h: acceso con clave SSH" >&2
    else
        line="$line ansible_password=$SSH_PASS"; echo "    $h: primer acceso con contrasena (se cambia a clave)" >&2
    fi
    echo "$line"
done
cat <<EOF

[seleccionados:vars]
ansible_user=$SSH_USER
ansible_become_password=$SSH_PASS
ansible_python_interpreter=/usr/bin/python3
# Laboratorio: aunque un equipo este aislado, Vagrant (red NAT 10.0.2.2) puede seguir gestionando la VM
octopus_isolation_allow=["10.0.2.2"]
ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
EOF
} > "$INV"
chmod 600 "$INV"

"$PY" -c 'import json,sys; k=sys.argv[1]; print(json.dumps({"octopus_ssh_key": k, "octopus_ssh_pubkey": open(k+".pub").read().strip()}))' "$KEY" > "$DIR/extra_vars.json"
chmod 600 "$DIR/extra_vars.json"

export ANSIBLE_HOST_KEY_CHECKING=False ANSIBLE_RETRY_FILES_ENABLED=False ANSIBLE_STDOUT_CALLBACK=default ANSIBLE_NOCOLOR=1
cd "$DIR"
ansible-playbook -i "$INV" desplegar_agentes.yml -e @"$DIR/extra_vars.json"
RC=$?

# Comprobar que cada agente se ha conectado al servidor
for h in "${OK_HOSTS[@]}"; do
    for i in $(seq 1 30); do "$PY" "$ROOT/lib/equipos_cli.py" conectado "$h" && break; sleep 2; done
    "$PY" "$ROOT/lib/equipos_cli.py" conectado "$h" && echo "Equipo $h conectado al servidor" || echo "AVISO: $h no se ha conectado"
done
exit $RC
