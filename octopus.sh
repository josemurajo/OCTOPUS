#!/bin/bash
# OCTOPUS Zero-Touch - gestion del servidor (Linux y macOS). En Windows: octopus.ps1
#   sudo bash octopus.sh <orden>      (en Mac: sudo bash /usr/local/octopus-servidor/octopus.sh <orden>)
set -uo pipefail
RAIZ="$(cd "$(dirname "$(realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
DC=(docker compose --env-file "$RAIZ/install/.env" -f "$RAIZ/install/docker-compose.yml")

# ------------------------------------------------------------------ servidor NATIVO de Mac (sin Docker)
if [ -x "$RAIZ/python/bin/python3" ] && [ "$(uname -s)" = Darwin ]; then
    [ "$(id -u)" -eq 0 ] || exec sudo bash "$0" "$@"
    entorno() {
        while IFS='=' read -r k v; do case "$k" in ''|\#*) continue ;; esac
            v="$(printf '%s' "$v" | tr -d '\r"')"; [ -n "$v" ] && export "$k=$v"; done < "$RAIZ/install/.env"
        export OCTOPUS_NATIVO=1 OCTOPUS_DATA="$RAIZ/datos" OCTOPUS_BIN="$RAIZ/bin" RESTIC_CACHE_DIR="$RAIZ/datos/.cache/restic"
        export OCTOPUS_BOVEDA_DIR="${OCTOPUS_BOVEDA_DIR:-$RAIZ/boveda}" PATH="$RAIZ/bin:$RAIZ/python/bin:$PATH"
        cd "$RAIZ" || exit 1
    }
    py() { entorno; "$RAIZ/python/bin/python3" "$@"; }
    salud() { curl -fsk -m 5 "https://127.0.0.1:$(grep -E '^ADMIN_PORT=' "$RAIZ/install/.env" | cut -d= -f2 | tr -d '\r' || echo 8080)/healthz"; }
    esperar() { for _ in $(seq 1 60); do salud >/dev/null 2>&1 && return 0; sleep 2; done; return 1; }
    PL=/Library/LaunchDaemons/com.octopus.servidor.plist
    parar_n() { launchctl bootout system/com.octopus.servidor 2>/dev/null; sleep 2
                pkill -f "$RAIZ/python/bin/python" 2>/dev/null; pkill -f "$RAIZ/bin/rest-server" 2>/dev/null; sleep 1; true; }
    arrancar_n() { launchctl bootstrap system "$PL" 2>/dev/null; launchctl kickstart -k system/com.octopus.servidor 2>/dev/null
                   esperar && echo "OCTOPUS en marcha." || echo "No responde todavia: mira 'octopus.sh logs'."; }
    case "${1:-ayuda}" in
    estado)        launchctl print system/com.octopus.servidor 2>/dev/null | grep -E "state =|pid =" | head -2
                   echo "Panel: $(salud || echo 'NO RESPONDE')"; py lib/equipos_cli.py lista ;;
    logs)          tail -n "${2:-100}" -f "$RAIZ/datos/logs/servidor.log" ;;
    credenciales)  cat "$RAIZ/data/CREDENCIALES_INICIALES.txt" 2>/dev/null || echo "Ya no hay credenciales iniciales (se borran al cambiar la contrasena)" ;;
    kit)           py lib/mantenimiento.py kit ;;
    buscar-equipos) py lib/consola.py ${2:+"$2"} ;;
    mantenimiento) py lib/mantenimiento.py "${2:-todo}" ;;
    ajustes)       cp "$RAIZ/.env" "$RAIZ/.env.antes"; "${EDITOR:-$(command -v nano || command -v vi)}" "$RAIZ/.env"
                   if cmp -s "$RAIZ/.env" "$RAIZ/.env.antes"; then echo "Sin cambios."; else parar_n; arrancar_n; fi
                   rm -f "$RAIZ/.env.antes" ;;
    recuperar-servidor)
        ORIGEN="${2:-}"; [ -n "$ORIGEN" ] || { echo "Uso: bash octopus.sh recuperar-servidor <carpeta octopus-backups | almacen externo>"; exit 2; }
        entorno; REPO="$ORIGEN"
        if [ -d "$ORIGEN" ]; then
            [ "$(ls "$OCTOPUS_BOVEDA_DIR/octopus-backups/snapshots" 2>/dev/null | wc -l | tr -d ' ')" = 0 ] \
                || { echo "Este servidor ya tiene copias en su almacen: no se sobrescriben."; exit 1; }
            parar_n; echo "Copiando el almacen (puede tardar)..."
            rsync -a "$ORIGEN/" "$OCTOPUS_BOVEDA_DIR/octopus-backups/" || exit 1
            [ -d "$(dirname "$ORIGEN")/octopus-cuarentena" ] && rsync -a "$(dirname "$ORIGEN")/octopus-cuarentena/" "$OCTOPUS_BOVEDA_DIR/octopus-cuarentena/"
            REPO="$OCTOPUS_BOVEDA_DIR/octopus-backups"
        fi
        py lib/recuperar_servidor.py "$REPO"; rc=$?; arrancar_n; exit $rc ;;
    actualizar)    ORIGEN="${2:-$PWD}"
                   if [ ! -f "$ORIGEN/instalar_servidor_mac.sh" ] || [ "$(cd "$ORIGEN" && pwd)" = "$RAIZ" ]; then
                       echo "Ejecuta esto desde la carpeta de la VERSION NUEVA (o: octopus.sh actualizar <carpeta>), o actualiza desde el panel."; exit 2; fi
                   OCTOPUS_DESTINO="$RAIZ" bash "$ORIGEN/instalar_servidor_mac.sh" --sin-preguntas ;;
    actualizar-pedido) bash "$RAIZ/actualizador.sh" ;;
    volver)        [ -f "$RAIZ.anterior/lib/servidor.py" ] || { echo "No hay version anterior guardada"; exit 1; }
                   parar_n; rsync -a "$RAIZ.anterior/" "$RAIZ/"; arrancar_n ;;
    parar)         parar_n; echo "OCTOPUS parado (volvera a arrancar al reiniciar el Mac)." ;;
    arrancar)      arrancar_n ;;
    reiniciar)     parar_n; arrancar_n ;;
    desinstalar)
        entorno
        echo "Se quitara OCTOPUS de este Mac. Las COPIAS ($OCTOPUS_BOVEDA_DIR) y los datos se quedan, salvo que escribas BORRAR TODO."
        RESP="${2:-}"; [ -n "$RESP" ] || read -r -p "Escribe SI para desinstalar (o BORRAR TODO para quitar tambien las copias): " RESP
        case "$RESP" in SI|"BORRAR TODO") ;; *) echo "Cancelado."; exit 1 ;; esac
        parar_n; launchctl bootout system/com.octopus.actualizador 2>/dev/null
        rm -f /Library/LaunchDaemons/com.octopus.servidor.plist /Library/LaunchDaemons/com.octopus.actualizador.plist
        rm -rf "$RAIZ/python" "$RAIZ/bin" "$RAIZ/lib" "$RAIZ/templates" "$RAIZ/agentes" "$RAIZ/install" "$RAIZ/herramientas"
        if [ "$RESP" = "BORRAR TODO" ]; then rm -rf "$OCTOPUS_BOVEDA_DIR" "$RAIZ" "$RAIZ.anterior"; echo "OCTOPUS y sus copias se han quitado de este Mac."
        else echo "OCTOPUS se ha quitado. Se quedan las copias en $OCTOPUS_BOVEDA_DIR y la configuracion en $RAIZ/data y $RAIZ/.env"; fi ;;
    *) cat <<AYUDA
Uso: sudo bash $RAIZ/octopus.sh <orden>
  estado | logs [n] | credenciales | buscar-equipos | kit | mantenimiento | ajustes
  recuperar-servidor <almacen> | actualizar <carpeta version nueva> | volver
  parar | arrancar | reiniciar | desinstalar
AYUDA
    ;;
    esac
    exit $?
fi

case "${1:-ayuda}" in
estado)
    docker ps --filter name=^octopus --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    docker exec octopus python /app/lib/equipos_cli.py lista
    docker exec octopus curl -fsk https://127.0.0.1:8080/healthz; echo ;;
logs)          docker logs --tail "${2:-100}" -f octopus ;;
credenciales)  docker exec octopus cat /data/panel/CREDENCIALES_INICIALES.txt 2>/dev/null || echo "Ya no hay credenciales iniciales (se borran al cambiar la contrasena)" ;;
kit)           docker exec octopus python /app/lib/mantenimiento.py kit ;;
buscar-equipos)  # ventanas con raton para buscar y proteger equipos (si la consola no es interactiva, preguntas en texto)
    if [ -t 0 ] && [ -t 1 ]; then docker exec -it -e TERM="${TERM:-xterm-256color}" octopus python /app/lib/consola.py ${2:+"$2"}
    else docker exec -i octopus python /app/lib/consola.py --sencillo; fi ;;
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
actualizar-pedido)  # lo lanza el temporizador cada 5 min: hace la actualizacion pedida desde el panel (firmada)
    bash "$RAIZ/actualizador.sh" ;;
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
Uso: sudo bash octopus.sh <orden>     (en Windows: octopus.ps1)
  estado          como esta todo (contenedor, equipos conectados, almacen)
  logs [n]        registro en directo del servidor
  credenciales    contrasena inicial del panel
  buscar-equipos  busca los equipos de la red y los protege, con ventanas y raton (--sencillo: solo preguntas)
  kit             kit de recuperacion (claves de las copias) - guardalo fuera del servidor
  mantenimiento   limpieza, verificacion y copia del servidor ahora (normalmente cada noche)
  ajustes         cambia los ajustes del servidor (almacen externo, avisos de disco...) y reinicia
  desplegar       instala el agente en los equipos Linux de ansible/equipos.ini (anade -k -K la primera vez)
  recuperar-servidor <almacen>   monta un servidor nuevo con la configuracion del que se perdio
  actualizar      instala la version de esta carpeta (conserva datos y copias)
  actualizar-pedido  hace la actualizacion pedida desde el panel (normalmente la lanza sola un temporizador)
  volver          vuelve a la version anterior si la actualizacion da problemas
  parar | arrancar | reiniciar | consola
EOF
;;
esac
