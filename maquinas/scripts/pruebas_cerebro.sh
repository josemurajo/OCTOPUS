#!/bin/bash
# OCTOPUS v2 - Bateria de pruebas REALES. Se ejecuta en la VM cerebro (anfitrion del contenedor "octopus"):
#   sudo bash /vagrant_host/scripts/pruebas_cerebro.sh todo cliente1 cliente2 ...
#   sudo bash /vagrant_host/scripts/pruebas_cerebro.sh cerebro            (solo el servidor)
#   sudo bash /vagrant_host/scripts/pruebas_cerebro.sh limpiar            (libera incidentes de pruebas anteriores)
#   sudo bash /vagrant_host/scripts/pruebas_cerebro.sh health|backup <equipo|ip>
#   sudo bash /vagrant_host/scripts/pruebas_cerebro.sh restaurar <equipo|ip> <ruta>
#   sudo bash /vagrant_host/scripts/pruebas_cerebro.sh simular cliente1   (demo manual, ver DEMO_ATAQUE.bat)
#
# En la v2 todo el servidor vive en el contenedor "octopus" y el servidor NUNCA entra en los equipos:
# cada agente recoge sus ordenes por HTTPS. Por eso aqui:
#   - las ordenes a los agentes van por la cola:  docker exec octopus python lib/equipos_cli.py pedir ...
#   - copia, restauracion, explorar, incidente, liberar y kit se prueban A TRAVES DEL PANEL (como un usuario)
#     con un usuario de pruebas temporal (se crea al empezar y se borra al terminar; no toca al admin)
#   - el SSH a los clientes (solo para estropear/comprobar archivos) sale del contenedor con su clave
#   - NO se simulan ataques: el incidente se declara desde el panel (la demo de ataque es manual)
#
# Cada comprobacion imprime:  RESULT|PASS|nombre|detalle   RESULT|FAIL|...   RESULT|WARN|...
set -uo pipefail

C=octopus                                   # nombre del contenedor
SSH_PASS="${OCTOPUS_SSH_PASS:-vagrant123}"
declare -A IPS=( [cliente1]=192.168.10.20 [cliente2]=192.168.20.20 [debian12]=192.168.10.60 [rocky9]=192.168.10.50 [win2022]=192.168.10.40 )
declare -A DIR_PRUEBA=( [cliente1]=/home/vagrant/testfiles/critico [cliente2]=/home/vagrant/database )
# Carpetas protegidas de los equipos que se instalan con el instalador del panel
declare -A RUTAS=( [win2022]='["C:\\OctopusTest"]' [cliente1]='["/home/vagrant/testfiles","/home/vagrant/datos","/etc/miapp"]' )
PANEL="${OCTOPUS_PANEL:-https://127.0.0.1:8080}"
TMP="$(mktemp -d /tmp/octopus_pruebas.XXXXXX)"
JAR="$TMP/cookies"
TUSER="pruebas_auto"
TPASS="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"

# Progreso en vivo (se ve desde Windows en reportes\progreso_pruebas.log)
PROG=/vagrant_host/reportes/progreso_pruebas.log
[ -d /vagrant_host/reportes ] || PROG=/dev/null
log()  { echo "[$(date +%H:%M:%S)] $*" >> "$PROG" 2>/dev/null; }
pass() { echo "RESULT|PASS|$1|${2:-}"; log "PASS $1 ${2:-}"; }
fail() { echo "RESULT|FAIL|$1|${2:-}"; log "FAIL $1 ${2:-}"; }
warn() { echo "RESULT|WARN|$1|${2:-}"; log "WARN $1 ${2:-}"; }
check() { local name="$1"; shift; local out; if out=$("$@" 2>&1); then pass "$name" "$(echo "$out" | tail -1 | cut -c1-150)"; else fail "$name" "$(echo "$out" | tail -3 | tr '\n' ' ' | cut -c1-250)"; fi; }
corto() { tr '\n' ' ' | cut -c1-${1:-200}; }

# ------------------------------------------------------------------ utilidades del contenedor
dx()  { docker exec -i -w /app "$C" "$@"; }
envv() { dx cat /app/.env 2>/dev/null | grep -E "^$1=" | head -1 | cut -d= -f2- | tr -d '\r"'; }
CLI() { log "  equipos_cli $*"; dx python lib/equipos_cli.py "$@"; }
INC() { log "  incidentes $*"; timeout 900 docker exec -w /app "$C" python lib/incidentes.py "$@" 2>/dev/null | tail -1; }
jget() { python3 -c 'import json,sys
try: d=json.loads(sys.stdin.read() or "{}")
except ValueError: d={}
v=d
for k in sys.argv[1].split("."): v=v.get(k) if isinstance(v,dict) else None
print(v if v is not None else "")' "$1"; }
es_ok() { python3 -c 'import json,sys
try: d=json.loads(sys.stdin.read() or "{}")
except ValueError: sys.exit(1)
sys.exit(0 if d.get("status") in ("success","ok") else 1)'; }

# Python dentro del contenedor con el .env cargado (asi se usan las mismas funciones que el panel)
PY_PRE='import os, sys, json
sys.path.insert(0, "/app/lib")
for _l in open("/app/.env", encoding="utf-8"):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _v = _l.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip(chr(34)))
DB = os.environ.get("DB_PATH", "./data/admin_panel.db")
DB = DB if os.path.isabs(DB) else os.path.join("/app", DB)
'
pyc() { local code="$1"; shift; printf '%s\n%s\n' "$PY_PRE" "$code" | docker exec -i -w /app "$C" python - "$@"; }

# Nombre del equipo a partir de nombre o IP (las ordenes van por nombre)
equipo_de() { local x="$1" h; for h in "${!IPS[@]}"; do [ "${IPS[$h]}" = "$x" ] && { echo "$h"; return; }; done; echo "$x"; }

# Orden a un agente por la cola:  pedir <equipo> GET|POST <ruta> [json] [segundos]
pedir() { CLI pedir "$1" "$2" "$3" "${4:-}" "${5:-60}" 2>/dev/null; }

# Copias de un equipo leidas DIRECTAMENTE del almacen (lo mismo que ve el panel)
copias() {
    pyc 'import agentes
d, e = agentes.copias_por_equipo(force=True)
l = [c for c in d.get(sys.argv[1].lower(), []) if "forense" not in c["tags"]]
print(json.dumps({"error": e, "n": len(l), "ultima": l[0]["id"] if l else "",
                  "edad": int((__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - l[0]["time"]).total_seconds()) if l and l[0]["time"] else -1,
                  "ids": [c["id"] for c in l]}))' "$1"
}

# Comando como root en un cliente, por SSH desde el contenedor (clave del servidor; contrasena solo si aun no hay clave)
remote() { # remote <ip> <comando>
    local b64; b64=$(printf '%s' "$2" | base64 -w0)
    docker exec -e RIP="$1" -e RB64="$b64" -e RPASS="$SSH_PASS" "$C" bash -c '
        o=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3)
        cmd="f=\$(mktemp); echo $RB64 | base64 -d > \$f; echo $RPASS | sudo -S -p \"\" bash \$f; r=\$?; rm -f \$f; exit \$r"
        if [ -f /root/.ssh/octopus_ed25519 ] && ssh -i /root/.ssh/octopus_ed25519 -o BatchMode=yes "${o[@]}" "vagrant@$RIP" true 2>/dev/null; then
            timeout 180 ssh -i /root/.ssh/octopus_ed25519 -o BatchMode=yes "${o[@]}" "vagrant@$RIP" "$cmd"
        else
            timeout 180 sshpass -p "$RPASS" ssh "${o[@]}" "vagrant@$RIP" "$cmd"
        fi'
}

# ------------------------------------------------------------------ panel web (como un usuario de verdad)
pcurl() { curl -sk -m "${PT:-60}" -c "$JAR" -b "$JAR" "$@"; }
csrf_pagina() { pcurl "$PANEL/ajustes" | grep -o 'name="csrf-token" content="[^"]*"' | head -1 | cut -d'"' -f4; }
panel_post() { # panel_post <ruta> campo=valor ...   -> imprime la direccion a la que redirige
    local ruta="$1"; shift
    local args=(--data-urlencode "csrf_token=$(csrf_pagina)") kv
    for kv in "$@"; do args+=(--data-urlencode "$kv"); done
    pcurl -o /dev/null -w '%{redirect_url}' "${args[@]}" "$PANEL$ruta"
}
system_id() { CLI id "$1" 2>/dev/null; }

crear_usuario_pruebas() {
    local out; out=$(pyc 'import sqlite3, hashlib, secrets
u, p = sys.argv[1], sys.argv[2]
salt = secrets.token_hex(16)
h = "pbkdf2$%s$%s" % (salt, hashlib.pbkdf2_hmac("sha256", p.encode(), salt.encode(), 310000).hex())
c = sqlite3.connect(DB, timeout=30)
c.execute("DELETE FROM users WHERE username = ?", (u,))
c.execute("INSERT INTO users (username, email, password_hash, role, must_change_password) VALUES (?, ?, ?, ?, 0)",
          (u, u + "@pruebas.local", h, "admin"))
c.commit()
# doble autenticacion activada, como la tendria un administrador de verdad (el secreto solo lo conoce esta prueba)
import dosfa
dosfa.init(DB)
sec = dosfa.nuevo_secreto()
c.execute("UPDATE users SET totp_secreto = ?, totp_activo = 1, totp_ultimo = 0 WHERE username = ?", (dosfa.cifrar(DB, sec), u))
c.commit()
print("ok", sec)' "$TUSER" "$TPASS") || return 1
    [[ "$out" == ok\ * ]] || return 1
    echo "${out#ok }" > "$TMP/tsecreto"; rm -f "$TMP/tpaso"; echo ok
}
# codigo de la app del movil para el usuario de pruebas (uno que no se haya usado: el panel no acepta el mismo dos veces)
codigo_2fa() {
    local r; r=$(pyc 'import dosfa, time
s, ultimo = sys.argv[1], int(sys.argv[2] or 0)
while True:
    ahora = int(time.time() // 30)
    for d in (0, 1):
        if ahora + d > ultimo:
            print(dosfa.codigo(s, desfase=d), ahora + d); sys.exit(0)
    time.sleep(3)' "$(cat "$TMP/tsecreto")" "$(cat "$TMP/tpaso" 2>/dev/null)")
    echo "${r#* }" > "$TMP/tpaso"; echo "${r%% *}"
}
borrar_usuario_pruebas() {
    pyc 'import sqlite3
c = sqlite3.connect(DB, timeout=30)
c.execute("DELETE FROM users WHERE username = ?", (sys.argv[1],))
c.commit()' "$TUSER" >/dev/null 2>&1 || true
}
limpiar_al_salir() { borrar_usuario_pruebas; rm -rf "$TMP"; }
trap limpiar_al_salir EXIT

# El panel admite 5 peticiones a /login por minuto (proteccion contra fuerza bruta): aqui se usan 4 como mucho.
LOGIN_TOK=""
login_token() { rm -f "$JAR"; LOGIN_TOK=$(pcurl "$PANEL/login" | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | cut -d'"' -f4); }
login_post()  { # login_post <contrasena> <formato curl>; si pide el codigo del movil, lo escribe (segundo paso)
    local out; out=$(pcurl -o /dev/null -w "%{redirect_url}|$2" --data-urlencode "csrf_token=$LOGIN_TOK" \
                --data-urlencode "username=$TUSER" --data-urlencode "password=$1" "$PANEL/login")
    if [[ "${out%%|*}" == */login/codigo ]]; then
        echo 1 > "$TMP/pide_codigo"
        local t; t=$(pcurl "$PANEL/login/codigo" | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | cut -d'"' -f4)
        pcurl -o /dev/null -w "$2" --data-urlencode "csrf_token=$t" --data-urlencode "codigo=$(codigo_2fa)" "$PANEL/login/codigo"
    else echo "${out#*|}"; fi
}
sesion_activa() { [ "$(pcurl -o /dev/null -w '%{http_code}' "$PANEL/ajustes")" = 200 ]; }
panel_login() { # deja la sesion en $JAR; devuelve 0 si entra
    sesion_activa && return 0
    login_token
    [[ "$(login_post "$TPASS" '%{redirect_url}')" == *inicio* ]]
}

# ================================================================== 1. SERVIDOR
pruebas_cerebro() {
    check "cerebro: contenedor octopus en marcha" bash -c "docker inspect -f '{{.State.Running}}' $C | grep -q true && echo en marcha"
    local salud=""
    for i in $(seq 1 30); do
        salud=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$C" 2>/dev/null)
        [ "$salud" = healthy ] && break; sleep 4
    done
    [ "$salud" = healthy ] && pass "cerebro: contenedor sano (healthcheck)" || fail "cerebro: contenedor sano (healthcheck)" "estado=$salud"
    check "cerebro: panel web responde (8080)" bash -c "curl -fsSk -m 5 -o /dev/null -w '%{http_code}' $PANEL/healthz"
    check "cerebro: estado interno correcto (/healthz)" bash -c "curl -fsSk -m 10 $PANEL/healthz"
    local c; c=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:8080/healthz")
    [ "$c" = 000 ] || [ "$c" = 400 ] && pass "cerebro: panel solo cifrado (sin HTTP plano)" || fail "cerebro: panel solo cifrado (sin HTTP plano)" "HTTP responde $c"

    # Puertos publicados: solo 8080 (panel/ordenes) y 8000 (almacen)
    local puertos; puertos=$(docker port "$C" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')
    if [ "$(echo "$puertos" | tr ' ' '\n' | grep -v '^$' | grep -cv -e '^8080/tcp$' -e '^8000/tcp$')" = 0 ]; then
        pass "cerebro: solo 2 puertos abiertos" "$puertos"
    else fail "cerebro: solo 2 puertos abiertos" "$puertos"; fi
    if curl -s -m 3 -o /dev/null http://192.168.10.10:8081/ 2>/dev/null; then fail "cerebro: nada mas escuchando (8081)" "responde en 8081"
    else pass "cerebro: nada mas escuchando (8081)"; fi

    # Autoridad de certificados propia: los equipos validan el certificado (no se acepta "cualquiera")
    dx cat /app/data/tls/ca.crt > "$TMP/ca.crt" 2>/dev/null
    local ipc
    for ipc in 192.168.10.10 192.168.20.10; do
        c=$(curl -s --cacert "$TMP/ca.crt" -m 5 -o /dev/null -w '%{http_code}' "https://$ipc:8080/healthz" 2>&1)
        [ "$c" = 200 ] && pass "cerebro: certificado valido para $ipc (panel)" "firmado por la autoridad de OCTOPUS" \
                       || fail "cerebro: certificado valido para $ipc (panel)" "codigo=$c (falta $ipc en el certificado?)"
        c=$(curl -s --cacert "$TMP/ca.crt" -m 5 -o /dev/null -w '%{http_code}' "https://$ipc:8000/" 2>&1)
        [ "$c" = 401 ] && pass "cerebro: almacen cifrado y con contrasena en $ipc (8000)" "HTTPS valido, sin clave -> 401" \
                       || fail "cerebro: almacen cifrado y con contrasena en $ipc (8000)" "codigo=$c"
    done
    # (con pipefail, "cmd | grep -q" puede fallar aunque encuentre el texto: se guarda antes la salida)
    local procs; procs=$(docker exec "$C" ps -eo args 2>/dev/null)
    grep -q -- "rest-server.*--append-only" <<< "$procs" \
        && pass "cerebro: almacen en modo solo-anadir" "los equipos no pueden borrar copias" \
        || fail "cerebro: almacen en modo solo-anadir"

    # Seguridad del panel
    local nocsrf; nocsrf=$(curl -sk -m 10 -o /dev/null -w '%{redirect_url}' --data-urlencode "username=admin" --data-urlencode "password=x" "$PANEL/login")
    [[ "$nocsrf" == */login* ]] && pass "cerebro: panel rechaza formularios sin token CSRF" || fail "cerebro: panel rechaza formularios sin token CSRF" "$nocsrf"
    local hdr; hdr=$(curl -skI -m 5 "$PANEL/healthz")
    echo "$hdr" | grep -qi "content-security-policy" && echo "$hdr" | grep -qi "x-frame-options" \
        && pass "cerebro: cabeceras de seguridad del panel" || fail "cerebro: cabeceras de seguridad del panel"
    c=$(curl -sk -m 5 -o /dev/null -w '%{http_code}' -X POST -H "Content-Type: application/json" -H "X-Octopus-Equipo: cliente1" \
        -H "X-Octopus-Token: clave-falsa-$RANDOM" -d '{}' "$PANEL/api/agente/ordenes")
    [ "$c" = 401 ] && pass "cerebro: canal de agentes rechaza claves falsas" "401" || fail "cerebro: canal de agentes rechaza claves falsas" "codigo=$c"

    # Usuario de pruebas y login real
    if crear_usuario_pruebas >/dev/null 2>&1; then pass "cerebro: usuario de pruebas temporal creado" "$TUSER (se borra al terminar)"
    else fail "cerebro: usuario de pruebas temporal creado"; fi
    login_token
    local bad; bad=$(login_post "incorrecta" '%{http_code}')
    [ "$bad" = 200 ] && pass "cerebro: login con contrasena incorrecta rechazado" || fail "cerebro: login con contrasena incorrecta rechazado" "codigo=$bad"
    rm -f "$TMP/pide_codigo"
    local loc; loc=$(login_post "$TPASS" '%{redirect_url}')
    if [[ "$loc" == *inicio* ]]; then pass "cerebro: login en el panel" "usuario $TUSER"; else fail "cerebro: login en el panel" "redireccion='$loc'"; fi
    [ -f "$TMP/pide_codigo" ] && pass "cerebro: al entrar pide el codigo del movil (doble autenticacion)" \
                           || fail "cerebro: al entrar pide el codigo del movil (doble autenticacion)"
    # sin el codigo no hay sesion
    local j2="$TMP/jar_sin_codigo" t2 l2
    t2=$(curl -sk -c "$j2" -b "$j2" "$PANEL/login" | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | cut -d'"' -f4)
    curl -sk -c "$j2" -b "$j2" -o /dev/null --data-urlencode "csrf_token=$t2" --data-urlencode "username=$TUSER" --data-urlencode "password=$TPASS" "$PANEL/login"
    l2=$(curl -sk -c "$j2" -b "$j2" -o /dev/null -w '%{redirect_url}' "$PANEL/inicio")
    [[ "$l2" == */login* ]] && pass "cerebro: con la contrasena sola no se entra" || fail "cerebro: con la contrasena sola no se entra" "$l2"
    rm -f "$j2"

    # Repositorios restic (copias y cuarentena) accesibles desde el servidor
    check "cerebro: repositorio de copias accesible" docker exec -w /app "$C" sh -c \
        'set -a; . /app/.env; set +a; restic cat config >/dev/null && echo "copias OK"'
    check "cerebro: repositorio de cuarentena accesible" docker exec -w /app "$C" sh -c \
        'set -a; . /app/.env; set +a; RESTIC_REPOSITORY="$RESTIC_REPOSITORY_CUARENTENA" RESTIC_PASSWORD="$RESTIC_PASSWORD_CUARENTENA" restic cat config >/dev/null && echo "cuarentena OK"'
}

# ================================================================== 2a. INSTALAR DESDE EL PANEL CON LA CONTRASENA DEL EQUIPO
prueba_instalacion_remota() {
    local h="$1" lan="${IPS[$1]}" sid loc pag res=""
    log "$h: alta e instalacion a distancia desde el panel"
    sid=$(system_id "$h")
    if [ -z "$sid" ]; then
        # "Anadir equipo" con IP, usuario y contrasena: alta e instalacion en un solo paso
        local rutas; rutas=$(python3 -c 'import json,sys; print("\n".join(json.loads(sys.argv[1])))' "${RUTAS[$h]}")
        loc=$(panel_post /equipos/nuevo os_family=linux "hostname=$h" "rutas=$rutas" modo=remoto "ip_address=$lan" \
              usuario=vagrant "password=$SSH_PASS" solo_clave=1)
        sid=$(system_id "$h")
        [ -n "$sid" ] && pass "$h: anadido desde el panel con IP, usuario y contrasena" "instalacion lanzada" \
            || { fail "$h: anadido desde el panel con IP, usuario y contrasena" "$loc"; return; }
    else
        # ya estaba dado de alta (otra ejecucion): se reinstala desde su pagina "Instalador"
        loc=$(panel_post "/equipos/$sid/instalar-remoto" "ip=$lan" "usuario=vagrant" "password=$SSH_PASS" "solo_clave=1")
        [[ "$loc" == */equipos/$sid ]] && pass "$h: reinstalacion a distancia lanzada desde el panel" \
            || { fail "$h: reinstalacion a distancia lanzada desde el panel" "$loc"; return; }
    fi
    for i in $(seq 1 120); do   # hasta 6 minutos
        sleep 3
        pag=$(pcurl "$PANEL/equipos/$sid")
        res=$(grep -o 'Instalación terminada[^<]*</strong>[^<]*\|La instalación no ha terminado bien[^<]*</strong>[^<]*' <<< "$pag" | head -1 | sed 's#</strong># #')
        [ -n "$res" ] && break
    done
    if [[ "$res" == Instalación\ terminada* ]]; then pass "$h: instalado desde el panel con la contrasena del equipo" "$(cut -c1-180 <<< "$res")"
    else fail "$h: instalado desde el panel con la contrasena del equipo" "${res:-sin respuesta en 6 min}"; fi
}

# ================================================================== 2. INSTALADOR DEL PANEL ("Anadir equipo")
prueba_instalador_linux() {
    local h="$1" lan="${IPS[$1]}" sid
    log "$h: probando el instalador que da el panel"
    sid=$(system_id "$h")
    [ -n "$sid" ] || { fail "$h: instalador del panel descargado" "el equipo no esta dado de alta"; return; }
    local zip="$TMP/octopus-$h.zip"
    PT=120 pcurl -o "$zip" --data-urlencode "csrf_token=$(csrf_pagina)" "$PANEL/equipos/$sid/instalador"
    if python3 -c 'import zipfile,sys; n=zipfile.ZipFile(sys.argv[1]).namelist(); sys.exit(0 if {"instalar_linux.sh","config.json","zerotouch_agent.py"} <= set(n) else 1)' "$zip" 2>/dev/null; then
        pass "$h: instalador del panel descargado" "$(stat -c %s "$zip") bytes, clave nueva para el equipo"
    else fail "$h: instalador del panel descargado" "$(head -c 200 "$zip" | corto)"; return; fi
    docker cp "$zip" "$C:/tmp/octopus-$h.zip" >/dev/null
    docker exec "$C" sh -c "scp -i /root/.ssh/octopus_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR /tmp/octopus-$h.zip vagrant@$lan:/tmp/octopus.zip; r=\$?; rm -f /tmp/octopus-$h.zip; exit \$r" \
        || { fail "$h: instalacion con el instalador del panel" "no se pudo copiar el zip al equipo"; return; }
    local out
    out=$(remote "$lan" "rm -rf /tmp/octopus_inst && mkdir /tmp/octopus_inst && cd /tmp/octopus_inst && python3 -m zipfile -e /tmp/octopus.zip . && bash instalar_linux.sh 2>&1 | tail -4; cd /; rm -rf /tmp/octopus_inst /tmp/octopus.zip")
    if echo "$out" | grep -q "OCTOPUS instalado"; then pass "$h: instalacion con el instalador del panel" "$(echo "$out" | grep -m1 instalado | corto 120)"
    else fail "$h: instalacion con el instalador del panel" "$(echo "$out" | corto 250)"; fi
    local ok=1
    for i in $(seq 1 30); do CLI conectado "$h" && { ok=0; break; }; sleep 2; done
    [ $ok = 0 ] && pass "$h: conectado al servidor con la clave nueva" || fail "$h: conectado al servidor con la clave nueva" "no aparece conectado en 60 s"
}

# ================================================================== 3. POR CADA CLIENTE LINUX
prueba_cliente_linux() {
    local h="$1" lan="${IPS[$1]}" out sid
    local d="${DIR_PRUEBA[$h]:-/home/vagrant/testfiles/critico}"
    local f=/home/vagrant/testfiles/critico/config.txt
    check "$h: ping desde el cerebro ($lan)" ping -c 2 -W 2 "$lan"

    # Acceso SSH: solo con la clave del servidor
    if docker exec "$C" ssh -i /root/.ssh/octopus_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
            -o LogLevel=ERROR -o ConnectTimeout=10 "vagrant@$lan" true 2>/dev/null; then
        pass "$h: acceso SSH con clave del servidor"
        if docker exec "$C" sshpass -p "$SSH_PASS" ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password \
                -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=10 "vagrant@$lan" true 2>/dev/null; then
            fail "$h: acceso SSH con contrasena desactivado" "todavia se puede entrar con contrasena"
        else pass "$h: acceso SSH con contrasena desactivado"; fi
    else
        fail "$h: acceso SSH con clave del servidor" "la clave no funciona"
    fi

    # El equipo no tiene puertos abiertos: el agente se conecta el al servidor
    if curl -s -m 4 -o /dev/null "http://$lan:9999/health" 2>/dev/null; then fail "$h: agente sin puertos abiertos en la red" "responde en $lan:9999"
    else pass "$h: agente sin puertos abiertos en la red" "9999 solo en 127.0.0.1"; fi
    local ok=1
    for i in $(seq 1 15); do CLI conectado "$h" && { ok=0; break; }; sleep 2; done
    [ $ok = 0 ] && pass "$h: agente conectado al servidor (HTTPS saliente)" || { fail "$h: agente conectado al servidor (HTTPS saliente)" "no pregunta por ordenes"; return; }
    if out=$(pedir "$h" GET /health "" 20) && echo "$out" | es_ok; then pass "$h: agente responde por la cola de ordenes" "$(echo "$out" | corto 150)"
    else fail "$h: agente responde por la cola de ordenes" "$(echo "$out" | corto)"; return; fi

    # Copia
    out=$(pedir "$h" POST /webhook/backup "{}" 900)
    local snap; snap=$(echo "$out" | jget snapshot_id)
    if echo "$out" | es_ok; then pass "$h: copia de seguridad al servidor" "copia ${snap:0:8}"; else fail "$h: copia de seguridad al servidor" "$(echo "$out" | corto 250)"; return; fi
    local cj; cj=$(copias "$h")
    if [ -n "$snap" ] && echo "$cj" | grep -q "\"${snap:0:8}\""; then pass "$h: el servidor ve la copia en el almacen" "$(echo "$cj" | jget n) copias de $h"
    else fail "$h: el servidor ve la copia en el almacen" "$(echo "$cj" | corto)"; fi

    # Explorar la copia desde el panel (se lee en el servidor: funciona con el equipo apagado)
    sid=$(system_id "$h")
    pcurl -o /dev/null "$PANEL/equipos/$sid?refrescar=1"
    local base=/home/vagrant/testfiles html=""
    for i in 1 2 3 4 5 6 7 8; do
        html=$(pcurl "$PANEL/equipos/$sid/explorar?ruta=$base")
        grep -q "critico" <<< "$html" && break
        sleep 5   # el panel guarda la lista de copias 30 s
    done
    if grep -q "critico" <<< "$html"; then pass "$h: explorar la copia desde el panel" "$base contiene critico/"
    else fail "$h: explorar la copia desde el panel" "no aparece critico/ en $base"; fi

    # Rotura 1: un archivo estropeado -> se restaura DESDE EL PANEL
    remote "$lan" "echo 'CONTENIDO ESTROPEADO POR LA PRUEBA' > $f" >/dev/null 2>&1
    if [ "$(remote "$lan" "cat $f")" = "CONTENIDO ESTROPEADO POR LA PRUEBA" ]; then pass "$h: archivo estropeado a proposito ($f)"
    else fail "$h: archivo estropeado a proposito ($f)" "no se pudo modificar por SSH"; fi
    local dest; dest=$(PT=600 panel_post "/equipos/$sid/restaurar" "ruta=$f" "copia=latest" "destino=original" "carpeta=$(dirname "$f")")
    local msg; msg=$(pcurl "${dest:-$PANEL/restaurar}" | grep -o 'class="flash [a-z]*"[^>]*>[^<]*' | head -1 | sed 's/.*>//')
    local now; now="$(remote "$lan" "cat $f")"
    if [ "$now" = "config original" ]; then pass "$h: archivo restaurado desde el panel" "contenido='$now'"
    else fail "$h: archivo restaurado desde el panel" "panel='$msg' contenido='$now'"; fi

    # Rotura 2: carpeta vaciada -> se restaura con una orden (lo que usa la respuesta a incidentes)
    remote "$lan" "rm -rf $d/*" >/dev/null 2>&1
    local cnt; cnt=$(remote "$lan" "ls -A $d | grep -v octopus_no_tocar | wc -l")   # (el señuelo oculto no cuenta)
    [ "$cnt" = "0" ] && pass "$h: carpeta $d vaciada" || fail "$h: carpeta $d vaciada" "quedan $cnt"
    out=$(pedir "$h" POST /webhook/restaurar-archivo "{\"archivo\":\"$d\"}" 600)
    cnt=$(remote "$lan" "ls -A $d | wc -l")
    if echo "$out" | es_ok && [ "${cnt:-0}" -gt 0 ]; then pass "$h: carpeta restaurada" "$cnt elementos"
    else fail "$h: carpeta restaurada" "respuesta=$(echo "$out" | corto 150) elementos=$cnt"; fi

    out=$(pedir "$h" GET /snapshots "" 120)
    if echo "$out" | es_ok; then pass "$h: el agente lista sus copias" "$(echo "$out" | jget count) copias"
    else fail "$h: el agente lista sus copias" "$(echo "$out" | corto)"; fi
}

# ================================================================== 4. INCIDENTE DECLARADO DESDE EL PANEL
estado_inc() { INC ver "$1"; }

prueba_incidente() {
    local h="$1" lan="${IPS[$1]}" sid inc
    local f=/home/vagrant/testfiles/critico/config.txt
    local nuevo=/home/vagrant/testfiles/critico/archivo_posterior_a_la_copia.txt
    sid=$(system_id "$h")
    # La respuesta restaura la ultima copia ANTERIOR (2 min de margen) al momento del incidente
    local edad; edad=$(copias "$h" | jget edad)
    log "$h: la ultima copia tiene ${edad}s; hace falta que tenga 150 s"
    if [ "${edad:--1}" -lt 0 ]; then fail "$h: hay copia sana antes del incidente" "sin copias"; return; fi
    [ "$edad" -lt 150 ] && sleep $((150 - edad))
    pass "$h: hay copia sana antes del incidente" "de hace $((edad < 150 ? 150 : edad)) s"

    # Cambios normales hechos DESPUES de la copia (no es un ataque): la restauracion debe deshacerlos
    remote "$lan" "echo 'cambio posterior a la copia' > $f; echo 'archivo nuevo' > $nuevo; chown vagrant:vagrant $f $nuevo" >/dev/null 2>&1
    local internet_antes=1
    remote "$lan" "timeout 8 curl -s -o /dev/null https://www.google.com" && internet_antes=0

    local dest; dest=$(panel_post "/equipos/$sid/incidente" "motivo=Prueba automatica: incidente declarado desde el panel")
    inc=$(echo "$dest" | grep -o '/incidentes/[0-9]*' | grep -o '[0-9]*$')
    if [ -n "$inc" ]; then pass "$h: incidente declarado desde el panel" "#$inc"
    else fail "$h: incidente declarado desde el panel" "redireccion='$dest'"; return; fi

    local j est=""
    for i in $(seq 1 200); do   # hasta 10 minutos
        sleep 3
        j=$(estado_inc "$inc"); est=$(echo "$j" | jget estado)
        [ $((i % 10)) = 0 ] && log "  esperando la respuesta automatica: incidente #$inc estado=$est"
        [ "$est" != respondiendo ] && [ "$est" != nuevo ] && [ "$est" != pendiente ] && break
    done
    if [ "$est" = contenido ]; then pass "$h: respuesta completa" "aislar + copia forense + restaurar + avisar"
    else fail "$h: respuesta completa" "estado=$est; pasos: $(echo "$j" | python3 -c 'import json,sys
d=json.load(sys.stdin); print(" | ".join(("OK " if p.get("ok") else "MAL ")+p.get("texto","")+(" ("+p.get("detalle","")+")" if not p.get("ok") and p.get("detalle") else "") for p in d.get("pasos",[])))' 2>/dev/null | cut -c1-300)"; fi
    [ -n "$(echo "$j" | jget snapshot_forense)" ] && pass "$h: copia forense guardada en cuarentena" "$(echo "$j" | jget snapshot_forense | cut -c1-8)" \
        || fail "$h: copia forense guardada en cuarentena"
    [ "$(remote "$lan" "cat $f")" = "config original" ] && pass "$h: documentos devueltos a la copia sana" \
        || fail "$h: documentos devueltos a la copia sana" "config.txt='$(remote "$lan" "cat $f")'"
    [ "$(remote "$lan" "test -e $nuevo && echo si || echo no")" = no ] && pass "$h: lo creado despues de la copia se ha quitado" \
        || fail "$h: lo creado despues de la copia se ha quitado" "$nuevo sigue ahi"
    remote "$lan" "grep -q 'restaurado' /home/vagrant/AVISO_SEGURIDAD.txt" && pass "$h: aviso mostrado al usuario" "AVISO_SEGURIDAD.txt + mensaje al iniciar sesion" \
        || fail "$h: aviso mostrado al usuario"
    if [ $internet_antes = 0 ]; then
        if remote "$lan" "timeout 6 curl -s -o /dev/null https://www.google.com"; then fail "$h: equipo aislado de internet y de la red" "todavia sale a internet"
        else pass "$h: equipo aislado de internet y de la red" "solo habla con el servidor"; fi
    else
        # sin internet en el laboratorio: se comprueba que el cortafuegos del equipo tiene la regla de aislamiento
        if remote "$lan" "nft list table inet octopus >/dev/null 2>&1 || iptables -S OCTOPUS_OUT >/dev/null 2>&1"; then
            pass "$h: equipo aislado (cortafuegos activo)" "solo puede hablar con el servidor"
        else fail "$h: equipo aislado (cortafuegos activo)" "no hay regla de aislamiento en el equipo"; fi
    fi
    pedir "$h" GET /health "" 20 | es_ok && pass "$h: el servidor sigue llegando al equipo aislado" "por la cola de ordenes" \
        || fail "$h: el servidor sigue llegando al equipo aislado"
    local pag; pag=$(pcurl "$PANEL/incidentes/$inc")
    grep -q "Prueba automatica" <<< "$pag" && pass "$h: el incidente se ve en el panel" "/incidentes/$inc" \
        || fail "$h: el incidente se ve en el panel"

    local sala; sala=$(INC preparar "$inc")
    [ "$(echo "$sala" | jget ok)" = True ] && pass "$h: sala de analisis preparada" "$(echo "$sala" | jget msg)" \
        || fail "$h: sala de analisis preparada" "$(echo "$sala" | jget msg)"
    docker image inspect octopus-sandbox:1 >/dev/null 2>&1 && pass "cerebro: imagen del sandbox (sin red) disponible" \
        || warn "cerebro: imagen del sandbox no disponible" "la sala usa analisis basico"

    if [ "${DEJAR_INCIDENTE:-0}" = 1 ]; then
        warn "$h: incidente #$inc abierto para revisarlo" "liberalo desde el panel cuando quieras"
        return
    fi
    PT=200 panel_post "/incidentes/$inc/accion" "accion=liberar" "notas=cerrado por las pruebas automaticas" >/dev/null
    j=$(estado_inc "$inc")
    [ "$(echo "$j" | jget estado)" = cerrado ] && [ "$(echo "$j" | jget aislado)" = 0 ] \
        && pass "$h: equipo liberado desde el panel" "incidente #$inc cerrado" \
        || fail "$h: equipo liberado desde el panel" "estado=$(echo "$j" | jget estado) aislado=$(echo "$j" | jget aislado)"
    if [ $internet_antes = 0 ]; then
        remote "$lan" "timeout 8 curl -s -o /dev/null https://www.google.com" && pass "$h: vuelve a tener red normal" \
            || fail "$h: vuelve a tener red normal" "sigue sin internet tras liberar"
    fi
    remote "$lan" "grep -q 'AVISO DE SEGURIDAD' /etc/motd" && warn "$h: el aviso sigue en el mensaje de inicio" "deberia quitarse al liberar" \
        || pass "$h: aviso de inicio de sesion retirado al liberar"
}

# ================================================================== 5. MANTENIMIENTO
prueba_mantenimiento() {
    log "Mantenimiento: limpieza, verificacion, copia del servidor y vigilancia"
    timeout 1800 docker exec -w /app "$C" python lib/mantenimiento.py todo > "$TMP/mant.log" 2>&1
    local est; est=$(dx cat /app/data/mantenimiento.json 2>/dev/null)
    if [ -z "$est" ]; then fail "mantenimiento: se ejecuta" "$(tail -3 "$TMP/mant.log" | corto)"; return; fi
    pass "mantenimiento: se ejecuta" "estado guardado para el panel (Ajustes)"
    local t
    for t in retencion verificar autocopia vigilar probar; do
        local r; r=$(echo "$est" | python3 -c 'import json,sys; r=json.load(sys.stdin)["resultados"].get(sys.argv[1],{}); print(("1" if r.get("ok") else "0")+"|"+str(r.get("detalle",""))[:200])' "$t")
        local nombre; case $t in retencion) nombre="limpieza de copias antiguas";; verificar) nombre="comprobacion del almacen";;
                                 autocopia) nombre="copia del propio servidor";; vigilar) nombre="vigilancia (equipos sin copia, disco)";;
                                 probar) nombre="prueba de recuperacion semanal";; esac
        if [ "${r%%|*}" = 1 ]; then pass "mantenimiento: $nombre" "${r#*|}"
        elif [ $t = vigilar ]; then warn "mantenimiento: $nombre" "${r#*|}"
        else fail "mantenimiento: $nombre" "${r#*|}"; fi
    done
    local n; n=$(docker exec -w /app "$C" sh -c 'set -a; . /app/.env; set +a; restic -r /boveda/octopus-backups snapshots --no-lock --json --host octopus-servidor' 2>/dev/null \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin) or []))' 2>/dev/null)
    [ "${n:-0}" -gt 0 ] && pass "mantenimiento: la copia del servidor esta en el almacen" "$n copias de octopus-servidor" \
        || fail "mantenimiento: la copia del servidor esta en el almacen"
    local pag; pag=$(pcurl "$PANEL/ajustes")
    grep -q "ltima vez" <<< "$pag" && pass "mantenimiento: el panel muestra el resultado" "Ajustes -> Mantenimiento del servidor" \
        || fail "mantenimiento: el panel muestra el resultado" "Ajustes no muestra la ultima ejecucion"
}

# ================================================================== 6. KIT DE RECUPERACION
prueba_kit() {
    local clave; clave="$(envv RESTIC_PASSWORD)"
    local cod; cod=$(PT=30 pcurl -o "$TMP/kit_mal.txt" -w '%{http_code}' --data-urlencode "csrf_token=$(csrf_pagina)" \
        --data-urlencode "password=incorrecta" "$PANEL/ajustes/kit-recuperacion")
    if [ "$cod" = 302 ] && ! grep -q "$clave" "$TMP/kit_mal.txt"; then pass "kit: con contrasena incorrecta no se entrega"
    else fail "kit: con contrasena incorrecta no se entrega" "codigo=$cod"; fi
    cod=$(PT=30 pcurl -D "$TMP/kit_cab.txt" -o "$TMP/kit.txt" -w '%{http_code}' --data-urlencode "csrf_token=$(csrf_pagina)" \
        --data-urlencode "password=$TPASS" --data-urlencode "codigo_2fa=$(codigo_2fa)" "$PANEL/ajustes/kit-recuperacion")
    if [ "$cod" = 200 ] && grep -qi "attachment" "$TMP/kit_cab.txt" && grep -q "KIT DE RECUPERACION" "$TMP/kit.txt"; then
        pass "kit: se descarga desde el panel (pide la contrasena)" "$(wc -l < "$TMP/kit.txt") lineas"
    else fail "kit: se descarga desde el panel (pide la contrasena)" "codigo=$cod"; return; fi
    local kclave; kclave=$(grep -m1 "^Clave de las copias" "$TMP/kit.txt" | sed 's/.*\.\.\.\.\. *//' | tr -d '\r ')
    [ -n "$kclave" ] && [ "$kclave" = "$clave" ] && pass "kit: contiene la clave de las copias" || fail "kit: contiene la clave de las copias"
    # La prueba de verdad: con SOLO la clave del kit se pueden leer las copias directamente del disco
    local n; n=$(docker exec -e RESTIC_PASSWORD="$kclave" "$C" restic -r /boveda/octopus-backups snapshots --no-lock --json 2>/dev/null \
        | python3 -c 'import json,sys; print(len(json.load(sys.stdin) or []))' 2>/dev/null)
    [ "${n:-0}" -gt 0 ] && pass "kit: con la clave del kit se leen las copias sin el panel" "$n copias en el almacen" \
        || fail "kit: con la clave del kit se leen las copias sin el panel"
    rm -f "$TMP/kit.txt" "$TMP/kit_mal.txt"
}

# ================================================================== COPIA COMPLETA EN UN EQUIPO REAL
# prueba_completa <equipo> [archivo_de_sistema]: copia de TODO el disco (en Windows con instantanea VSS),
# comprueba que dentro esta un archivo del sistema y lo recupera (debe quedar al lado, sin tocar el original)
prueba_completa() {
    local h="$1" sid fich="${2:-}" n=0 snap=""
    [ -n "$fich" ] || { [ "$h" = win2022 ] && fich='C:\Windows\System32\drivers\etc\hosts' || fich=/etc/hostname; }
    sid=$(system_id "$h"); [ -n "$sid" ] || { fail "copia completa: equipo $h en el panel"; return; }
    panel_post "/equipos/$sid/copia-completa" "activa=on" "accion=guardar" >/dev/null
    sleep 20
    local t0; t0=$(date +%s)
    panel_post "/equipos/$sid/copia-completa" "accion=ahora" >/dev/null
    for _ in $(seq 1 540); do   # hasta 90 min (la primera copia de un disco entero tarda)
        sleep 10
        snap=$(pyc 'import agentes
d, e = agentes.copias_por_equipo(force=True)
l = [c for c in d.get(sys.argv[1].lower(), []) if "completa" in c["tags"] and c["time"] and c["time"].timestamp() >= float(sys.argv[2]) - 5]
print(l[0]["id"] if l else "")' "$h" "$t0" 2>/dev/null)
        [ -n "$snap" ] && break
    done
    if [ -z "$snap" ]; then fail "copia completa de $h" "no termino en 90 min"; return; fi
    pass "copia completa de $h (todo el disco)" "copia $snap en $(( ($(date +%s) - t0) / 60 )) min"
    local dir; dir=$(python3 -c 'import sys,ntpath,posixpath; p=sys.argv[1]; print(ntpath.dirname(p) if "\\" in p else posixpath.dirname(p))' "$fich")
    local base; base=$(python3 -c 'import sys,ntpath,posixpath; p=sys.argv[1]; print(ntpath.basename(p) if "\\" in p else posixpath.basename(p))' "$fich")
    local ls; ls=$(pedir "$h" GET "/ls?snapshot=$snap&path=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1]))' "$dir")" "" 300)
    grep -q "\"name\": \"$base\"" <<< "$ls" && pass "copia completa: incluye archivos del sistema" "$fich" \
        || fail "copia completa: incluye archivos del sistema" "$fich: $(corto <<< "$ls")"
    local rs; rs=$(pedir "$h" POST /webhook/restaurar-archivo "$(python3 -c 'import json,sys;print(json.dumps({"archivo":sys.argv[1],"snapshot":sys.argv[2],"destino":"original"}))' "$fich" "$snap")" 900)
    if es_ok <<< "$rs" && grep -q "restaurado-" <<< "$rs"; then
        pass "copia completa: lo del sistema se recupera al lado, sin tocar el original" "$(python3 -c 'import json,sys;print(json.load(sys.stdin).get("file",""))' <<< "$rs")"
    else
        fail "copia completa: recuperar un archivo del sistema" "$(corto <<< "$rs")"
    fi
    panel_post "/equipos/$sid/copia-completa" "accion=guardar" >/dev/null   # se vuelve a desactivar
}

# ================================================================== 7. NOVEDADES v2.1
# prueba de recuperacion, copias sospechosas, kit cifrado, informe mensual y limite de velocidad
prueba_novedades() {
    local h="$1" sid; sid=$(system_id "$h")
    [ -n "$sid" ] || { fail "novedades: equipo $h en el panel"; return; }
    # 1. Prueba de recuperacion pedida desde el panel (recupera de verdad unos archivos en el servidor)
    panel_post "/equipos/$sid/probar-recuperacion" >/dev/null
    local r=""
    for _ in $(seq 1 30); do
        sleep 2
        r=$(dx cat /app/data/pruebas_recuperacion.json 2>/dev/null | python3 -c 'import json,sys
from datetime import datetime
d=json.load(sys.stdin).get(sys.argv[1].lower()) or {}
reciente = d and (datetime.now().astimezone()-datetime.fromisoformat(d["fecha"])).total_seconds() < 300
print(("1" if d.get("ok") else "0")+"|"+d.get("detalle","") if reciente else "")' "$h" 2>/dev/null)
        [ -n "$r" ] && break
    done
    if [ "${r%%|*}" = 1 ]; then pass "recuperacion: prueba desde el panel ($h)" "${r#*|}"
    else fail "recuperacion: prueba desde el panel ($h)" "${r#*|}"; fi
    grep -q "Prueba de recuperación" <<< "$(pcurl "$PANEL/equipos/$sid")" && pass "recuperacion: la ficha del equipo muestra el resultado" \
        || fail "recuperacion: la ficha del equipo muestra el resultado"
    # 2. Copias sospechosas: un ataque (simulado en la base de datos) marca las copias hechas despues
    local inc; inc=$(pyc 'import sqlite3
from datetime import datetime, timezone, timedelta
c = sqlite3.connect(DB, timeout=30)
cur = c.execute("INSERT INTO incidents (system_id, hostname, detectado, origen, severidad, motivo, estado) VALUES (?,?,?,?,?,?,?)",
    (int(sys.argv[1]), sys.argv[2], (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "pruebas", "critica",
     "PRUEBA copias sospechosas", "nuevo"))
c.commit(); print(cur.lastrowid)' "$sid" "$h")
    if pedir "$h" POST /webhook/backup "{}" 600 | es_ok; then
        local pag; pag=$(pcurl "$PANEL/equipos/$sid?refrescar=1")
        grep -q ">Sospechosa<" <<< "$pag" && grep -q "Hay copias hechas durante un ataque" <<< "$pag" \
            && pass "copias sospechosas: se marcan en el panel" "la copia hecha durante el ataque sale como Sospechosa" \
            || fail "copias sospechosas: se marcan en el panel"
        local exp; exp=$(pcurl "$PANEL/equipos/$sid/explorar")
        grep -o '<option value="[a-z0-9]*" selected>[^<]*' <<< "$exp" | grep -qv SOSPECHOSA \
            && pass "copias sospechosas: al recuperar se propone la ultima copia limpia" \
            || fail "copias sospechosas: al recuperar se propone la ultima copia limpia"
    else
        fail "copias sospechosas: copia de prueba" "no se pudo hacer la copia"
    fi
    pyc 'import sqlite3
c = sqlite3.connect(DB, timeout=30); c.execute("DELETE FROM incidents WHERE id = ?", (int(sys.argv[1]),)); c.commit()' "${inc:-0}" >/dev/null 2>&1
    # 3. Kit cifrado (zip AES-256 con 7-Zip)
    local cod; cod=$(PT=30 pcurl -D "$TMP/kitz_cab.txt" -o "$TMP/kit.zip" -w '%{http_code}' --data-urlencode "csrf_token=$(csrf_pagina)" \
        --data-urlencode "password=$TPASS" --data-urlencode "codigo_2fa=$(codigo_2fa)" --data-urlencode "clave_zip=ClaveKitPruebas1" "$PANEL/ajustes/kit-recuperacion")
    if [ "$cod" = 200 ] && grep -qi "application/zip" "$TMP/kitz_cab.txt"; then
        docker cp "$TMP/kit.zip" "$C:/tmp/kit_prueba.zip" >/dev/null 2>&1
        if dx 7z t -pClaveKitPruebas1 /tmp/kit_prueba.zip >/dev/null 2>&1 && ! dx 7z t -pmala /tmp/kit_prueba.zip >/dev/null 2>&1; then
            pass "kit cifrado: zip AES-256, solo se abre con su contrasena" "$(wc -c < "$TMP/kit.zip") bytes"
        else fail "kit cifrado: zip AES-256, solo se abre con su contrasena"; fi
        dx rm -f /tmp/kit_prueba.zip
    else fail "kit cifrado: se descarga" "codigo=$cod"; fi
    rm -f "$TMP/kit.zip" "$TMP/kitz_cab.txt"
    # 4. Informe mensual
    local inf; inf=$(pcurl "$PANEL/informe")
    grep -q "Informe de copias de seguridad" <<< "$inf" && grep -q "$h" <<< "$inf" \
        && pass "informe mensual: pagina para imprimir" "incluye a $h" || fail "informe mensual: pagina para imprimir"
    local txt; txt=$(dx python lib/informe.py 2>&1)
    grep -q "Copias hechas" <<< "$txt" && pass "informe mensual: version texto (la del correo)" || fail "informe mensual: version texto" "$(corto <<< "$txt")"
    # 5. Limite de velocidad: se guarda en el panel y el agente lo recibe en su siguiente consulta
    panel_post "/ajustes/copias" "limite_kbps=1024" "informe=on" >/dev/null
    local v; v=$(pyc 'import sqlite3
c = sqlite3.connect(DB, timeout=30); print(c.execute("SELECT value FROM config WHERE key = ?", ("copias_limite_kbps",)).fetchone()[0])')
    [ "$v" = 1024 ] && pass "velocidad: el limite se guarda desde Ajustes" "1024 KB/s" || fail "velocidad: el limite se guarda desde Ajustes" "valor=$v"
    panel_post "/ajustes/copias" "limite_kbps=0" "solo_horario=on" "informe=on" >/dev/null
    # 6. Copia completa del equipo (opcional): se activa, se hace desde el panel y sale marcada como "Completa"
    panel_post "/equipos/$sid/copia-completa" "activa=on" "accion=guardar" >/dev/null
    sleep 15   # el agente recoge el ajuste en su siguiente consulta
    panel_post "/equipos/$sid/copia-completa" "accion=ahora" >/dev/null
    local completa=""
    for _ in $(seq 1 120); do
        sleep 10
        completa=$(pyc 'import agentes
d, e = agentes.copias_por_equipo(force=True)
print(sum(1 for c in d.get(sys.argv[1].lower(), []) if "completa" in c["tags"]))' "$h" 2>/dev/null)
        [ "${completa:-0}" -gt 0 ] && break
    done
    if [ "${completa:-0}" -gt 0 ]; then
        grep -q ">Completa<" <<< "$(pcurl "$PANEL/equipos/$sid?refrescar=1")" \
            && pass "copia completa: se hace desde el panel y sale marcada" "todo el disco de $h" \
            || fail "copia completa: sale marcada en la ficha"
    else
        fail "copia completa: se hace desde el panel" "no aparece ninguna copia completa de $h en 20 min"
    fi
    panel_post "/equipos/$sid/copia-completa" "accion=guardar" >/dev/null   # se vuelve a desactivar
}

# ================================================================== v2.2: avisos, banderines, señuelos, asistente...
prueba_v22() {
    local h="$1" sid ip; sid=$(system_id "$h"); ip="${IPS[$h]}"
    [ -n "$sid" ] || { fail "v2.2: equipo $h en el panel"; return; }
    # 1. Avisos con codigo y explicacion
    local pag; pag=$(pcurl "$PANEL/avisos")
    grep -q 'class="codigo"' <<< "$pag" && grep -q "Por qué importa" <<< "$pag" && pass "avisos: con código, por qué importa y pasos" \
        || { grep -q "No hay nada que revisar" <<< "$pag" && pass "avisos: página correcta (no hay nada que revisar)" || fail "avisos: con código y pasos"; }
    # 2. Boton Solucionar: vuelve a copiar el equipo
    local antes; antes=$(copias "$h" | jget n)
    panel_post "/avisos/solucionar" "codigo=OCT-EQ-03" "system_id=$sid" "volver=/avisos" >/dev/null
    local despues="$antes"
    for _ in $(seq 1 45); do sleep 4; despues=$(copias "$h" | jget n); [ "${despues:-0}" -gt "${antes:-0}" ] && break; done
    [ "${despues:-0}" -gt "${antes:-0}" ] && pass "avisos: el botón Solucionar hace la copia ($h)" "$antes -> $despues copias" \
        || fail "avisos: el botón Solucionar hace la copia ($h)" "$antes -> $despues copias"
    # 3. Banderines: ultimos pasos en la ficha (incluidos los que manda el agente)
    sleep 3; pag=$(pcurl "$PANEL/equipos/$sid")
    grep -q "Últimos pasos" <<< "$pag" && grep -q "(en el equipo)" <<< "$pag" && pass "banderines: últimos pasos en la ficha del equipo" \
        || fail "banderines: últimos pasos en la ficha del equipo"
    # 4. Asistente de recuperacion: busca por nombre (sin respetar mayusculas)
    pag=$(PT=300 pcurl -G "$PANEL/recuperar/asistente" --data-urlencode "equipo=$sid" --data-urlencode "q=CONFIG")
    grep -qi "config.txt" <<< "$pag" && pass "asistente: encuentra config.txt buscando «CONFIG»" || fail "asistente: busca por nombre" "$(grep -o 'No hemos encontrado[^<]*' <<< "$pag" | head -1)"
    # 5. Diagnostico para soporte: sin nombres de equipo ni secretos
    pcurl -o "$TMP/diag.zip" "$PANEL/ajustes/diagnostico"
    if python3 -c 'import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); n=z.namelist(); d=b"".join(z.read(x) for x in n)
assert "diagnostico.json" in n, n
assert sys.argv[2].encode() not in d and b"RESTIC_PASSWORD" not in d, "contiene datos sensibles"' "$TMP/diag.zip" "$h" 2>"$TMP/diag.err"; then
        pass "diagnóstico: se descarga sin nombres de equipo ni contraseñas"
    else fail "diagnóstico: se descarga sin nombres de equipo ni contraseñas" "$(tail -1 "$TMP/diag.err")"; fi
    # 6. Registro de actividad firmado
    grep -q "Registro íntegro" <<< "$(pcurl "$PANEL/audit")" && pass "registro de actividad: firmado e íntegro" \
        || fail "registro de actividad: firmado e íntegro"
    # 7. Semaforo 3-2-1 en el inicio
    grep -q "Regla 3-2-1" <<< "$(pcurl "$PANEL/inicio")" && pass "inicio: semáforo 3-2-1" || fail "inicio: semáforo 3-2-1"
    # 7b. Buscar equipos en la red desde el panel (radar): encuentra este equipo y sabe que ya esta protegido
    local loc; loc=$(PT=30 pcurl -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf_token=$(csrf_pagina)" \
        --data-urlencode "red=${ip%.*}.0/24" "$PANEL/equipos/buscar")
    pag=""
    for _ in $(seq 1 40); do sleep 3; pag=$(pcurl "$loc"); grep -q "He encontrado" <<< "$pag" && break; done
    if grep -q ">$ip<" <<< "$pag" && grep -q "Ya protegido" <<< "$pag"; then
        pass "buscar equipos: encuentra $h ($ip) y lo marca como ya protegido" "$(grep -o 'He encontrado [0-9]* equipo' <<< "$pag")"
    else fail "buscar equipos: encuentra $h en la red" "$(grep -o 'He encontrado [0-9]* equipo[s]*' <<< "$pag" | head -1)"; fi
    # 7c. Se arregla solo lo que no tiene riesgo; lo que borra copias espera permiso
    if [ "$(pyc 'import sqlite3; print(sqlite3.connect(DB).execute("SELECT COUNT(*) FROM incidents WHERE estado != ?", ("cerrado",)).fetchone()[0])')" != 0 ]; then
        limpiar >/dev/null
    fi
    pyc 'import sys; sys.path.insert(0, "lib"); import mantenimiento as m
m.guardar_estado({"autocopia": {"ok": False, "detalle": "fallo provocado por la bateria"},
                  "retencion": {"ok": False, "detalle": "fallo provocado por la bateria"}})' >/dev/null
    pag=$(pcurl "$PANEL/avisos")
    grep -q "OCT-ALM-03" <<< "$pag" && grep -q "Necesita tu permiso" <<< "$pag" && pass "autoarreglo: borrar copias antiguas pide permiso" \
        || fail "autoarreglo: borrar copias antiguas pide permiso"
    log "  esperando a que OCTOPUS arregle solo la copia del servidor (como mucho 12 min)..."
    for _ in $(seq 1 72); do sleep 10; pag=$(pcurl "$PANEL/avisos"); grep -q "OCT-SRV-01" <<< "$pag" || break; done
    grep -q "OCT-SRV-01" <<< "$pag" && fail "autoarreglo: la copia del servidor fallida se repite sola" "sigue el aviso tras 12 min" \
        || pass "autoarreglo: la copia del servidor fallida se repite sola"
    grep -q "OCT-ALM-03" <<< "$pag" && pass "autoarreglo: la limpieza (borra copias) NO se hace sola" \
        || fail "autoarreglo: la limpieza (borra copias) NO se hace sola"
    panel_post "/avisos/solucionar" "codigo=OCT-ALM-03" "volver=/avisos" "confirmado=1" >/dev/null
    for _ in $(seq 1 30); do sleep 6; grep -q "OCT-ALM-03" <<< "$(pcurl "$PANEL/avisos")" || break; done
    grep -q "OCT-ALM-03" <<< "$(pcurl "$PANEL/avisos")" && fail "autoarreglo: con permiso, la limpieza se hace" \
        || pass "autoarreglo: con permiso, la limpieza se hace"
    # 8. Archivo señuelo: el agente lo crea y, si se toca, es un ataque
    local base; base=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])[0])' "${RUTAS[$h]:-[\"/home/vagrant/testfiles\"]}")
    if remote "$ip" "test -f '$base/.octopus_no_tocar.docx'" >/dev/null 2>&1; then
        pass "señuelos: el agente ha puesto el archivo señuelo ($h)" "$base"
        local n0; n0=$(pyc 'import sqlite3; print(sqlite3.connect(DB).execute("SELECT COUNT(*) FROM incidents WHERE motivo LIKE ?", ("%señuelo%",)).fetchone()[0])')
        remote "$ip" "echo cifrado >> '$base/.octopus_no_tocar.docx'" >/dev/null 2>&1
        local n1="$n0"
        for _ in $(seq 1 30); do sleep 4; n1=$(pyc 'import sqlite3; print(sqlite3.connect(DB).execute("SELECT COUNT(*) FROM incidents WHERE motivo LIKE ?", ("%señuelo%",)).fetchone()[0])'); [ "$n1" -gt "$n0" ] && break; done
        [ "$n1" -gt "$n0" ] && pass "señuelos: tocar el señuelo abre un incidente al momento ($h)" || fail "señuelos: tocar el señuelo abre un incidente" "sin incidente en 2 min"
        sleep 20; limpiar >/dev/null
    else
        fail "señuelos: el agente ha puesto el archivo señuelo ($h)" "no existe $base/.octopus_no_tocar.docx"
    fi
}

# ================================================================== demo manual (NO forma parte de las pruebas automaticas)
lanzar_ataque() { # simula un ransomware INOFENSIVO: archivos con datos aleatorios y una nota de rescate
    local lan="$1" d=/home/vagrant/testfiles/critico
    log "Lanzando ataque simulado en $lan"
    remote "$lan" "for i in 1 2 3 4 5; do head -c 4000 /dev/urandom > $d/documento\$i.docx.locked; done; echo 'Your files have been encrypted. Pay 1 bitcoin.' > $d/README_DECRYPT.txt; echo 'ARCHIVO CIFRADO' > $d/config.txt" >/dev/null 2>&1
}

# Instalador del panel para un equipo (la misma funcion que el boton "Descargar instalador"):
# lo da de alta con sus carpetas, le crea su clave propia y deja el zip en /vagrant_host/.runtime/
instalador() { # instalador <equipo> <linux|windows|macos>
    local h="$1" so="$2" ip="${IPS[$1]:-}" rutas="${RUTAS[$1]:-}"
    [ -n "$rutas" ] || { echo "No se que carpetas proteger en $h"; return 1; }
    mkdir -p /vagrant_host/.runtime
    CLI alta "$h" "$so" "$ip" "$rutas" >/dev/null || { echo "No se pudo dar de alta $h"; return 1; }
    pyc 'import alta_equipos, ordenes
ordenes.init(DB)
h, so, rutas = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
sys.stdout.buffer.write(alta_equipos.paquete(h, so, rutas, ordenes.nuevo_token(h)))' "$h" "$so" "$rutas" > "/vagrant_host/.runtime/octopus-$h.zip" \
        || { echo "No se pudo generar el instalador de $h"; return 1; }
    echo "Instalador listo: .runtime/octopus-$h.zip ($(stat -c %s "/vagrant_host/.runtime/octopus-$h.zip") bytes)"
}

limpiar() { local lim; lim=$(INC limpiar-laboratorio); log "  limpieza: $lim"; echo "$lim"; }

docker inspect "$C" >/dev/null 2>&1 || { fail "cerebro: contenedor octopus existe" "no esta instalado (vagrant provision cerebro)"; exit 1; }

case "${1:-todo}" in
    todo)
        shift || true
        : > "$PROG" 2>/dev/null; log "Inicio de la bateria v2: $*"
        limpiar >/dev/null   # incidentes de ejecuciones anteriores (equipos aislados): se liberan antes de empezar
        pruebas_cerebro
        panel_login || { fail "panel: sesion de pruebas" "sin sesion no se pueden hacer las pruebas del panel"; exit 1; }
        LINUX=()
        for h in "$@"; do [ "$h" != win2022 ] && [ -n "${IPS[$h]:-}" ] && LINUX+=("$h"); done
        for h in "${LINUX[@]}"; do
            [ "$h" = cliente1 ] && { prueba_instalacion_remota cliente1; prueba_instalador_linux cliente1; }
        done
        for h in "${LINUX[@]}"; do prueba_cliente_linux "$h"; done
        [ ${#LINUX[@]} -gt 0 ] && prueba_incidente "${LINUX[0]}"
        prueba_mantenimiento
        prueba_kit
        [ ${#LINUX[@]} -gt 0 ] && prueba_novedades "${LINUX[0]}"
        [ ${#LINUX[@]} -gt 0 ] && prueba_v22 "${LINUX[0]}"
        log "Fin de la bateria" ;;
    v22)       crear_usuario_pruebas >/dev/null && panel_login && prueba_v22 "${2:-cliente1}" ;;
    cerebro)   pruebas_cerebro ;;
    novedades) crear_usuario_pruebas >/dev/null && panel_login && prueba_novedades "${2:-cliente1}" ;;
    completa)  crear_usuario_pruebas >/dev/null && panel_login && prueba_completa "${2:-win2022}" "${3:-}" ;;
    limpiar)   limpiar ;;
    instalador) instalador "$2" "${3:-linux}" ;;
    conectado) for i in $(seq 1 "${3:-60}"); do CLI conectado "$2" && { echo "$2 conectado"; exit 0; }; sleep 2; done; echo "$2 NO conectado"; exit 1 ;;
    simular)   # demo en directo: lanza el ataque simulado y deja que OCTOPUS responda solo
        lanzar_ataque "${IPS[$2]}"; echo "Ataque simulado lanzado en $2. Mira el panel: Incidentes." ;;
    health)    pedir "$(equipo_de "$2")" GET /health "" 20 ;;
    backup)    pedir "$(equipo_de "$2")" POST /webhook/backup "{}" 900 ;;
    restaurar) pedir "$(equipo_de "$2")" POST /webhook/restaurar-archivo "$(python3 -c 'import json,sys;print(json.dumps({"archivo":sys.argv[1]}))' "$3")" 600 ;;
    *) echo "uso: $0 todo <equipos...>|cerebro|limpiar|instalador <equipo> <so>|conectado <equipo>|simular <equipo>|health <equipo>|backup <equipo>|restaurar <equipo> <ruta>"; exit 1 ;;
esac
