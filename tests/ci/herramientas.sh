#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
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
  # rest-server para Windows se publica como .tar.gz (no .zip)
  curl -fsSL -o s.tgz "$U/rest-server/releases/download/v$REST/rest-server_${REST}_windows_${ARQ}.tar.gz"
  mkdir -p rs && tar -xzf s.tgz -C rs
  mv -f "$(find rs -name 'rest-server*.exe' | head -1)" rest-server.exe && rm -rf rs s.tgz
else
  curl -fsSL "$U/restic/releases/download/v$RESTIC/restic_${RESTIC}_${SO}_${ARQ}.bz2" | bunzip2 > restic
  curl -fsSL "$U/rest-server/releases/download/v$REST/rest-server_${REST}_${SO}_${ARQ}.tar.gz" | tar -xz --strip-components=1 "rest-server_${REST}_${SO}_${ARQ}/rest-server"
  chmod 755 restic rest-server
fi
./restic version && ./rest-server --version
