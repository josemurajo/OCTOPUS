#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS Zero-Touch - Despliegue de agentes Linux con Ansible (muchos equipos a la vez).
# Se ejecuta DENTRO del contenedor del servidor. Desde el anfitrion:
#   sudo bash octopus.sh desplegar -k -K     la primera vez (pide la contrasena SSH y la de sudo)
#   sudo bash octopus.sh desplegar           despues (entra con la clave SSH del servidor)
#
# Lee ansible/equipos.ini (ver equipos.ini.ejemplo). Para cada equipo:
#   - lo da de alta en el panel con sus carpetas y le crea su propia clave de agente
#   - instala el agente (ansible/desplegar_agentes.yml), que se conecta EL al servidor por HTTPS
#   - deja el acceso SSH solo con la clave del servidor (desactiva la contrasena)
set -uo pipefail
DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
ROOT="$(dirname "$DIR")"
KEY=/root/.ssh/octopus_ed25519
INV="$DIR/equipos.ini"
PY="$(command -v python3 || command -v python)"
ARGS=()
for a in "$@"; do if [[ "$a" == *.ini ]]; then INV="$a"; else ARGS+=("$a"); fi; done

[ -f "$INV" ] || { echo "Falta $INV. Copia ansible/equipos.ini.ejemplo como ansible/equipos.ini, rellenalo y vuelve a ejecutar."; exit 1; }
[ -f "$DIR/config.json" ] || { echo "Falta la configuracion de los agentes: el servidor no ha arrancado bien (octopus.sh estado)"; exit 1; }
# ansible no viene en la imagen (ocupa ~100 MB y casi nadie lo usa): se instala la primera vez que hace falta, en
# /data/ansible/venv, que se conserva al actualizar OCTOPUS. Necesita Internet solo esa primera vez.
VENV=/data/ansible/venv
if ! command -v ansible-playbook >/dev/null && [ ! -x "$VENV/bin/ansible-playbook" ]; then
    echo "Primera vez: instalando ansible en el servidor (un par de minutos, solo esta vez)..."
    mkdir -p /data/ansible
    "$PY" -m venv "$VENV" && "$VENV/bin/pip" install -q "ansible-core>=2.15,<2.18" \
        || { rm -rf "$VENV"; echo "No se pudo instalar ansible (¿hay Internet en el servidor?). Vuelve a intentarlo."; exit 1; }
fi
[ -x "$VENV/bin/ansible-playbook" ] && export PATH="$VENV/bin:$PATH"

if [ ! -f "$KEY" ]; then
    mkdir -p /root/.ssh && chmod 700 /root/.ssh
    ssh-keygen -t ed25519 -N '' -C "octopus-servidor" -f "$KEY" -q
    echo "Clave SSH del servidor creada"
fi

# equipos del grupo [seleccionados]: nombre | ip | usuario | carpetas (JSON)
mapfile -t LINEAS < <(ansible-inventory -i "$INV" --list 2>/dev/null | "$PY" -c '
import json, sys
d = json.load(sys.stdin); hv = d.get("_meta", {}).get("hostvars", {})
for h in d.get("seleccionados", {}).get("hosts", []):
    v = hv.get(h, {})
    r = v.get("octopus_backup_paths") or ["/home"]
    if isinstance(r, str):
        try: r = json.loads(r)
        except ValueError: r = [x.strip() for x in r.split(",") if x.strip()]
    print("|".join([h, str(v.get("ansible_host", h)), str(v.get("ansible_user", "root")), json.dumps(r)]))')
[ ${#LINEAS[@]} -gt 0 ] || { echo "No hay equipos en el grupo [seleccionados] de $INV"; exit 1; }

EXTRA="$DIR/.inventario_claves.ini"
HOSTS=()
umask 077
{
    echo "[seleccionados]"
    for l in "${LINEAS[@]}"; do
        IFS='|' read -r h ip user rutas <<< "$l"
        HOSTS+=("$h")
        token="$("$PY" "$ROOT/lib/equipos_cli.py" alta "$h" linux "$ip" "$rutas")" || { echo "No se pudo dar de alta $h" >&2; continue; }
        line="$h octopus_agent_token=$token"
        if ssh -i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -o LogLevel=ERROR \
               "$user@$ip" true 2>/dev/null; then
            line="$line ansible_ssh_private_key_file=$KEY"
            echo "  $h ($ip): acceso con la clave del servidor" >&2
        else
            echo "  $h ($ip): primer acceso con contrasena (usa -k -K)" >&2
        fi
        echo "$line"
    done
} > "$EXTRA"
"$PY" -c 'import json,sys; k=sys.argv[1]; print(json.dumps({"octopus_ssh_key": k, "octopus_ssh_pubkey": open(k+".pub").read().strip()}))' \
    "$KEY" > "$DIR/.extra_vars.json"
echo "Equipos: ${HOSTS[*]}"

export ANSIBLE_HOST_KEY_CHECKING=False ANSIBLE_RETRY_FILES_ENABLED=False
cd "$DIR"
ansible-playbook -i "$INV" -i "$EXTRA" desplegar_agentes.yml -e @"$DIR/.extra_vars.json" "${ARGS[@]}"
RC=$?
rm -f "$EXTRA"   # contiene las claves de los agentes

echo
FALTAN=()
for h in "${HOSTS[@]}"; do
    ok=1
    for i in $(seq 1 30); do "$PY" "$ROOT/lib/equipos_cli.py" conectado "$h" && { ok=0; break; }; sleep 2; done
    if [ $ok = 0 ]; then echo "  OK  $h conectado al servidor"; else echo "  MAL $h no se ha conectado"; FALTAN+=("$h"); fi
done
if [ ${#FALTAN[@]} -gt 0 ]; then
    echo
    echo "AVISO: ${FALTAN[*]} no se han conectado. Corrige el problema que indique Ansible y vuelve a ejecutar"
    echo "       'octopus.sh desplegar' (cada ejecucion da una clave nueva a los equipos de la lista)."
    exit 1
fi
exit $RC
