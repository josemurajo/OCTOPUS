#!/bin/bash
# Prueba del ALMACEN EXTERNO CON BLOQUEO POR TIEMPO (Object Lock de S3), con MinIO (compatible con S3,
# Backblaze B2, Wasabi...). Lo ejecutan las pruebas de GitHub (Linux con Docker).
#   1. MinIO con un bucket con bloqueo: cada version de cada archivo queda protegida 1 dia
#   2. OCTOPUS manda alli su copia externa (las copias de los equipos y la del servidor) con su codigo real
#   3. Un "atacante" con las claves del almacen borra TODO
#   4. Se comprueba que no ha podido destruir nada y que las copias se pueden recuperar
set -uo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; BIN="$T/bin"; mkdir -p "$BIN"; export PATH="$BIN:$PATH"
FALLOS=0
pass() { echo "RESULT|PASS|$1|${2:-}"; }
fail() { echo "RESULT|FAIL|$1|${2:-}"; FALLOS=$((FALLOS + 1)); }

# --- herramientas: restic y el cliente de MinIO
bash "$RAIZ/tests/ci/herramientas.sh" "$BIN" >/dev/null
curl -fsSL -o "$BIN/mc" https://dl.min.io/client/mc/release/linux-amd64/mc && chmod 755 "$BIN/mc"

# --- 1. MinIO con bloqueo por tiempo
docker run -d --name minio -p 9000:9000 -e MINIO_ROOT_USER=octopus -e MINIO_ROOT_PASSWORD=ClaveMinio2026 \
    minio/minio server /data >/dev/null
for i in $(seq 1 30); do curl -fs http://127.0.0.1:9000/minio/health/live >/dev/null && break; sleep 1; done
mc alias set ext http://127.0.0.1:9000 octopus ClaveMinio2026 >/dev/null
mc mb --with-lock ext/octopus >/dev/null && mc retention set --default GOVERNANCE 1d ext/octopus >/dev/null \
    && pass "almacen externo con bloqueo por tiempo (1 dia)" "MinIO, compatible S3" \
    || fail "almacen externo con bloqueo por tiempo"

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
export AWS_ACCESS_KEY_ID=octopus AWS_SECRET_ACCESS_KEY=ClaveMinio2026 RESTIC_PASSWORD=ClaveExterna2026
EXT=s3:http://127.0.0.1:9000/octopus/copias
N=$(restic -r $EXT snapshots --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
[ "$N" -ge 2 ] && pass "en el externo estan la copia del equipo y la del servidor" "$N copias" \
    || fail "en el externo estan las copias" "$N copias"

# --- 3. El atacante, con las claves del almacen, intenta borrarlo todo
T0=$(date +%s); sleep 2
mc rm --recursive --force ext/octopus >/dev/null 2>&1
mc rm --recursive --force --versions ext/octopus >/dev/null 2>&1
VERS=$(mc ls --recursive --versions ext/octopus 2>/dev/null | grep -vc "DEL " || true)
[ "${VERS:-0}" -gt 0 ] && pass "el atacante no puede borrar las copias (siguen $VERS archivos protegidos)" \
    || fail "el atacante no puede borrar las copias" "no queda nada"

# --- 4. Recuperacion: se vuelve a la version anterior al borrado y se recupera el archivo
mc rb --force ext/octopus >/dev/null 2>&1 && fail "el atacante no puede borrar el bucket entero" || pass "el atacante no puede borrar el bucket entero"
mkdir -p "$T/rec"
REW="$(( $(date +%s) - T0 + 1 ))s"   # como estaba el almacen justo antes del borrado
mc cp --recursive --rewind "$REW" ext/octopus/ "$T/rec/" >/dev/null 2>&1
if RESTIC_PASSWORD=ClaveExterna2026 restic -r "$T/rec/copias" restore latest --host pc-ana --target "$T/rest" -q 2>/dev/null \
   && grep -q "factura importante" "$(find "$T/rest" -name factura.txt | head -1)"; then
    pass "las copias se recuperan despues del ataque" "factura.txt recuperada"
else
    fail "las copias se recuperan despues del ataque"
fi
docker rm -f minio >/dev/null 2>&1
exit $FALLOS
