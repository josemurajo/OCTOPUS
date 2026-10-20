#!/usr/bin/env bash
# Prueba del instalador de Proxmox (install/proxmox/octopus-lxc.sh) con un Proxmox simulado:
# pct / pveam / pvesh / pvesm falsos que apuntan lo que se les pide y contestan como uno de verdad.
# Comprueba lo importante: contenedor sin privilegios con nesting, no pisa un contenedor existente,
# arranca OCTOPUS con la IP del contenedor y da al usuario la dirección y la contraseña.
set -uo pipefail
RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$RAIZ/install/proxmox/octopus-lxc.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FALLOS=0
ok()  { echo "PASS $*"; }
mal() { echo "FAIL $*"; FALLOS=$((FALLOS+1)); }

mkdir -p "$TMP/bin"
cat > "$TMP/bin/pct" <<'EOF'
#!/usr/bin/env bash
echo "pct $*" >> "$LOG"
case "$1" in
  status) [ "$2" = "${EXISTE:-none}" ] && { echo "status: running"; exit 0; }; exit 2 ;;
  create) exit 0 ;;
  exec)   shift 3; cmd="$3"
          case "$cmd" in
            *"hostname -I"*) echo "10.9.8.7" ;;
            *getent*) exit 0 ;;
            *get.docker.com*) exit 0 ;;
            *"docker compose up"*) echo "$cmd" >> "$LOG.compose"; exit 0 ;;
            *healthz*) exit 0 ;;
            *CREDENCIALES*) echo "ClaveDePrueba123" ;;
          esac ;;
esac
EOF
cat > "$TMP/bin/pveam" <<'EOF'
#!/usr/bin/env bash
echo "pveam $*" >> "$LOG"
case "$1" in
  available) printf 'system          debian-11-standard_11.7-1_amd64.tar.zst\nsystem          debian-12-standard_12.7-1_amd64.tar.zst\n' ;;
  list) echo "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst" ;;
esac
exit 0
EOF
cat > "$TMP/bin/pvesh" <<'EOF'
#!/usr/bin/env bash
echo 105
EOF
cat > "$TMP/bin/pvesm" <<'EOF'
#!/usr/bin/env bash
echo "Name Type Status Total Used Available %"
case "$*" in
  *rootdir*) echo "local-lvm lvmthin active 100 1 99 1%" ;;
  *vztmpl*)  echo "local dir active 100 1 99 1%" ;;
esac
EOF
cat > "$TMP/bin/id" <<'EOF'
#!/usr/bin/env bash
[ "$1" = "-u" ] && { echo "${FALSO_UID:-0}"; exit 0; }; exec /usr/bin/id "$@"
EOF
chmod +x "$TMP/bin/"*
export PATH="$TMP/bin:$PATH" OCTOPUS_SIN_PREGUNTAS=1 LOG="$TMP/log"

# 1. instalación normal
: > "$LOG"
salida="$(bash "$SCRIPT" </dev/null 2>&1)"; rc=$?
[ $rc -eq 0 ] && ok "instala sin errores" || { mal "instala sin errores (rc=$rc)"; echo "$salida" | tail -20; }
grep -q "pct create 105 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst" "$LOG" && ok "usa el siguiente número libre y Debian 12" || mal "número/plantilla"
grep -q -- "--unprivileged 1" "$LOG" && grep -q -- "--features nesting=1,keyctl=1" "$LOG" && ok "contenedor sin privilegios con nesting (lo que pide Docker)" || mal "privilegios/nesting"
grep -q -- "--rootfs local-lvm:64" "$LOG" && ok "disco de 64 GB en el almacenamiento que admite contenedores" || mal "disco"
grep -q -- "--onboot 1" "$LOG" && ok "arranca solo con Proxmox" || mal "onboot"
grep -q "OCTOPUS_IP=10.9.8.7" "$LOG.compose" && ok "pone la IP del contenedor en OCTOPUS" || mal "IP en compose"
grep -q "TZ=" "$LOG.compose" && ! grep -q "TZ=.*/.*/.*|" "$LOG.compose" && ok "pone la zona horaria" || mal "zona horaria"
echo "$salida" | grep -q "https://10.9.8.7:8443" && echo "$salida" | grep -q "ClaveDePrueba123" && ok "dice al usuario la dirección y la contraseña" || mal "mensaje final"
grep -q "pveam download" "$LOG" && mal "no descarga la plantilla si ya está" || ok "no descarga la plantilla si ya está"

# 2. no pisa un contenedor que ya existe
: > "$LOG"
salida="$(EXISTE=105 bash "$SCRIPT" </dev/null 2>&1)"; rc=$?
[ $rc -ne 0 ] && echo "$salida" | grep -q "No lo toco" && ! grep -q "pct create" "$LOG" && ok "no toca un contenedor existente" || mal "contenedor existente"

# 3. datos raros
salida="$(OCTOPUS_DISCO=abc bash "$SCRIPT" </dev/null 2>&1)"; [ $? -ne 0 ] && echo "$salida" | grep -q "número de GB" && ok "rechaza un disco que no es un número" || mal "disco raro"
salida="$(OCTOPUS_CTID=12a bash "$SCRIPT" </dev/null 2>&1)"; [ $? -ne 0 ] && ok "rechaza un número de contenedor raro" || mal "ctid raro"

# 4. sin root / sin Proxmox
salida="$(FALSO_UID=1000 bash "$SCRIPT" </dev/null 2>&1)"; [ $? -ne 0 ] && echo "$salida" | grep -q "root" && ok "pide ser root" || mal "root"
salida="$(PATH="$(echo "$PATH" | sed "s#$TMP/bin:##")" bash -c "id(){ [ \"\$1\" = -u ] && echo 0; }; export -f id; bash '$SCRIPT'" </dev/null 2>&1)"
echo "$salida" | grep -q "no parece un Proxmox" && ok "avisa si no es un Proxmox" || mal "no proxmox"

echo "FALLOS: $FALLOS"
[ $FALLOS -eq 0 ]
