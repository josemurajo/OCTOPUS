#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
# Prueba del ALMACEN EXTERNO CON BLOQUEO POR TIEMPO (Object Lock de S3), con MinIO (compatible con S3,
# Backblaze B2, Wasabi...). Lo ejecutan las pruebas de GitHub (Linux con Docker y la herramienta "aws").
#   1. MinIO con un bucket con bloqueo: cada version de cada archivo queda protegida 1 dia
#   2. OCTOPUS manda alli su copia externa (las copias de los equipos y la del servidor) con su codigo real
#   3. Un "atacante" con las claves del almacen intenta borrarlo TODO, version a version
#   4. Se comprueba que no ha podido destruir nada y que las copias se pueden recuperar
set -uo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; BIN="$T/bin"; mkdir -p "$BIN"; export PATH="$BIN:$PATH"
FALLOS=0
pass() { echo "RESULT|PASS|$1|${2:-}"; }
fail() { echo "RESULT|FAIL|$1|${2:-}"; FALLOS=$((FALLOS + 1)); }
export AWS_ACCESS_KEY_ID=octopus AWS_SECRET_ACCESS_KEY=ClaveMinio2026 AWS_DEFAULT_REGION=us-east-1
S3() { aws --endpoint-url http://127.0.0.1:9000 "$@"; }

bash "$RAIZ/tests/ci/herramientas.sh" "$BIN" >/dev/null

# --- 1. MinIO (la imagen ya no esta en Docker Hub: se prueban otras fuentes)
IMG=""
for i in quay.io/minio/minio:latest cgr.dev/chainguard/minio:latest bitnamilegacy/minio:latest; do
    docker pull -q "$i" >/dev/null 2>&1 && { IMG="$i"; break; }
done
[ -n "$IMG" ] || { fail "descargar MinIO" "ninguna imagen disponible"; exit 1; }
if [[ "$IMG" == bitnami* ]]; then
    docker run -d --name minio -p 9000:9000 -e MINIO_ROOT_USER=octopus -e MINIO_ROOT_PASSWORD=ClaveMinio2026 "$IMG" >/dev/null
else
    docker run -d --name minio -p 9000:9000 -e MINIO_ROOT_USER=octopus -e MINIO_ROOT_PASSWORD=ClaveMinio2026 "$IMG" server /data >/dev/null
fi
for i in $(seq 1 60); do curl -fs http://127.0.0.1:9000/minio/health/live >/dev/null && break; sleep 1; done
S3 s3api create-bucket --bucket octopus --object-lock-enabled-for-bucket >/dev/null \
 && S3 s3api put-object-lock-configuration --bucket octopus --object-lock-configuration \
      '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"GOVERNANCE","Days":1}}}' \
 && pass "almacen externo con bloqueo por tiempo (1 dia)" "$IMG" \
 || fail "almacen externo con bloqueo por tiempo" "$IMG"

# --- 2. Almacen local de OCTOPUS con una copia de un "equipo" y envio al externo con el codigo real
export OCTOPUS_BOVEDA_DIR="$T/boveda" RESTIC_CACHE_DIR="$T/cache"; mkdir -p "$OCTOPUS_BOVEDA_DIR" "$T/equipo"
echo "factura importante" > "$T/equipo/factura.txt"
CLAVE=ClaveCopiasPrueba2026
RESTIC_PASSWORD=$CLAVE restic -r "$OCTOPUS_BOVEDA_DIR/octopus-backups" init -q
RESTIC_PASSWORD=$CLAVE restic -r "$OCTOPUS_BOVEDA_DIR/octopus-backups" backup -q --host pc-ana "$T/equipo"
cd "$RAIZ"
SALIDA=$(python3 - "$CLAVE" <<'PYEOF'
import json, sys
sys.path.insert(0, "lib")
import mantenimiento as m
env = {"RESTIC_PASSWORD": sys.argv[1], "RESTIC_REPOSITORY": "rest:https://x/octopus-backups",
       "OFFSITE_RESTIC_REPOSITORY": "s3:http://127.0.0.1:9000/octopus/copias",
       "OFFSITE_RESTIC_PASSWORD": "ClaveExterna2026",
       "OFFSITE_AWS_ACCESS_KEY_ID": "octopus", "OFFSITE_AWS_SECRET_ACCESS_KEY": "ClaveMinio2026"}
print(json.dumps(m.autocopia(env)))
PYEOF
)
echo "$SALIDA"
grep -q '"ok": true' <<< "$SALIDA" && pass "OCTOPUS envia sus copias a un almacen con bloqueo" "$(echo "$SALIDA" | cut -c1-160)" \
    || fail "OCTOPUS envia sus copias a un almacen con bloqueo" "$SALIDA"
EXT=s3:http://127.0.0.1:9000/octopus/copias
N=$(RESTIC_PASSWORD=ClaveExterna2026 restic -r $EXT snapshots --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null)
[ "${N:-0}" -ge 2 ] && pass "en el externo estan la copia del equipo y la del servidor" "$N copias" \
    || fail "en el externo estan las copias" "${N:-0} copias"

# --- 3. El atacante, con las claves del almacen, intenta borrarlo todo (tambien version a version)
S3 s3 rm s3://octopus --recursive >/dev/null 2>&1
BORRADAS=0; DENEGADAS=0
while read -r key ver; do
    [ -n "$key" ] || continue
    if S3 s3api delete-object --bucket octopus --key "$key" --version-id "$ver" >/dev/null 2>&1; then BORRADAS=$((BORRADAS+1))
    else DENEGADAS=$((DENEGADAS+1)); fi
done < <(S3 s3api list-object-versions --bucket octopus --query 'Versions[].[Key,VersionId]' --output text 2>/dev/null)
[ "$DENEGADAS" -gt 0 ] && [ "$BORRADAS" -eq 0 ] \
    && pass "el atacante no puede borrar las copias" "$DENEGADAS archivos protegidos, 0 borrados" \
    || fail "el atacante no puede borrar las copias" "borrados=$BORRADAS protegidos=$DENEGADAS"
S3 s3api delete-bucket --bucket octopus >/dev/null 2>&1 && fail "el atacante no puede borrar el almacen entero" \
    || pass "el atacante no puede borrar el almacen entero"

# --- 4. Recuperacion: se quitan las "marcas de borrado" que dejo el atacante y se recupera con restic
while read -r key ver; do
    [ -n "$key" ] && S3 s3api delete-object --bucket octopus --key "$key" --version-id "$ver" >/dev/null 2>&1
done < <(S3 s3api list-object-versions --bucket octopus --query 'DeleteMarkers[].[Key,VersionId]' --output text 2>/dev/null)
# (al quitar las marcas reaparecen tambien candados viejos de restic: se lee sin candado)
ERR=$(RESTIC_PASSWORD=ClaveExterna2026 restic -r $EXT restore latest --no-lock --host pc-ana --target "$T/rest" -q 2>&1)
if grep -q "factura importante" "$(find "$T/rest" -name factura.txt 2>/dev/null | head -1)" 2>/dev/null; then
    pass "las copias se recuperan despues del ataque" "factura.txt recuperada del almacen externo"
else
    fail "las copias se recuperan despues del ataque" "$(echo "$ERR" | tail -3 | tr '\n' ' ')"
fi
docker rm -f minio >/dev/null 2>&1
exit $FALLOS
