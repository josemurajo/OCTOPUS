#!/bin/bash
# Descarga restic y rest-server para el sistema donde corre (Linux, macOS o Windows con Git Bash).
#   bash tests/ci/herramientas.sh <carpeta>
set -euo pipefail
DEST="$1"; mkdir -p "$DEST"; cd "$DEST"
RESTIC=0.16.4; REST=0.13.0
case "$(uname -s)" in
  Linux*)  SO=linux ;;
  Darwin*) SO=darwin ;;
  MINGW*|MSYS*|CYGWIN*) SO=windows ;;
  *) echo "sistema no soportado: $(uname -s)"; exit 1 ;;
esac
case "$(uname -m)" in arm64|aarch64) ARQ=arm64 ;; *) ARQ=amd64 ;; esac
U=https://github.com/restic
if [ "$SO" = windows ]; then
  curl -fsSL -o r.zip "$U/restic/releases/download/v$RESTIC/restic_${RESTIC}_windows_${ARQ}.zip"
  unzip -oq r.zip && mv -f restic_*_windows_*.exe restic.exe && rm -f r.zip
  # el nombre del paquete de Windows ha cambiado entre versiones: se pregunta a GitHub cual es
  URL=$(curl -fsSL "https://api.github.com/repos/restic/rest-server/releases/tags/v$REST" | python -c "
import json, sys
for a in json.load(sys.stdin)['assets']:
    n = a['name'].lower()
    if 'windows' in n and '${ARQ}' in n and (n.endswith('.zip') or n.endswith('.tar.gz')):
        print(a['browser_download_url']); break")
  [ -n "$URL" ] || { echo "no hay rest-server $REST para windows_${ARQ}"; exit 1; }
  echo "rest-server: $URL"
  mkdir -p rs && curl -fsSL -o "rs/${URL##*/}" "$URL"
  case "$URL" in *.zip) (cd rs && unzip -oq ./*.zip) ;; *) (cd rs && tar -xzf ./*.tar.gz) ;; esac
  mv -f "$(find rs -name 'rest-server*.exe' | head -1)" rest-server.exe && rm -rf rs
else
  curl -fsSL "$U/restic/releases/download/v$RESTIC/restic_${RESTIC}_${SO}_${ARQ}.bz2" | bunzip2 > restic
  curl -fsSL "$U/rest-server/releases/download/v$REST/rest-server_${REST}_${SO}_${ARQ}.tar.gz" | tar -xz --strip-components=1 "rest-server_${REST}_${SO}_${ARQ}/rest-server"
  chmod 755 restic rest-server
fi
./restic version && ./rest-server --version
