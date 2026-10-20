#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# OCTOPUS Zero-Touch - Instalador del agente para macOS (11 Big Sur o posterior, Intel y Apple Silicon)
#
# En el zip que da el panel se llama INSTALAR.command: doble clic (o clic derecho -> Abrir la primera vez).
#   bash INSTALAR.command                 instalar o actualizar (pide la contrasena de administrador)
#   bash INSTALAR.command --quitar        desinstalar (las copias del servidor NO se borran)
#   bash INSTALAR.command --sin-preguntas lo usa la instalacion a distancia desde el panel
#
# Instala: Python (si falta), restic, el agente como servicio del sistema (LaunchDaemon) que arranca solo
# y se reinicia si falla, y la copia diaria a las 20:00. No abre ningun puerto: el agente se conecta el
# al servidor por HTTPS.
set -u
AQUI="$(cd "$(dirname "$0")" && pwd)"
DIR="/usr/local/octopus"
DATOS="/Library/Application Support/Octopus"
LOGS="/Library/Logs/Octopus"
PLIST="/Library/LaunchDaemons/com.octopus.agent.plist"
PLIST_COPIA="/Library/LaunchDaemons/com.octopus.copia.plist"
RESTIC_VER="0.16.4"
PY_VER="3.12.7"
PREGUNTAR=1
for a in "$@"; do [ "$a" = "--sin-preguntas" ] && PREGUNTAR=0; done

PROGRESO="${OCTOPUS_PROGRESO:-/Library/Logs/OCTOPUS/instalacion_agente_progreso.txt}"   # banderines: cada paso con la hora (para saber donde se paro)
marca() { { mkdir -p "$(dirname "$PROGRESO")" && echo "[$(date '+%F %T')] $*" >> "$PROGRESO"; } 2>/dev/null || true; }
paso() { marca "==> $*"; echo; printf '\033[1;36m==> %s\033[0m\n' "$*"; }
bien() { marca "OK  $*"; printf '    \033[32m%s\033[0m\n' "$*"; }
aviso() { marca "..  $*"; printf '    \033[33m%s\033[0m\n' "$*"; }
fallo() { marca "ERROR $*"; printf '\n\033[1;31mERROR: %s\033[0m\n' "$*"; [ $PREGUNTAR = 1 ] && read -r -p "Pulsa Intro para cerrar" _; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fallo "Este instalador es para Mac."
if [ "$(id -u)" -ne 0 ]; then
    echo "OCTOPUS necesita permisos de administrador. Escribe la contrasena de tu Mac (no se ve al escribir):"
    exec sudo /bin/bash "$0" "$@"
fi

# ------------------------------------------------------------------ desinstalar
if [ "${1:-}" = "--quitar" ]; then
    paso "Quitando OCTOPUS"
    launchctl bootout system "$PLIST" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
    launchctl bootout system "$PLIST_COPIA" 2>/dev/null || launchctl unload "$PLIST_COPIA" 2>/dev/null || true
    rm -f "$PLIST" "$PLIST_COPIA"
    pfctl -d 2>/dev/null || true          # por si estaba aislado por un incidente
    rm -rf "$DIR" "$DATOS/config.json"
    bien "OCTOPUS se ha quitado. Las copias del servidor siguen alli."
    exit 0
fi

for f in zerotouch_agent.py config.json; do
    [ -f "$AQUI/$f" ] || fallo "Falta $f junto a este archivo. Descarga de nuevo el instalador desde el panel."
done
leer_cfg() { sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" "$AQUI/config.json" | head -1; }
NOMBRE="$(leer_cfg hostname)"
SERVIDOR="$(leer_cfg servidor)"
ESTE="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
echo
printf '\033[1mOCTOPUS Zero-Touch - instalacion en este Mac\033[0m   (macOS %s, %s)\n' "$(sw_vers -productVersion)" "$(uname -m)"
echo "  Equipo: ${NOMBRE:-?}     Servidor: ${SERVIDOR:-?}"
if [ -n "$NOMBRE" ] && [ "$NOMBRE" != "$ESTE" ]; then
    aviso "Este paquete es para '$NOMBRE' y este Mac se llama '$ESTE'. Las copias se guardaran como '$NOMBRE'."
    [ $PREGUNTAR = 1 ] && sleep 6
fi

# ------------------------------------------------------------------ Python
paso "Python"
PY=""
for c in /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    [ -x "$c" ] && "$c" -c 'import ssl, json' 2>/dev/null && { PY="$c"; break; }
done
# /usr/bin/python3 solo sirve si estan las herramientas de Apple (si no, abre una ventana pidiendo instalarlas)
if [ -z "$PY" ] && xcode-select -p >/dev/null 2>&1 && /usr/bin/python3 -c 'import ssl, json' 2>/dev/null; then PY=/usr/bin/python3; fi
if [ -z "$PY" ]; then
    aviso "Instalando Python $PY_VER (1-2 minutos)..."
    TMPPKG="$(mktemp -d)/python.pkg"
    curl -fsSL --retry 3 -o "$TMPPKG" "https://www.python.org/ftp/python/$PY_VER/python-$PY_VER-macos11.pkg" \
        || fallo "No se pudo descargar Python. Comprueba la conexion a Internet."
    installer -pkg "$TMPPKG" -target / >/dev/null || fallo "No se pudo instalar Python"
    rm -f "$TMPPKG"
    PY="/Library/Frameworks/Python.framework/Versions/${PY_VER%.*}/bin/python3"
fi
[ -x "$PY" ] || fallo "Python no esta disponible"
bien "$("$PY" --version 2>&1): $PY"

# ------------------------------------------------------------------ restic
paso "Motor de copias (restic)"
mkdir -p "$DIR"
if [ ! -x "$DIR/restic" ]; then
    case "$(uname -m)" in arm64) ARQ=arm64 ;; *) ARQ=amd64 ;; esac
    curl -fsSL --retry 3 "https://github.com/restic/restic/releases/download/v${RESTIC_VER}/restic_${RESTIC_VER}_darwin_${ARQ}.bz2" \
        | bunzip2 > "$DIR/restic.tmp" || fallo "No se pudo descargar restic"
    chmod 755 "$DIR/restic.tmp" && mv "$DIR/restic.tmp" "$DIR/restic"
    xattr -d com.apple.quarantine "$DIR/restic" 2>/dev/null || true
fi
bien "$("$DIR/restic" version)"

# ------------------------------------------------------------------ agente
paso "Agente OCTOPUS"
launchctl bootout system "$PLIST" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
mkdir -p "$DATOS" "$LOGS"
install -m 0755 "$AQUI/zerotouch_agent.py" "$DIR/zerotouch_agent.py"
[ -f "$AQUI/octopus_monitor.py" ] && install -m 0644 "$AQUI/octopus_monitor.py" "$DIR/octopus_monitor.py"
[ -f "$AQUI/octopus_vms.py" ] && install -m 0644 "$AQUI/octopus_vms.py" "$DIR/octopus_vms.py"
"$PY" - "$AQUI/config.json" "$DATOS/config.json" "$DIR/restic" <<'PYEOF'
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg["restic_bin"] = sys.argv[3]
json.dump(cfg, open(sys.argv[2], "w"), indent=2)
PYEOF
chmod 600 "$DATOS/config.json"; chmod 700 "$DATOS"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.octopus.agent</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/zerotouch_agent.py</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>OCTOPUS_CONFIG</key><string>$DATOS/config.json</string>
    <key>PATH</key><string>$DIR:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOGS/servicio.log</string>
  <key>StandardErrorPath</key><string>$LOGS/servicio.log</string>
</dict></plist>
EOF
cat > "$PLIST_COPIA" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.octopus.copia</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/zerotouch_agent.py</string><string>--copia</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>OCTOPUS_CONFIG</key><string>$DATOS/config.json</string>
    <key>PATH</key><string>$DIR:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$LOGS/copia.log</string>
  <key>StandardErrorPath</key><string>$LOGS/copia.log</string>
</dict></plist>
EOF
chown root:wheel "$PLIST" "$PLIST_COPIA"; chmod 644 "$PLIST" "$PLIST_COPIA"
launchctl bootout system "$PLIST_COPIA" 2>/dev/null || true
launchctl bootstrap system "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
launchctl bootstrap system "$PLIST_COPIA" 2>/dev/null || launchctl load -w "$PLIST_COPIA"

OK=0
for i in $(seq 1 20); do curl -fs -m 3 http://127.0.0.1:9999/health >/dev/null 2>&1 && { OK=1; break; }; sleep 2; done
[ $OK = 1 ] || fallo "El agente no arranca. Mira el registro: $LOGS/agent.log y $LOGS/servicio.log"
bien "agente en marcha (arranca solo con el Mac y se reinicia si falla)"

paso "Primera copia de seguridad"
launchctl kickstart system/com.octopus.copia 2>/dev/null || ( OCTOPUS_CONFIG="$DATOS/config.json" "$PY" "$DIR/zerotouch_agent.py" --copia >/dev/null 2>&1 & )
bien "en marcha en segundo plano; despues, una copia cada dia a las 20:00"

paso "Permiso para leer Documentos, Escritorio y Descargas"
echo "    macOS protege esas carpetas. Para que entren en la copia, activa «Acceso total al disco» para:"
echo "        $PY"
echo "    en Ajustes del Sistema -> Privacidad y seguridad -> Acceso total al disco (boton + , y Cmd+Shift+G para pegar la ruta)."
echo "    Sin ese permiso las copias se hacen igual, pero sin esas carpetas."
if [ $PREGUNTAR = 1 ]; then
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" 2>/dev/null || true
fi

echo
printf '\033[1;32mOCTOPUS instalado. En el panel este Mac aparecera como protegido en unos minutos.\033[0m\n'
printf '\033[1;33mIMPORTANTE: borra ahora esta carpeta y el .zip (contienen claves).\033[0m\n'
[ $PREGUNTAR = 1 ] && read -r -p "Pulsa Intro para cerrar" _
exit 0
