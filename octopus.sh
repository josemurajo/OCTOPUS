#!/bin/bash
# OCTOPUS Zero-Touch - gestion del servidor (Linux y macOS). En Windows: octopus.ps1
#   sudo bash octopus.sh <orden>      (en Mac, sin sudo: bash octopus.sh <orden>)
set -uo pipefail
RAIZ="$(cd "$(dirname "$(realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
DC=(docker compose --env-file "$RAIZ/install/.env" -f "$RAIZ/install/docker-compose.yml")

case "${1:-ayuda}" in
estado)
    docker ps --filter name=^octopus --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    docker exec octopus python /app/lib/equipos_cli.py lista
    docker exec octopus curl -fsk https://127.0.0.1:8080/healthz; echo ;;
logs)          docker logs --tail "${2:-100}" -f octopus ;;
credenciales)  docker exec octopus cat /data/panel/CREDENCIALES_INICIALES.txt 2>/dev/null || echo "Ya no hay credenciales iniciales (se borran al cambiar la contrasena)" ;;
kit)           docker exec octopus python /app/lib/mantenimiento.py kit ;;
mantenimiento) docker exec octopus python /app/lib/mantenimiento.py "${2:-todo}" ;;
desplegar)     # agentes Linux con Ansible: rellena ansible/equipos.ini (ver equipos.ini.ejemplo)
    shift
    if [ -f "$RAIZ/ansible/equipos.ini" ]; then
        docker exec octopus mkdir -p /data/ansible
        docker cp "$RAIZ/ansible/equipos.ini" octopus:/data/ansible/equipos.ini
    fi
    docker exec -it octopus bash /app/ansible/desplegar.sh "$@" ;;
ajustes)       # edita los ajustes del servidor (/data/.env dentro del contenedor) y reinicia
    TMPF="$(mktemp)"; chmod 600 "$TMPF"
    docker cp octopus:/data/.env "$TMPF" || { rm -f "$TMPF"; exit 1; }
    cp "$TMPF" "$TMPF.antes"
    "${EDITOR:-$(command -v nano || command -v vi)}" "$TMPF"
    if cmp -s "$TMPF" "$TMPF.antes"; then echo "Sin cambios."
    else docker cp "$TMPF" octopus:/data/.env && docker exec octopus chmod 600 /data/.env && docker restart octopus >/dev/null \
         && echo "Ajustes guardados. OCTOPUS se ha reiniciado."; fi
    rm -f "$TMPF" "$TMPF.antes" ;;
recuperar-servidor)  # servidor nuevo a partir de la autocopia del antiguo (ver PRODUCCION.md)
    ORIGEN="${2:-}"
    [ -n "$ORIGEN" ] || { echo "Uso: sudo bash octopus.sh recuperar-servidor <carpeta octopus-backups del disco antiguo | almacen externo>"; exit 2; }
    if [ -d "$ORIGEN" ]; then
        # carpeta del almacen antiguo (p. ej. el disco del servidor perdido montado en este): se copia al volumen
        # un servidor recien instalado tiene el almacen creado pero vacio; si ya tiene copias, no se toca
        [ "$(docker exec octopus sh -c 'ls /boveda/octopus-backups/snapshots 2>/dev/null | wc -l')" = 0 ] \
            || { echo "Este servidor ya tiene copias en su almacen: no se sobrescriben. Usa un servidor recien instalado."; exit 1; }
        echo "Copiando el almacen (puede tardar)..."
        docker exec octopus rm -rf /boveda/octopus-backups
        docker cp "$ORIGEN" octopus:/boveda/octopus-backups || exit 1
        [ -d "$(dirname "$ORIGEN")/octopus-cuarentena" ] && { docker exec octopus rm -rf /boveda/octopus-cuarentena; \
            docker cp "$(dirname "$ORIGEN")/octopus-cuarentena" octopus:/boveda/octopus-cuarentena; }
        docker exec octopus chown -R root:root /boveda
        REPO=/boveda/octopus-backups
    else
        REPO="$ORIGEN"
    fi
    docker exec -it octopus python /app/lib/recuperar_servidor.py "$REPO" || exit 1
    docker restart octopus >/dev/null && echo "OCTOPUS reiniciado con la configuracion recuperada. Entra en el panel con tu usuario de siempre." ;;
actualizar)    bash "$RAIZ/instalar_servidor.sh" ;;
volver)        # vuelve a la version anterior a la ultima actualizacion
    docker image inspect octopus-servidor:anterior >/dev/null 2>&1 || { echo "No hay version anterior guardada"; exit 1; }
    sed -i.bak 's/^OCTOPUS_VERSION=.*/OCTOPUS_VERSION=anterior/' "$RAIZ/install/.env"
    "${DC[@]}" up -d --no-build octopus && echo "Vuelto a la version anterior. Para volver a la nueva: bash octopus.sh actualizar" ;;
parar)         "${DC[@]}" stop ;;
arrancar)      "${DC[@]}" up -d --no-build octopus ;;
reiniciar)     docker restart octopus ;;
consola)       docker exec -it octopus bash ;;
*)
    cat <<EOF
Uso: sudo bash octopus.sh <orden>     (en Mac sin sudo; en Windows: octopus.ps1)
  estado          como esta todo (contenedor, equipos conectados, almacen)
  logs [n]        registro en directo del servidor
  credenciales    contrasena inicial del panel
  kit             kit de recuperacion (claves de las copias) - guardalo fuera del servidor
  mantenimiento   limpieza, verificacion y copia del servidor ahora (normalmente cada noche)
  ajustes         cambia los ajustes del servidor (almacen externo, avisos de disco...) y reinicia
  desplegar       instala el agente en los equipos Linux de ansible/equipos.ini (anade -k -K la primera vez)
  recuperar-servidor <almacen>   monta un servidor nuevo con la configuracion del que se perdio
  actualizar      instala la version de esta carpeta (conserva datos y copias)
  volver          vuelve a la version anterior si la actualizacion da problemas
  parar | arrancar | reiniciar | consola
EOF
;;
esac
