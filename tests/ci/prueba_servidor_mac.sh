#!/bin/bash
# OCTOPUS - (pruebas de GitHub) instala el servidor NATIVO de Mac como lo haria un usuario y lo prueba entero:
# arranca, se vuelve a levantar solo si se cae, gestion con octopus.sh, copia y restauracion de un agente real,
# reinstalar sin perder nada y actualizacion a distancia firmada (y que una manipulada NO se instala).
# Se ejecuta desde la carpeta del repositorio con un usuario que puede usar sudo sin contrasena (el de GitHub).
set -uo pipefail
REPO="$(pwd)"
R=/usr/local/octopus-servidor
T="${RUNNER_TEMP:-/tmp}"
FALLOS=()
resultado() { if [ "$1" = 0 ]; then echo "RESULT|PASS|$2|${3:-}"; else echo "RESULT|FAIL|$2|${3:-}"; FALLOS+=("$2"); fi; }
salud() { curl -fsk -m 5 https://127.0.0.1:8080/healthz 2>/dev/null; }
esperar() { local fin=$((SECONDS + $1)); while [ $SECONDS -lt $fin ]; do salud >/dev/null && return 0; sleep 3; done; return 1; }
instalar() { sudo OCTOPUS_IP=127.0.0.1 bash "$REPO/instalar_servidor_mac.sh" --sin-preguntas; }
equipos() { sudo "$R/python/bin/python3" -c "import sqlite3;print(sqlite3.connect('$R/data/admin_panel.db').execute('select count(*) from systems').fetchone()[0])"; }
ok() { "$@" >/dev/null 2>&1; echo $?; }

# 1. instalar como un usuario (doble clic -> INSTALAR_SERVIDOR_MAC.command llama a este mismo instalador)
t0=$SECONDS
instalar; rc=$?
resultado $rc "el instalador nativo termina bien (sin Docker, Colima ni Homebrew)" "$((SECONDS - t0)) s"
s="$(salud)"; resultado "$([ -n "$s" ]; echo $?)" "el panel responde" "$s"
resultado "$(ok sudo launchctl print system/com.octopus.servidor)" "servicio del sistema (arranca solo al encender el Mac, sin iniciar sesion)"
resultado "$(ok sudo launchctl print system/com.octopus.actualizador)" "actualizador automatico programado"
resultado "$(pgrep -f "$R/bin/rest-server" >/dev/null && pgrep -f "$R/python/bin/python" >/dev/null; echo $?)" "funciona con su propio Python y rest-server"
resultado "$(sudo grep -q "gunicorn\|Booting worker\|Listening at" "$R/datos/logs/servidor.log"; echo $?)" "panel con gunicorn"
resultado "$(sudo test -f "$R/data/CREDENCIALES_INICIALES.txt"; echo $?)" "contrasena inicial creada"
resultado "$(! command -v docker >/dev/null || ! pgrep -x com.docker.backend >/dev/null; echo $?)" "no usa Docker"

# 2. si se cae, se levanta solo (launchd KeepAlive)
sudo pkill -9 -f "$R/python/bin/python"; sudo pkill -9 -f "$R/bin/rest-server"
sleep 3
caido=1; salud >/dev/null || caido=0
resultado "$([ $caido = 0 ] && esperar 180; echo $?)" "si se para de golpe, vuelve a arrancar solo"

# 3. gestion
e="$(sudo bash "$R/octopus.sh" estado 2>&1)"
resultado "$(grep -q 'Panel: {' <<< "$e"; echo $?)" "octopus.sh estado" "$(head -3 <<< "$e" | tr '\n' ' ')"
sudo bash "$R/octopus.sh" reiniciar >/dev/null 2>&1
resultado "$(esperar 120; echo $?)" "octopus.sh reiniciar"

# 4. un agente de verdad: alta, instalacion, copia, restaurar archivo y carpeta
sudo mkdir -p "$R/tests/ci" && sudo cp "$REPO/tests/ci/prueba_agente.py" "$R/tests/ci/"
ENTORNO=(env OCTOPUS_NATIVO=1 OCTOPUS_DATA="$R/datos" OCTOPUS_BOVEDA_DIR="$R/boveda" OCTOPUS_BIN="$R/bin"
         RESTIC_CACHE_DIR="$R/datos/.cache/restic" PATH="$R/bin:$PATH")
sudo "${ENTORNO[@]}" "$R/python/bin/python3" "$R/tests/ci/prueba_agente.py" preparar macos ci-agente "$HOME/octopus_ci" "$T/inst"
( cd "$T/inst" && sudo bash INSTALAR.command --sin-preguntas )
sudo "${ENTORNO[@]}" "$R/python/bin/python3" "$R/tests/ci/prueba_agente.py" probar ci-agente "$HOME/octopus_ci"
resultado $? "agente: copia y restauracion contra el servidor nativo"

# 4b. copia completa del Mac (la real copia /System/Volumes/Data entero: en el Mac de GitHub son cientos de GB, asi que
#     se limita con OCTOPUS_RUTA_COMPLETA a una carpeta, con la ruta real de macOS para los datos de usuario)
COMPLETA="/System/Volumes/Data/Users/$(id -un)/octopus_completa"
mkdir -p "$HOME/octopus_completa" && echo "solo en la copia completa $(date +%s)" > "$HOME/octopus_completa/fuera_de_la_copia_diaria.txt"
PB=/usr/libexec/PlistBuddy; PLIST=/Library/LaunchDaemons/com.octopus.agent.plist
sudo $PB -c "Add :EnvironmentVariables dict" "$PLIST" 2>/dev/null
sudo $PB -c "Delete :EnvironmentVariables:OCTOPUS_RUTA_COMPLETA" "$PLIST" 2>/dev/null
sudo $PB -c "Add :EnvironmentVariables:OCTOPUS_RUTA_COMPLETA string $COMPLETA" "$PLIST"
sudo launchctl bootout system "$PLIST" 2>/dev/null; sleep 2; sudo launchctl bootstrap system "$PLIST"; sleep 10
sudo "${ENTORNO[@]}" "$R/python/bin/python3" "$R/tests/ci/prueba_agente.py" completa ci-agente "$COMPLETA"
resultado $? "copia completa del Mac y recuperar desde ella"

# 5. volver a instalar (actualizar a mano) no pierde nada
antes="$(equipos)"
instalar >/dev/null 2>&1; rc=$?
resultado "$([ $rc = 0 ] && salud >/dev/null; echo $?)" "volver a instalar (actualizar) funciona"
resultado "$([ "$(equipos)" = "$antes" ] && [ "${antes:-0}" -ge 1 ]; echo $?)" "al reinstalar se conservan los equipos y los datos" "equipos: $antes -> $(equipos)"
resultado "$(test -f "$R.anterior/lib/servidor.py"; echo $?)" "se guarda la version anterior por si hay que volver"

# 6. actualizacion a distancia firmada (desde un archivo local, con una clave de PRUEBA)
bash tests/ci/version_firmada.sh "$T/buena.tar.gz" 9.9.9 "$T/claves" >/dev/null
bash tests/ci/version_firmada.sh "$T/mala.tar.gz" 9.9.10 "$T/claves" manipular >/dev/null
sudo cp "$T/claves/clave.pub" "$R/install/firma_publicacion.pub"
pedir() { # pedir <archivo> <version>
    sudo sed -i '' -e '/^OCTOPUS_URL_CODIGO=/d' -e '/^OCTOPUS_PROTO_DESCARGA=/d' "$R/install/.env"
    printf 'OCTOPUS_URL_CODIGO=file://%s\nOCTOPUS_PROTO_DESCARGA==file\n' "$1" | sudo tee -a "$R/install/.env" >/dev/null
    sudo mkdir -p "$R/datos/actualizacion"; sudo rm -f "$R/datos/actualizacion/resultado.json"
    echo "$2" | sudo tee "$R/datos/actualizacion/pedida" >/dev/null
    sudo bash "$R/actualizador.sh" >/dev/null 2>&1
    sudo cat "$R/datos/actualizacion/resultado.json" 2>/dev/null
}
r="$(pedir "$T/mala.tar.gz" 9.9.10)"
resultado "$(grep -q '"ok": false' <<< "$r" && [ "$(cat "$R/VERSION")" != 9.9.10 ]; echo $?)" "version manipulada: NO se instala" "$r"
r="$(pedir "$T/buena.tar.gz" 9.9.9)"
resultado "$(grep -q '"ok": true' <<< "$r" && [ "$(cat "$R/VERSION")" = 9.9.9 ] && salud >/dev/null; echo $?)" "version firmada: se actualiza sola y sigue funcionando" "$r"
resultado "$([ "$(equipos)" -ge 1 ]; echo $?)" "tras actualizar a distancia se conservan los equipos"

echo
if [ ${#FALLOS[@]} -gt 0 ]; then printf 'FALLOS: %s\n' "${FALLOS[*]}"; exit 1; fi
echo "TODO CORRECTO"
