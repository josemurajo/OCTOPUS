#!/usr/bin/env bash
# Prueba del paquete para NAS (install/nas/docker-compose.yml) tal cual lo usará la gente:
# construye la imagen, la arranca con ESE archivo (solo cambiando la IP), y comprueba que
#   - el panel responde en el puerto del NAS (8443) y el almacén en el 8444,
#   - la primera contraseña sale en el Registro del contenedor y sirve para entrar,
#   - al cambiarla deja de salir en el Registro (y se borra el archivo),
#   - los datos quedan en las carpetas ./datos y ./copias (sobreviven a borrar el contenedor).
set -uo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGEN="${OCTOPUS_IMAGEN_PRUEBA:-octopus-nas:prueba}"
NOMBRE="octopus-nas-prueba"   # para no chocar con otro "octopus" que ya esté funcionando
DIR="$(mktemp -d)"
FALLOS=0
ok()  { echo "PASS $*"; }
mal() { echo "FAIL $*"; FALLOS=$((FALLOS+1)); }
# lo que crea el contenedor es de root y con permisos 700: mirarlo con sudo si hace falta
existe() { [ -e "$1" ] || sudo -n test -e "$1" 2>/dev/null; }
limpiar() { [ -n "${OCTOPUS_DEJAR:-}" ] && return; (cd "$DIR" && docker compose down >/dev/null 2>&1); sudo rm -rf "$DIR" 2>/dev/null || rm -rf "$DIR"; }
trap limpiar EXIT

if [ -z "${OCTOPUS_SIN_CONSTRUIR:-}" ]; then
    docker build -q -t "$IMAGEN" "$RAIZ" >/dev/null || { echo "FAIL no se pudo construir la imagen"; exit 1; }
fi
ok "imagen construida"

sed -e "s#image: ghcr.io/josemurajo/octopus:latest#image: $IMAGEN#" \
    -e "s#OCTOPUS_IP=192.168.1.20#OCTOPUS_IP=127.0.0.1#" -e "s#container_name: octopus#container_name: $NOMBRE#" -e "s#^name: octopus#name: octopus-nas-prueba#" "$RAIZ/install/nas/docker-compose.yml" > "$DIR/docker-compose.yml"
grep -q "image: $IMAGEN" "$DIR/docker-compose.yml" && ok "el archivo del NAS solo necesita cambiar la IP" || mal "sustitucion"

(cd "$DIR" && docker compose up -d) >/dev/null 2>&1 || { mal "docker compose up"; exit 1; }
for _ in $(seq 1 90); do curl -fsk -m 3 https://127.0.0.1:8443/healthz >/dev/null 2>&1 && break; sleep 2; done
curl -fsk -m 3 https://127.0.0.1:8443/healthz >/dev/null && ok "panel en https://IP:8443" || { mal "el panel no responde"; docker logs --tail 60 $NOMBRE; exit 1; }
codigo="$(curl -sk -m 5 -o /dev/null -w '%{http_code}' https://127.0.0.1:8444/)"
[[ "$codigo" =~ ^[24] ]] && ok "almacén en https://IP:8444 ($codigo)" || mal "almacén ($codigo)"

for _ in $(seq 1 30); do docker logs $NOMBRE 2>&1 | grep -qi "contrasena (de un solo uso)" && break; sleep 1; done
CLAVE="$(docker logs $NOMBRE 2>&1 | grep -i 'contrasena' | grep -o ': [^ ]*$' | tail -1 | cut -c3-)"
docker logs $NOMBRE 2>&1 | grep -q "PRIMER ACCESO" && [ -n "$CLAVE" ] && ok "la primera contraseña sale en el Registro" \
    || { mal "contraseña en el Registro"; docker logs --tail 40 $NOMBRE; }
existe "$DIR/datos/panel/CREDENCIALES_INICIALES.txt" && ok "los datos están en la carpeta ./datos" || mal "carpeta ./datos"
[ -d "$DIR/copias" ] && [ -n "$(ls -A "$DIR/copias" 2>/dev/null || sudo ls -A "$DIR/copias")" ] && ok "el almacén está en la carpeta ./copias" || mal "carpeta ./copias"

python3 - "$CLAVE" <<'EOF'
import re, sys, requests, urllib3
urllib3.disable_warnings()
B = "https://127.0.0.1:8443"; s = requests.Session(); s.verify = False; s.trust_env = False
def csrf(path): return re.search(r'name="csrf_token" value="([^"]+)"', s.get(B + path).text).group(1)
r = s.post(B + "/login", data={"csrf_token": csrf("/login"), "username": "admin", "password": sys.argv[1]},
           headers={"Referer": B + "/login"}, allow_redirects=True)
ok1 = "contrasena" in r.url or "Contraseña nueva" in r.text
print("PASS" if ok1 else "FAIL", "entrar con la contraseña del Registro (y pide cambiarla)", r.url)
nueva = "UnaClaveNueva-2026!x"
r = s.post(B + "/cuenta/contrasena", data={"csrf_token": csrf("/cuenta/contrasena"), "actual": sys.argv[1],
           "nueva": nueva, "repetir": nueva}, headers={"Referer": B + "/cuenta/contrasena"}, allow_redirects=True)
ok2 = "cambiada" in r.text
print("PASS" if ok2 else "FAIL", "cambiar la contraseña")
sys.exit(0 if ok1 and ok2 else 1)
EOF
[ $? -eq 0 ] || FALLOS=$((FALLOS+1))

existe "$DIR/datos/panel" && ! existe "$DIR/datos/panel/CREDENCIALES_INICIALES.txt" && ok "al cambiarla se borra el archivo con la contraseña inicial" || mal "archivo no borrado"
(cd "$DIR" && docker compose down >/dev/null 2>&1 && docker compose up -d >/dev/null 2>&1)
for _ in $(seq 1 60); do curl -fsk -m 3 https://127.0.0.1:8443/healthz >/dev/null 2>&1 && break; sleep 2; done
sleep 3
curl -fsk -m 3 https://127.0.0.1:8443/healthz >/dev/null && ok "tras borrar y recrear el contenedor sigue funcionando" || mal "recrear"
docker logs $NOMBRE 2>&1 | grep -q "PRIMER ACCESO" && mal "la contraseña ya no debe salir en el Registro" || ok "la contraseña ya no sale en el Registro"

echo "FALLOS: $FALLOS"
[ $FALLOS -eq 0 ]
