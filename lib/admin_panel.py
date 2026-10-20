#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Panel web de administración (el cerebro: todo lo que se ve y se hace desde el navegador).

Es una aplicación Flask. Cada página web y cada acción del panel es una función con @app.route(...) aquí dentro.
Este es el archivo más grande; está dividido en secciones que empiezan por un comentario con «====».

QUÉ TOCAR PARA CAMBIAR CADA COSA (mapa rápido):
  - Una página o un botón del panel ....... busca su @app.route('/loquesea') en este archivo.
  - El aspecto (colores, tipos, cabecera) .. templates/base.html (lo comparten todas las páginas).
  - El texto de una pantalla ............... su archivo en templates/ (p. ej. equipo.html, monitorizacion.html).
  - Encender/apagar o ajustar funciones .... lib/funciones.py (la lista) + la página /ajustes/funciones de aquí.
  - Entrar, contraseñas, sesión ............ función login() y _iniciar_sesion()/_abrir_sesion() más abajo.
  - Doble autenticación (2FA) .............. lib/dosfa.py (la lógica) + rutas /login/codigo y /cuenta/2fa de aquí.
  - Usuarios de la empresa (LDAP/OIDC...) .. lib/identidad.py + login_empresa()/login_oidc() de aquí.
  - Bloqueo de atacantes, aprobaciones ..... lib/seguridad.py + _seg_fallo() y las rutas /aprobaciones de aquí.
  - Monitorización de equipos .............. lib/monitor.py + rutas /monitorizacion* de aquí.
  - Avisos (qué pasa y qué hacer) .......... lib/avisos.py (el catálogo con código y pasos).
  - Lo que hacen los equipos (copias...) ... lib/ordenes.py (cola) y las rutas /api/agente/* de aquí.
  - Textos legales de la web ............... lib/legal.py + los .md de legal/ + ruta /legal de aquí.

REGLAS IMPORTANTES AL AÑADIR UNA RUTA:
  - Si NO lleva @login_required, añádela a PUBLIC_ENDPOINTS (si no, pedirá entrar).
  - Si cambia datos, el formulario tiene que enviar csrf_token (ver cualquier plantilla) o será rechazado.
"""

import os
import sys
import json
import threading
import re
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from markupsafe import escape as html_escape
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort, Response
from functools import wraps
import subprocess
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Dependencias de seguridad: si faltan, el panel sigue funcionando (con aviso)
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ImportError:  # pragma: no cover
    Limiter = None
try:
    from flask_talisman import Talisman
except ImportError:  # pragma: no cover
    Talisman = None
try:
    import bcrypt
except ImportError:  # pragma: no cover
    bcrypt = None
from config_manager import ConfigManager
from notifications import NotificationManager
from wazuh_integration import WazuhIntegration
from telegram_integration import TelegramIntegration
import agentes
import avisos as _av
import banderines as _ban
import autoarreglo as _aa
import registro as _registro
import monitor as _mon
from datetime import timezone
from pathlib import Path

app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates'))

def _load_dotenv():
    """Carga variables de entorno desde .env en el project root (no requiere python-dotenv)."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and (k not in os.environ or os.environ.get("_OVERWRITE_ENV_", "") == "1"):
                    os.environ[k] = v
    except Exception:
        pass
_load_dotenv()

# SECRET KEY desde variable de entorno o generar
app.secret_key = os.environ.get('FLASK_SECRET_KEY',
                                os.environ.get('ADMIN_SECRET_KEY', secrets.token_hex(32)))

# Directorios
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "install", "config.json")
DB_FILE = os.environ.get('DB_PATH', os.path.join(BASE_DIR, "data", "admin_panel.db"))
if not os.path.isabs(DB_FILE):
    DB_FILE = os.path.join(BASE_DIR, DB_FILE)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Asegurar directorio de templates
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

# SEGURIDAD: Rate limiting para prevenir ataques de fuerza bruta
if Limiter is not None:
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["2000 per day", "300 per hour"],
        # Solo para quien NO ha entrado: un administrador con la monitorizacion en directo pide datos cada
        # pocos segundos (mas de 300 por hora) y en una oficina todos salen por la misma IP.
        default_limits_exempt_when=lambda: 'user_id' in session or request.path.startswith('/static/'),
        storage_uri="memory://"
    )
else:
    print("[AVISO] flask-limiter no instalado: rate limiting desactivado")

    class _NoLimiter:
        def limit(self, *a, **k):
            return lambda f: f

        def exempt(self, f):
            return f

        def request_filter(self, f):
            return f
    limiter = _NoLimiter()

# SEGURIDAD: HTTPS enforcement (en producción, solo si hay certificado/proxy TLS)
if os.environ.get('FLASK_ENV') == 'production' and os.environ.get('FORCE_HTTPS', '0') == '1' and Talisman:
    Talisman(app, force_https=True)

# ============================================================
# CAPAS DE SEGURIDAD DEL PANEL
#  1. HTTPS (certificado propio generado por el instalador)
#  2. Cookies de sesion HttpOnly + SameSite=Strict (+ Secure con HTTPS)
#  3. Caducidad de sesion por inactividad
#  4. Token CSRF en todos los formularios y peticiones POST
#  5. Cabeceras de seguridad (CSP, anti-clickjacking, no-sniff...)
#  6. Bloqueo de cuenta tras varios intentos fallidos + limite por IP
#  7. Cambio obligatorio de la contrasena inicial y politica de contrasenas
#  8. Permisos por rol y registro de auditoria de todas las acciones
# ============================================================
TLS_CERT = os.environ.get('PANEL_TLS_CERT', os.path.join(BASE_DIR, 'data', 'tls', 'panel.crt'))
TLS_KEY = os.environ.get('PANEL_TLS_KEY', os.path.join(BASE_DIR, 'data', 'tls', 'panel.key'))
USE_HTTPS = (os.environ.get('PANEL_HTTPS', '1') == '1' and os.path.isfile(TLS_CERT) and os.path.isfile(TLS_KEY))
SESSION_IDLE_MINUTES = int(os.environ.get('SESSION_IDLE_MINUTES', '30'))
MAX_FAILED_LOGINS = int(os.environ.get('MAX_FAILED_LOGINS', '5'))
LOCKOUT_MINUTES = int(os.environ.get('LOCKOUT_MINUTES', '15'))
MIN_PASSWORD_LEN = 12

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Strict',
    SESSION_COOKIE_SECURE=USE_HTTPS,
    SESSION_COOKIE_NAME='octopus_session',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


app.jinja_env.globals['csrf_token'] = csrf_token

PUBLIC_ENDPOINTS = {'login', 'static', 'recover_password', 'reset_password', 'index', 'healthz'}


# ------------------------------------------------------------------ capas de seguridad (Ajustes -> Funciones)
import seguridad as _seg

_SIN_FILTRO_RED = ('/api/agente/', '/healthz')   # los equipos siempre pueden hablar con el servidor


def _seg_confianza():
    import funciones as _f
    return _f.opcion('bloqueo_atacantes', 'confianza') if _f.activa('bloqueo_atacantes') else ''


@limiter.request_filter
def _limite_no_aplica():
    """El limite de peticiones no se aplica al propio servidor ni a las direcciones de confianza."""
    return _seg.nunca_bloquear(request.remote_addr or '', _seg_confianza())


def _seg_fallo(motivo):
    """Un intento sospechoso desde esta dirección (contraseña mal, página que no existe...)."""
    import funciones as _f
    if not _f.activa('bloqueo_atacantes'):
        return
    ip = request.remote_addr or ''
    minutos = int(_f.opcion('bloqueo_atacantes', 'minutos'))
    if _seg.fallo(DB_FILE, ip, motivo, int(_f.opcion('bloqueo_atacantes', 'intentos')), minutos, _seg_confianza()):
        log_audit(None, 'IP_BLOQUEADA', f'{ip} bloqueada {minutos} min ({motivo})', ip)
        _ban.marcar('seguridad', f'Dirección {ip} bloqueada {minutos} min: {motivo}', nivel='aviso')
        _notificar_incidente('acceso', f'OCTOPUS ha bloqueado la dirección {ip} durante {minutos} minutos: {motivo}.\n'
                                       f'Si eras tú, espera o desbloquéala en Ajustes → Funciones (modo experto). '
                                       f'Desde la consola del servidor: octopus.sh acceso-emergencia')


@app.before_request
def _seguridad_entrada():
    import funciones as _f
    ip = request.remote_addr or ''
    if request.path.startswith(_SIN_FILTRO_RED):
        return None
    if _f.activa('panel_solo_redes') and not _seg.nunca_bloquear(ip, _f.opcion('panel_solo_redes', 'redes')):
        return ('Este panel solo se puede abrir desde la red de la oficina (o por VPN).\n'
                'Si es tu red y te has quedado fuera, en la consola del servidor: octopus.sh acceso-emergencia\n',
                403, {'Content-Type': 'text/plain; charset=utf-8'})
    if _f.activa('bloqueo_atacantes'):
        mins = _seg.bloqueada(DB_FILE, ip, _seg_confianza())
        if mins:
            return (f'Demasiados intentos fallidos desde tu dirección ({ip}). Vuelve a intentarlo en {mins} minutos.\n',
                    429, {'Content-Type': 'text/plain; charset=utf-8', 'Retry-After': str(mins * 60)})
    return None


@app.errorhandler(404)
def _no_existe(e):
    if not request.path.startswith(_SIN_FILTRO_RED + ('/static/', '/favicon')):
        _seg_fallo(f'página que no existe: {request.path[:80]}')
    return ('No existe esa página.', 404, {'Content-Type': 'text/plain; charset=utf-8'})


@app.errorhandler(429)
def _demasiados(e):
    return ('Demasiados intentos seguidos desde esta dirección. Espera un minuto y vuelve a intentarlo.', 429,
            {'Content-Type': 'text/plain; charset=utf-8', 'Retry-After': '60'})


def _aviso_acceso(user):
    """Tras entrar bien: ¿desde un navegador nuevo? Devuelve la cookie a poner (o None)."""
    import funciones as _f
    _seg.acierto(DB_FILE, request.remote_addr or '')
    cookie = request.cookies.get('octopus_disp', '')
    ua = request.headers.get('User-Agent', '')
    estado = _seg.acceso(DB_FILE, user['id'], cookie, request.remote_addr, ua)
    if estado == 'conocido':
        return None
    cookie = secrets.token_urlsafe(32)
    _seg.recordar(DB_FILE, user['id'], cookie, request.remote_addr, ua)
    if estado == 'nuevo' and _f.activa('aviso_acceso_nuevo'):
        nav = _seg.nombre_navegador(ua)
        log_audit(user['id'], 'ACCESO_NUEVO', f'{nav} desde {request.remote_addr}', request.remote_addr)
        _notificar_incidente('acceso', f'Nuevo acceso al panel de OCTOPUS: el usuario «{user["username"]}» ha entrado desde '
                                       f'{nav} ({request.remote_addr}) el {datetime.now():%d/%m/%Y a las %H:%M}.\n'
                                       f'Si has sido tú, no hagas nada. Si no, cambia la contraseña ya '
                                       f'(Ajustes → Tu cuenta) y revisa el registro de actividad.')
    return cookie


@app.before_request
def security_checks():
    # CSRF: todo POST debe traer el token de la sesion (campo oculto o cabecera)
    if request.method == 'POST' and not request.path.startswith('/api/agente/'):
        sent = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
        expected = session.get('_csrf', '')
        if not expected or not secrets.compare_digest(str(sent), str(expected)):
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({'error': 'Token CSRF invalido. Recarga la pagina.'}), 400
            flash('La pagina habia caducado. Vuelve a intentarlo.', 'error')
            return redirect(request.referrer or url_for('login'))
    # Caducidad por inactividad
    if 'user_id' in session:
        now = datetime.now().timestamp()
        last = session.get('_last_seen', now)
        if now - last > SESSION_IDLE_MINUTES * 60:
            session.clear()
            flash('Tu sesion ha caducado por inactividad. Vuelve a entrar.', 'info')
            return redirect(url_for('login'))
        # Las recargas automaticas de las paginas (?auto=1 o cabecera X-Auto) no cuentan como actividad:
        # si no, una pantalla abierta en Inicio mantendria la sesion abierta para siempre.
        if not (request.args.get('auto') == '1' or request.headers.get('X-Auto') == '1'):
            session['_last_seen'] = now
        session.permanent = True
        # el papel se lee en cada visita: si otro administrador lo cambia o borra el usuario, se aplica al momento
        with get_db_connection() as _c:
            _u = _c.execute('SELECT role, sesion_gen FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if not _u or (_u['sesion_gen'] or 0) != session.get('gen', 0):
            session.clear()
            return redirect(url_for('login'))
        session['role'] = _u['role']
        # Contrasena inicial: obligar a cambiarla antes de usar el panel
        if session.get('must_change') and request.endpoint not in ('cambiar_password', 'logout', 'static'):
            return redirect(url_for('cambiar_password'))
        if session.get('falta_2fa') and request.endpoint not in ('cuenta_2fa', 'ayuda_2fa', 'logout', 'static'):
            return redirect(url_for('cuenta_2fa'))


@app.after_request
def security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
    if USE_HTTPS:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    if 'user_id' in session:
        response.headers['Cache-Control'] = 'no-store'
    response.headers.pop('Server', None)
    return response


@app.route('/healthz')
def healthz():
    """Comprobacion para monitorizacion externa: base de datos y almacen de copias."""
    estado = {'panel': 'ok'}
    try:
        c = sqlite3.connect(DB_FILE, timeout=5)
        c.execute('SELECT 1')
        c.close()
        estado['base_de_datos'] = 'ok'
    except Exception:
        estado['base_de_datos'] = 'error'
    try:
        import urllib.request as _u, urllib.error as _ue
        try:
            _u.urlopen('http://127.0.0.1:8000/', timeout=3)
        except _ue.HTTPError:
            pass  # 401/404: responde, que es lo que importa
        estado['almacen'] = 'ok'
    except Exception:
        estado['almacen'] = 'error'
    ok = all(v == 'ok' for v in estado.values())
    estado['status'] = 'ok' if ok else 'degradado'
    return jsonify(estado), (200 if ok else 503)

# Instancia del gestor de configuración
config_manager = ConfigManager(DB_FILE)

# Instancia del gestor de notificaciones
notification_manager = NotificationManager(config_manager)


# Instancia de integración con Wazuh
wazuh_integration = WazuhIntegration(config_manager)

# Instancia de integración con Telegram
telegram_integration = TelegramIntegration(config_manager)

# Instancia del gestor de alertas

# Inicializar base de datos
def init_db():
    """Inicializa la base de datos del panel de administración"""
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Tabla de usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            recovery_token TEXT,
            recovery_token_expiry TIMESTAMP
        )
    ''')
    
    # Tabla de sistemas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            os_family TEXT NOT NULL,
            os_version TEXT,
            status TEXT DEFAULT 'unknown',
            last_backup TIMESTAMP,
            last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de configuración
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de logs de auditoría
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Migraciones (columnas nuevas en instalaciones existentes)
    for table, col, ddl in (
        ('users', 'must_change_password', 'INTEGER DEFAULT 0'),
        ('users', 'failed_logins', 'INTEGER DEFAULT 0'),
        ('users', 'locked_until', 'TIMESTAMP'),
        ('users', 'nivel', "TEXT DEFAULT 'basico'"),
        ('users', 'sesion_gen', 'INTEGER DEFAULT 0'),   # sube al cambiar la contraseña: cierra las demás sesiones
        ('users', 'origen', "TEXT DEFAULT 'local'"),     # local / ldap / radius / oidc
        ('systems', 'tunnel_ip', 'TEXT'),
        ('systems', 'notes', 'TEXT'),
        ('systems', 'agent_info', 'TEXT'),
        ('audit_logs', 'hash', 'TEXT'),
        ('audit_logs', 'hash_anterior', 'TEXT'),
    ):
        cols = [r[1] for r in cursor.execute(f'PRAGMA table_info({table})').fetchall()]
        if col not in cols:
            cursor.execute(f'ALTER TABLE {table} ADD COLUMN {col} {ddl}')
    import sugerencias as _sug_db
    _sug_db.crear_tabla(conn)

    # Índices para que las búsquedas no se hagan lentas al crecer: equipos por nombre, registro por tipo de acción
    # (el recuento de accesos nuevos, el informe...) y por fecha.
    cursor.execute('CREATE INDEX IF NOT EXISTS systems_hostname ON systems (hostname)')
    cursor.execute('CREATE INDEX IF NOT EXISTS audit_action ON audit_logs (action)')
    cursor.execute('CREATE INDEX IF NOT EXISTS audit_timestamp ON audit_logs (timestamp)')

    conn.commit()
    conn.close()

def get_db_connection():
    """Obtiene conexión a la base de datos"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def _hash_registro(anterior, rid, user_id, action, details, ts, ip):
    return _registro.huella(anterior, rid, user_id, action, details, ts, ip)


def log_audit(user_id, action, details="", ip_address=""):
    """Registra la acción en el registro de actividad, encadenada con la anterior (lib/registro.py)."""
    _registro.escribir(DB_FILE, user_id, action, details, ip_address)


def verificar_registro():
    """(correcto, explicación) tras recorrer la cadena del registro de actividad."""
    conn = get_db_connection()
    filas = conn.execute('SELECT id, user_id, action, details, timestamp, ip_address, hash, hash_anterior '
                         'FROM audit_logs ORDER BY id').fetchall()
    conn.close()
    previo, empezado, n = None, False, 0
    for f in filas:
        if not f['hash']:
            if empezado:
                return False, (f'La línea {f["id"]} ({f["action"]}) se añadió sin firma: alguien escribió directamente '
                               f'en la base de datos.')
            continue  # lineas de antes de esta version (sin firma)
        if empezado and (f['hash_anterior'] or '') != previo:
            return False, f'Se ha borrado o cambiado algo justo antes de la línea {f["id"]} ({f["action"]}).'
        if _hash_registro(f['hash_anterior'] or '', f['id'], f['user_id'], f['action'], f['details'],
                          f['timestamp'], f['ip_address']) != f['hash']:
            return False, f'La línea {f["id"]} ({f["action"]}) se ha modificado después de escribirse.'
        previo, empezado, n = f['hash'], True, n + 1
    return True, (f'{n} líneas comprobadas: ninguna se ha borrado ni cambiado.' if n else 'Aún no hay líneas firmadas.')

# Decoradores de autenticación
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            
            conn = get_db_connection()
            user = conn.execute('SELECT role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
            conn.close()
            
            if not user or user['role'] not in roles:
                flash('No tienes permisos para esta acción', 'error')
                return redirect(url_for('inicio'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Rutas de autenticación
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])  # fuerza bruta (ver la pagina o recargarla no cuenta)
def login():
    """Página de login"""
    if 'user_id' in session and request.method == 'GET':
        return redirect(url_for('inicio'))
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

        if user and user['locked_until']:
            try:
                locked = datetime.fromisoformat(str(user['locked_until']))
            except ValueError:
                locked = None
            if locked and locked > datetime.now():
                conn.close()
                mins = int((locked - datetime.now()).total_seconds() // 60) + 1
                log_audit(user['id'], 'LOGIN_BLOCKED', 'Intento con la cuenta bloqueada', request.remote_addr)
                flash(f'Demasiados intentos fallidos. Prueba de nuevo en {mins} minutos.', 'error')
                return render_template('login.html'), 429

        local = not user or (user['origen'] if 'origen' in user.keys() else 'local') in (None, '', 'local')
        if user and local and verify_password(password, user['password_hash']):
            conn.close()
            return _iniciar_sesion(user, 'contraseña de OCTOPUS')

        if not local or not user:
            # usuarios de la empresa (LDAP / RADIUS), si están encendidos; un usuario local nunca pasa por aquí
            import identidad as _id
            datos, proveedor, error_ext = _id.entrar_con_contrasena(username, password)
            if datos:
                uid, error_ext = _id.usuario_local(DB_FILE, datos, proveedor)
                if uid:
                    fila = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
                    conn.close()
                    return _iniciar_sesion(fila, {'ldap': 'Active Directory / LDAP', 'radius': 'RADIUS'}[proveedor])
            if error_ext and 'incorrect' not in error_ext:
                conn.close()
                _seg_fallo(f'acceso de empresa fallido ({username[:40]})')
                log_audit(user['id'] if user else None, 'LOGIN_FAILED', f'{username[:40]}: {error_ext}'[:200],
                          request.remote_addr)
                flash(error_ext, 'error')
                return render_template('login.html', oidc=_oidc_boton())

        if user:
            fails = (user['failed_logins'] or 0) + 1
            locked_until = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES) if fails >= MAX_FAILED_LOGINS else None
            conn.execute('UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?',
                         (0 if locked_until else fails, locked_until, user['id']))
            conn.commit()
            log_audit(user['id'], 'LOGIN_FAILED', f'Contrasena incorrecta ({fails})', request.remote_addr)
        conn.close()
        _seg_fallo('contraseña incorrecta' + ('' if user else f' (usuario «{username[:40]}» no existe)'))
        flash('Usuario o contrasena incorrectos.', 'error')

    return render_template('login.html', oidc=_oidc_boton())


def _oidc_boton():
    """Texto del botón «Entrar con...» si OIDC está encendido (None si no)."""
    try:
        return config_manager.get_config('oidc.nombre_boton') or 'Entrar con la cuenta de la empresa' \
            if _fun.activa('oidc') else None
    except Exception:
        return None


def _necesita_2fa(user):
    """¿Este usuario tiene que usar la doble autenticación? (los de OIDC no: la pone su proveedor)."""
    if (user['origen'] if 'origen' in user.keys() else 'local') == 'oidc' or not _fun.activa('dosfa'):
        return False
    quien = _fun.opcion('dosfa', 'quien')
    return quien == 'todos' or (quien == 'admins' and user['role'] in ('admin', 'supremo'))


def _iniciar_sesion(user, como):
    """Contraseña correcta: si tiene la 2FA activada, pide el código (salvo navegador recordado); si no, entra."""
    if (user['origen'] if 'origen' in user.keys() else 'local') != 'oidc' and _dosfa.activo(DB_FILE, user['id']) \
            and not _dosfa.recordado(DB_FILE, user['id'], request.cookies.get('octopus_2fa', '')):
        session.clear()
        session['pre2fa'] = {'uid': user['id'], 'como': como, 't': datetime.now().timestamp(), 'fallos': 0}
        return redirect(url_for('login_codigo'))
    return _abrir_sesion(user, como)


def _abrir_sesion(user, como):
    """Abre la sesión (local o de la empresa) y devuelve la respuesta."""
    with get_db_connection() as c:
        c.execute('UPDATE users SET last_login = ?, failed_logins = 0, locked_until = NULL WHERE id = ?',
                  (datetime.now(), user['id']))
    session.clear()  # evita fijacion de sesion
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    session['nivel'] = (user['nivel'] if 'nivel' in user.keys() else None) or 'basico'
    session['gen'] = (user['sesion_gen'] if 'sesion_gen' in user.keys() else 0) or 0
    session['must_change'] = bool(user['must_change_password'])
    session['falta_2fa'] = _necesita_2fa(user) and not _dosfa.activo(DB_FILE, user['id'])
    session['_last_seen'] = datetime.now().timestamp()
    session.permanent = True
    log_audit(user['id'], 'LOGIN', f'Inicio de sesion ({como})', request.remote_addr)
    cookie = _aviso_acceso(user)
    if session['must_change']:
        flash('Por seguridad, elige una contrasena nueva antes de continuar.', 'info')
        resp = redirect(url_for('cambiar_password'))
    else:
        resp = redirect(url_for('inicio'))
    if cookie:
        resp.set_cookie('octopus_disp', cookie, max_age=400 * 86400, httponly=True, secure=USE_HTTPS, samesite='Lax')
    return resp


import dosfa as _dosfa


@app.route('/login/codigo', methods=['GET', 'POST'])
def login_codigo():
    """Segundo paso al entrar: el código de 6 cifras de la app del móvil (o un código de emergencia)."""
    pre = session.get('pre2fa')
    if not pre or datetime.now().timestamp() - pre.get('t', 0) > 600:
        session.pop('pre2fa', None)
        flash('Han pasado más de 10 minutos: vuelve a escribir tu usuario y contraseña.', 'info')
        return redirect(url_for('login'))
    if request.method == 'POST':
        tipo = _dosfa.comprobar(DB_FILE, pre['uid'], request.form.get('codigo', ''))
        with get_db_connection() as c:
            user = c.execute('SELECT * FROM users WHERE id = ?', (pre['uid'],)).fetchone()
        if tipo and user:
            recordar = request.form.get('recordar') == 'on'
            resp = _abrir_sesion(user, pre.get('como', '') + ' + doble autenticación')
            if tipo == 'emergencia':
                quedan = _dosfa.quedan_emergencia(DB_FILE, user['id'])
                log_audit(user['id'], '2FA_EMERGENCIA', f'Código de emergencia usado (quedan {quedan})', request.remote_addr)
                flash(f'Has entrado con un código de emergencia. Te quedan {quedan}. Si has perdido el móvil, ve a '
                      f'«Tu cuenta → Doble autenticación» y vuelve a activarla con el móvil nuevo.', 'info')
            if recordar:
                resp.set_cookie('octopus_2fa', _dosfa.recordar(DB_FILE, user['id']), max_age=_dosfa.DIAS_RECORDAR * 86400,
                                httponly=True, secure=USE_HTTPS, samesite='Lax')
            return resp
        pre['fallos'] = pre.get('fallos', 0) + 1
        session['pre2fa'] = pre
        log_audit(pre['uid'], 'LOGIN_FAILED', f'Código de doble autenticación incorrecto ({pre["fallos"]})', request.remote_addr)
        _seg_fallo('código de doble autenticación incorrecto')
        if pre['fallos'] >= 5:
            session.pop('pre2fa', None)
            with get_db_connection() as c:
                c.execute('UPDATE users SET locked_until = ? WHERE id = ?',
                          (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES), pre['uid']))
            flash(f'Demasiados códigos incorrectos: la cuenta queda bloqueada {LOCKOUT_MINUTES} minutos.', 'error')
            return redirect(url_for('login'))
        flash('Ese código no vale. Mira que la hora del móvil esté bien y escribe el que sale ahora.', 'error')
    return render_template('login_codigo.html')


def _codigo_ok(uid, campo='codigo_2fa'):
    """Para lo delicado: si el usuario tiene la 2FA activada, el código es obligatorio (aunque el navegador esté recordado)."""
    if not _dosfa.activo(DB_FILE, uid):
        return True
    return bool(_dosfa.comprobar(DB_FILE, uid, request.form.get(campo, '')))


app.jinja_env.globals['dosfa_activo'] = lambda: 'user_id' in session and _dosfa.activo(DB_FILE, session['user_id'])


@app.route('/cuenta/2fa', methods=['GET', 'POST'])
@login_required
def cuenta_2fa():
    """Activar, ver y gestionar la doble autenticación del propio usuario."""
    uid = session['user_id']
    with get_db_connection() as c:
        user = c.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    obligatoria = _necesita_2fa(user)
    activa = _dosfa.activo(DB_FILE, uid)
    if request.method == 'POST':
        accion = request.form.get('accion', '')
        if accion == 'confirmar' and not activa:
            codigos = _dosfa.confirmar(DB_FILE, uid, request.form.get('codigo', ''))
            if not codigos:
                flash('Ese código no vale. Escribe el de 6 cifras que sale ahora en la app (cambia cada 30 segundos).', 'error')
                return redirect(url_for('cuenta_2fa'))
            session.pop('falta_2fa', None)
            _dosfa.olvidar_navegadores(DB_FILE, uid)
            log_audit(uid, '2FA_ACTIVADA', 'Doble autenticación activada', request.remote_addr)
            return render_template('cuenta_2fa.html', fase='codigos', codigos=codigos, nueva=True)
        if accion in ('nuevos', 'desactivar') and activa:
            if not _dosfa.comprobar(DB_FILE, uid, request.form.get('codigo', '')):
                flash('Para eso hace falta el código de la app (o uno de emergencia).', 'error')
                return redirect(url_for('cuenta_2fa'))
            if accion == 'nuevos':
                log_audit(uid, '2FA_CODIGOS', 'Códigos de emergencia nuevos', request.remote_addr)
                return render_template('cuenta_2fa.html', fase='codigos', codigos=_dosfa.nuevos_codigos(DB_FILE, uid),
                                       nueva=False)
            if obligatoria:
                flash('En este servidor la doble autenticación es obligatoria para tu usuario. Si has cambiado de móvil, '
                      'usa «Cambiar de móvil».', 'error')
                return redirect(url_for('cuenta_2fa'))
            _dosfa.quitar(DB_FILE, uid)
            with get_db_connection() as c:
                session['gen'] = c.execute('SELECT sesion_gen FROM users WHERE id = ?', (uid,)).fetchone()[0]
            log_audit(uid, '2FA_DESACTIVADA', 'Doble autenticación desactivada por el propio usuario', request.remote_addr)
            flash('Doble autenticación desactivada.', 'success')
            return redirect(url_for('cuenta_2fa'))
        if accion == 'cambiar_movil' and activa:
            if not _dosfa.comprobar(DB_FILE, uid, request.form.get('codigo', '')):
                flash('Para cambiar de móvil hace falta un código del móvil antiguo o uno de emergencia.', 'error')
                return redirect(url_for('cuenta_2fa'))
            _dosfa.preparar(DB_FILE, uid)     # deja de estar activa hasta que se confirme con el móvil nuevo
            session['falta_2fa'] = obligatoria
            log_audit(uid, '2FA_CAMBIO_MOVIL', 'Cambio de móvil de la doble autenticación', request.remote_addr)
            flash('Ahora escanea el código QR con el móvil nuevo.', 'info')
            return redirect(url_for('cuenta_2fa'))
        if accion == 'olvidar':
            _dosfa.olvidar_navegadores(DB_FILE, uid)
            log_audit(uid, '2FA_OLVIDAR', 'Olvidados los navegadores recordados', request.remote_addr)
            resp = redirect(url_for('cuenta_2fa'))
            resp.delete_cookie('octopus_2fa')
            flash('Hecho: todos los navegadores volverán a pedir el código.', 'success')
            return resp
        return redirect(url_for('cuenta_2fa'))
    if activa:
        return render_template('cuenta_2fa.html', fase='activa', obligatoria=obligatoria,
                               quedan=_dosfa.quedan_emergencia(DB_FILE, uid))
    secreto = _dosfa.secreto_pendiente(DB_FILE, uid) or _dosfa.preparar(DB_FILE, uid)
    import configuracion as _conf
    servidor = _conf.leer_env().get('OCTOPUS_PUBLIC_HOST') or _conf.leer_env().get('OCTOPUS_IP') or ''
    enlace = _dosfa.uri(user['username'], secreto, servidor)
    return render_template('cuenta_2fa.html', fase='activar', obligatoria=obligatoria, qr=_dosfa.qr_svg(enlace),
                           secreto=' '.join(secreto[i:i + 4] for i in range(0, len(secreto), 4)))


@app.route('/ayuda/doble-autenticacion')
def ayuda_2fa():
    """Guía sencilla, paso a paso (se puede abrir sin haber entrado y se puede imprimir)."""
    return render_template('ayuda_2fa.html')


# ------------------------------------------------------------------ legal y privacidad (público: también sin entrar)
import legal as _legal

URL_CODIGO_FUENTE = os.environ.get('OCTOPUS_CODIGO_FUENTE', 'https://github.com/josemurajo/OCTOPUS')
app.jinja_env.globals['autor_octopus'] = _legal.AUTOR      # atribución obligatoria (NOTICE, AGPL-3.0 sección 7.b)


def _legal_valores():
    """Lo que la nota para los trabajadores dice que se recoge, según cómo está configurado ahora."""
    datos = ['- Estado técnico del equipo: uso del procesador, memoria, discos, red, temperatura, ventiladores y batería.',
             '- Inventario del equipo: sistema operativo, modelo, discos y su salud, y si las protecciones del sistema '
             'están activas (antivirus, cortafuegos, cifrado del disco).',
             '- Las **copias de seguridad** de las carpetas de trabajo, cifradas antes de salir del equipo.']
    try:
        if _fun.opcion('monitorizacion', 'procesos') != 'no':
            datos.append('- Los **programas abiertos** y cuánto gastan (solo el nombre del programa, no lo que haces en él).')
        if _fun.opcion('monitorizacion', 'usuarios') == 'si':
            datos.append('- El **nombre de usuario** con la sesión iniciada en el equipo.')
        dias = _fun.opcion('monitorizacion', 'dias')
    except Exception:
        dias = 90
    return {'lista_datos': '\n'.join(datos), 'dias': dias}


@app.route('/legal')
def legal():
    """Licencia, componentes, privacidad y plantillas para la empresa."""
    docs = [(k, v[1], v[2]) for k, v in _legal.DOCUMENTOS.items()]
    return render_template('legal.html', docs=docs, doc=None, fuente=URL_CODIGO_FUENTE, autoria=_legal.autoria())


@app.route('/legal/<doc>')
def legal_doc(doc):
    t = _legal.texto(doc, _legal_valores() if doc == 'trabajadores' else None)
    if t is None:
        abort(404)
    if request.args.get('descargar'):
        nombre = os.path.basename(_legal.DOCUMENTOS[doc][0])
        return (t, 200, {'Content-Type': 'text/plain; charset=utf-8',
                         'Content-Disposition': f'attachment; filename="{nombre if "." in nombre else nombre + ".txt"}"'})
    cuerpo = ('<pre class="licencia">' + str(html_escape(t)) + '</pre>') if doc in ('licencia', 'autoria') else _legal.a_html(t)
    docs = [(k, v[1], v[2]) for k, v in _legal.DOCUMENTOS.items()]
    return render_template('legal.html', docs=docs, doc=doc, titulo=_legal.DOCUMENTOS[doc][1], cuerpo=cuerpo,
                           fuente=URL_CODIGO_FUENTE)


@app.route('/login/empresa')
def login_oidc():
    """Botón «Entrar con...»: manda al proveedor de la empresa (OIDC)."""
    import identidad as _id
    if not _fun.activa('oidc'):
        return redirect(url_for('login'))
    try:
        destino, datos = _id.oidc_inicio(url_for('login_oidc_vuelta', _external=True))
    except Exception as exc:
        flash(str(exc) if isinstance(exc, _id.ErrorIdentidad) else 'No se puede hablar con el proveedor de la empresa. '
              'Entra con el usuario local de OCTOPUS.', 'error')
        return redirect(url_for('login'))
    session['_oidc'] = datos
    return redirect(destino)


@app.route('/login/empresa/vuelta')
def login_oidc_vuelta():
    import identidad as _id
    if not _fun.activa('oidc'):
        return redirect(url_for('login'))
    guardado = session.pop('_oidc', None)
    try:
        datos = _id.oidc_vuelta(request.args, guardado)
        uid, error = _id.usuario_local(DB_FILE, datos, 'oidc')
        if not uid:
            raise _id.ErrorIdentidad(error)
    except Exception as exc:
        _seg_fallo('acceso de empresa (OIDC) fallido')
        log_audit(None, 'LOGIN_FAILED', f'OIDC: {exc}'[:200], request.remote_addr)
        flash(str(exc) if isinstance(exc, _id.ErrorIdentidad) else 'No se ha podido entrar con la cuenta de la empresa.',
              'error')
        return redirect(url_for('login'))
    with get_db_connection() as c:
        fila = c.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    return _iniciar_sesion(fila, 'cuenta de la empresa (OIDC)')

@app.route('/logout')
def logout():
    """Cerrar sesión"""
    if 'user_id' in session:
        log_audit(session['user_id'], 'LOGOUT', 'User logged out', request.remote_addr)
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('login'))

@app.route('/recover', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=["POST"])
def recover_password():
    """Recuperacion de contrasena por correo (mismo mensaje exista o no el correo: no revela usuarios)"""
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE lower(email) = ?', (email,)).fetchone()
        if user and (user['origen'] or 'local') != 'local':
            user = None   # los usuarios de la empresa cambian su contraseña en la empresa, no aquí
        if user:
            token = secrets.token_urlsafe(32)
            expiry = datetime.now() + timedelta(minutes=30)
            # Se guarda solo el hash del token: si alguien lee la BD no puede usarlo
            conn.execute('UPDATE users SET recovery_token = ?, recovery_token_expiry = ? WHERE id = ?',
                         (hashlib.sha256(token.encode()).hexdigest(), expiry, user['id']))
            conn.commit()
            enviado = send_recovery_email(user['email'], token)
            log_audit(user['id'], 'PASSWORD_RECOVERY_REQUEST',
                      'Correo enviado' if enviado else 'Correo NO enviado (SMTP sin configurar)', request.remote_addr)
        conn.close()
        flash('Si ese correo pertenece a un usuario, en unos minutos recibirás un enlace para crear una contraseña nueva '
              '(caduca en 30 minutos). Si no llega, pide ayuda al administrador.', 'info')
        return redirect(url_for('login'))
    return render_template('recover_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Restablecer contraseña con token"""
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE recovery_token = ? AND recovery_token_expiry > ?',
                       (hashlib.sha256(token.encode()).hexdigest(), datetime.now())).fetchone()
    
    if not user:
        conn.close()
        flash('El enlace no es válido o ha caducado. Pide uno nuevo.', 'error')
        return redirect(url_for('recover_password'))
    
    if request.method == 'POST':
        new_password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if new_password != confirm_password:
            flash('Las contraseñas no coinciden', 'error')
            return redirect(url_for('reset_password', token=token))
        
        if len(new_password) < MIN_PASSWORD_LEN:
            flash(f'La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres', 'error')
            return redirect(url_for('reset_password', token=token))
        
        # Actualizar contraseña
        password_hash = hash_password(new_password)
        conn.execute('UPDATE users SET password_hash = ?, recovery_token = NULL, recovery_token_expiry = NULL, failed_logins = 0, '
                     'locked_until = NULL, sesion_gen = COALESCE(sesion_gen, 0) + 1 WHERE id = ?',
                   (password_hash, user['id']))
        conn.commit()
        conn.close()
        
        log_audit(user['id'], 'PASSWORD_RESET', 'Password reset via recovery token', request.remote_addr)
        flash('Contraseña restablecida exitosamente', 'success')
        return redirect(url_for('login'))
    
    conn.close()
    return render_template('reset_password.html', token=token)

@app.route('/config/notifications', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def config_notifications():
    """Avisos por correo: servidor de correo (SMTP), a quién y qué avisos, y quién recibe cada tipo."""
    if request.method == 'POST':
        uid = session['user_id']
        seccion = request.form.get('seccion', 'alertas')
        if seccion == 'smtp':
            config_manager.set_config('smtp_enabled', _marcado('smtp_enabled'), uid)
            config_manager.set_config('smtp_server', (request.form.get('smtp_server') or 'smtp.gmail.com').strip(), uid)
            try:
                puerto = int(request.form.get('smtp_port') or 587)
            except ValueError:
                puerto = 587
            config_manager.set_config('smtp_port', puerto, uid)
            config_manager.set_config('smtp_username', (request.form.get('smtp_username') or '').strip(), uid)
            if request.form.get('smtp_password'):   # vacío = se deja la que había (no se enseña nunca)
                config_manager.set_config('smtp_password', request.form['smtp_password'], uid)
            config_manager.set_config('smtp_from', (request.form.get('smtp_from') or '').strip(), uid)
            config_manager.set_config('smtp_use_tls', _marcado('smtp_use_tls'), uid)
            log_audit(uid, 'CONFIG_NOTIFICATIONS_UPDATE', 'Servidor de correo (SMTP)', request.remote_addr)
        else:
            _guardar_protegido('email_notifications', _marcado('email_notifications'), uid)
            config_manager.set_config('alert_email', (request.form.get('alert_email') or '').strip(), uid)
            config_manager.set_config('notification_levels', request.form.getlist('notification_levels[]'), uid)
            por_tipo = {cat: (request.form.get(f'dest_{cat}') or '').strip()[:500]
                        for cat in NotificationManager.NOMBRES_CATEGORIAS}
            config_manager.set_config('avisos_destinatarios', json.dumps(por_tipo, ensure_ascii=False), uid)
            log_audit(uid, 'CONFIG_NOTIFICATIONS_UPDATE', 'Avisos por correo y destinatarios', request.remote_addr)
        flash('Guardado.', 'success')
        return redirect(url_for('config_notifications'))
    config = config_manager.get_config()
    por_tipo = config.get('avisos_destinatarios') or {}
    if isinstance(por_tipo, str):
        try:
            por_tipo = json.loads(por_tipo or '{}')
        except ValueError:
            por_tipo = {}
    return render_template('config_notifications.html', config=config, por_tipo=por_tipo,
                           categorias=NotificationManager.NOMBRES_CATEGORIAS,
                           hay_password=bool(config.get('smtp_password')))

@app.route('/test_notification')
@login_required
@role_required('admin', 'supremo')
def test_notification():
    """Envía una notificación de prueba"""
    success, message = notification_manager.send_alert(
        alert_type="test",
        details="Esta es una notificación de prueba desde OCTOPUS Zero-Touch"
    )
    
    if success:
        flash(f'Notificación de prueba enviada: {message}', 'success')
    else:
        flash(f'Error enviando notificación: {message}', 'error')
    
    return redirect(url_for('config_notifications'))

@app.route('/config/wazuh', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def config_wazuh():
    """Configuración de integración con Wazuh"""
    if request.method == 'POST':
        wazuh_enabled = request.form.get('wazuh_enabled') == 'true'
        wazuh_url = request.form.get('wazuh_url', '')
        wazuh_api_key = request.form.get('wazuh_api_key', '')
        wazuh_verify_ssl = request.form.get('wazuh_verify_ssl') == 'true'
        wazuh_alert_level_min = int(request.form.get('wazuh_alert_level_min', 7))
        
        config_manager.set_config('wazuh_enabled', wazuh_enabled, session['user_id'])
        config_manager.set_config('wazuh_url', wazuh_url, session['user_id'])
        config_manager.set_config('wazuh_api_key', wazuh_api_key, session['user_id'])
        config_manager.set_config('wazuh_verify_ssl', wazuh_verify_ssl, session['user_id'])
        config_manager.set_config('wazuh_alert_level_min', wazuh_alert_level_min, session['user_id'])
        
        log_audit(session['user_id'], 'CONFIG_WAZUH_UPDATE', 'Updated Wazuh integration configuration', request.remote_addr)
        flash('Configuración de Wazuh actualizada', 'success')
        
        return redirect(url_for('config_wazuh'))
    
    config = config_manager.get_config()
    
    return render_template('config_wazuh.html', config=config)

@app.route('/test_wazuh')
@login_required
@role_required('admin', 'supremo')
def test_wazuh():
    """Prueba la conexión con Wazuh"""
    result = wazuh_integration.test_connection()
    
    if result.get('success'):
        flash(f'Conexión exitosa: {result.get("message")}', 'success')
    else:
        flash(f'Error de conexión: {result.get("error")}', 'error')
    
    return redirect(url_for('config_wazuh'))

@app.route('/wazuh/alerts')
@login_required
@role_required('admin', 'supremo')
def wazuh_alerts():
    """Muestra alertas de Wazuh"""
    hours = request.args.get('hours', 24, type=int)
    result = wazuh_integration.get_alerts(hours=hours)
    
    if result.get('success'):
        alerts = result.get('alerts', [])
        return jsonify({'success': True, 'alerts': alerts, 'count': len(alerts)})
    else:
        return jsonify(result)

@app.route('/wazuh/critical')
@login_required
@role_required('admin', 'supremo')
def wazuh_critical():
    """Muestra alertas críticas de Wazuh"""
    hours = request.args.get('hours', 1, type=int)
    result = wazuh_integration.get_critical_alerts(hours=hours)
    
    return jsonify(result)

@app.route('/config/telegram', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def config_telegram():
    """Configuración de Telegram"""
    if request.method == 'POST':
        telegram_enabled = _marcado('telegram_enabled')
        telegram_bot_token = (request.form.get('telegram_bot_token') or '').strip() or config_manager.get_config('telegram_bot_token') or ''
        telegram_chat_id = request.form.get('telegram_chat_id', '')
        telegram_notification_levels = request.form.getlist('telegram_notification_levels[]')
        
        _guardar_protegido('telegram_enabled', telegram_enabled, session['user_id'])
        config_manager.set_config('telegram_bot_token', telegram_bot_token, session['user_id'])
        config_manager.set_config('telegram_chat_id', telegram_chat_id, session['user_id'])
        config_manager.set_config('telegram_notification_levels', telegram_notification_levels, session['user_id'])
        
        log_audit(session['user_id'], 'CONFIG_TELEGRAM_UPDATE', 'Updated Telegram configuration', request.remote_addr)
        flash('Configuración de Telegram actualizada', 'success')
        
        return redirect(url_for('config_telegram'))
    
    config = dict(config_manager.get_config())
    config['hay_token'] = bool(config.get('telegram_bot_token'))
    config['telegram_bot_token'] = ''   # el token no se vuelve a enseñar en la página
    return render_template('config_telegram.html', config=config)

@app.route('/test_telegram')
@login_required
@role_required('admin', 'supremo')
def test_telegram():
    """Prueba la conexión con Telegram"""
    result = telegram_integration.test_connection()
    
    if result.get('success'):
        flash(f'Mensaje de prueba enviado: {result.get("message_id")}', 'success')
    else:
        flash(f'Error enviando mensaje: {result.get("error")}', 'error')
    
    return redirect(url_for('config_telegram'))

@app.route('/telegram_bot_info')
@login_required
@role_required('admin', 'supremo')
def telegram_bot_info():
    """Obtiene información del bot de Telegram"""
    result = telegram_integration.get_bot_info()
    
    if result.get('success'):
        bot_info = result.get('bot_info', {})
        return jsonify({
            'success': True,
            'bot_name': bot_info.get('first_name'),
            'bot_username': bot_info.get('username'),
            'bot_id': bot_info.get('id')
        })
    else:
        return jsonify(result)

# ========================================
# RUTAS DE SISTEMAS
# ========================================

@app.route('/systems/<int:system_id>/delete', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def delete_system(system_id):
    """Eliminar sistema"""
    conn = get_db_connection()
    system = conn.execute('SELECT * FROM systems WHERE id = ?', (system_id,)).fetchone()
    if not system:
        conn.close()
        flash('Ese equipo ya no existe.', 'error')
        return redirect(url_for('equipos'))
    if _pedir_aprobacion('borrar_equipo', {'id': system_id, 'hostname': system['hostname']},
                         f'Quitar el equipo «{system["hostname"]}» del panel'):
        conn.close()
        return redirect(url_for('equipo', system_id=system_id))
    conn.execute('DELETE FROM systems WHERE id = ?', (system_id,))
    conn.commit()
    conn.close()
    
    log_audit(session['user_id'], 'SYSTEM_DELETE', f'Deleted system: {system["hostname"] if system else system_id}', request.remote_addr)
    flash('Equipo quitado del panel. Sus copias siguen guardadas.', 'success')
    
    return redirect(url_for('equipos'))

# ========================================
# RUTAS DE AUDITORÍA
# ========================================

@app.route('/audit')
@login_required
@role_required('admin', 'supremo', 'auditor')
def audit():
    """Página de logs de auditoría"""
    conn = get_db_connection()
    
    # Obtener logs recientes
    logs = conn.execute('''
        SELECT al.*, u.username 
        FROM audit_logs al
        LEFT JOIN users u ON al.user_id = u.id
        ORDER BY al.timestamp DESC
        LIMIT 100
    ''').fetchall()
    
    conn.close()
    integro, integridad = verificar_registro()
    return render_template('audit.html', logs=logs, integro=integro, integridad=integridad)

@app.route('/audit/clear')
@login_required
@role_required('supremo')
def clear_audit():
    """Limpiar logs antiguos (mantiene últimos 30 días)"""
    conn = get_db_connection()
    
    cutoff_date = datetime.now() - timedelta(days=30)
    conn.execute('''
        DELETE FROM audit_logs 
        WHERE timestamp < ?
    ''', (cutoff_date,))
    conn.commit()
    conn.close()
    
    log_audit(session['user_id'], 'AUDIT_CLEAR', f'Borradas las líneas de antes del {cutoff_date:%d/%m/%Y}', request.remote_addr)
    flash('Logs antiguos eliminados (mantenidos últimos 30 días)', 'success')
    
    return redirect(url_for('audit'))

@app.route('/')
def index():
    return redirect(url_for('inicio') if 'user_id' in session else url_for('login'))

@app.route('/deploy')
@login_required
@role_required('admin', 'supremo')
def deploy():
    """Red y servicios: estado de solo lectura. La configuracion de red se cambia con el instalador
    (no desde la web), para no reescribir el .env ni reiniciar el almacen de copias desde aqui."""
    return render_template('deploy.html', servicios=estado_red(), base_dir=BASE_DIR)


def estado_red():
    """Puertos en escucha de los servicios de OCTOPUS y estado del cortafuegos."""
    import subprocess as _sp
    servicios = [
        ("Panel web y ordenes de los agentes", "8080", "Toda la red (HTTPS)", "Los equipos se conectan aqui"),
        ("Almacen de copias", "8000", "Toda la red (HTTPS)", "Los equipos dejan aqui sus copias, cifradas"),
    ]
    escucha = ""
    try:
        escucha = _sp.run(["ss", "-tulnH"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        pass
    filas = []
    for nombre, puerto, esperado, nota in servicios:
        num = puerto.split("/")[0]
        direcciones = sorted({l.split()[4].rsplit(":", 1)[0] for l in escucha.splitlines()
                              if len(l.split()) > 4 and l.split()[4].endswith(":" + num)})
        filas.append({"nombre": nombre, "puerto": puerto, "esperado": esperado, "nota": nota,
                      "activo": bool(direcciones), "direcciones": ", ".join(direcciones) or "-"})
    try:
        import ordenes as _o
        conn = get_db_connection()
        nombres = [r['hostname'] for r in conn.execute('SELECT hostname FROM systems')]
        conn.close()
        fw = f"{sum(1 for n in nombres if _o.en_linea(n))} de {len(nombres)} equipos conectados ahora"
    except Exception:
        fw = "desconocido"
    return {"filas": filas, "cortafuegos": fw}


def puede_actuar():
    return session.get('role') in ('admin', 'supremo')


def puede_recuperar():
    """Recuperar archivos: administradores y el papel «Solo recuperar archivos»."""
    return session.get('role') in ('admin', 'supremo', 'recuperar')


app.jinja_env.globals['puede_recuperar'] = puede_recuperar

ROLES = [('admin', 'Administrador', 'Puede hacerlo todo.'),
         ('recuperar', 'Solo recuperar archivos', 'Ve los equipos y recupera archivos; no cambia nada más.'),
         ('lectura', 'Solo ver', 'Ve cómo va todo, sin tocar nada.')]
NOMBRE_ROL = {'supremo': 'Administrador principal', **{k: n for k, n, _ in ROLES}}
app.jinja_env.globals['NOMBRE_ROL'] = NOMBRE_ROL


def modo_experto():
    return session.get('nivel') == 'experto'


app.jinja_env.globals['modo_experto'] = modo_experto


def _hace(dt):
    """'hace 5 minutos', 'hace 2 horas', 'ayer', 'el 3 de octubre'..."""
    if not dt:
        return 'nunca'
    if isinstance(dt, str):
        dt = agentes.parse_time(dt)
        if not dt:
            return 'nunca'
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60:
        return 'hace un momento'
    if secs < 3600:
        m = int(secs // 60)
        return f'hace {m} minuto' + ('s' if m != 1 else '')
    if secs < 86400:
        h = int(secs // 3600)
        return f'hace {h} hora' + ('s' if h != 1 else '')
    if secs < 172800:
        return 'ayer'
    if secs < 30 * 86400:
        return f'hace {int(secs // 86400)} días'
    meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
             'septiembre', 'octubre', 'noviembre', 'diciembre']
    local = dt.astimezone()
    return f'el {local.day} de {meses[local.month - 1]} de {local.year}'


def _fecha(dt):
    if not dt:
        return '-'
    if isinstance(dt, str):
        dt = agentes.parse_time(dt)
    return dt.astimezone().strftime('%d/%m/%Y %H:%M') if dt else '-'


def _tamano(n):
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return ''
    for unidad in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f'{n:.0f} {unidad}' if unidad == 'B' else f'{n:.1f} {unidad}'
        n /= 1024
    return f'{n:.1f} PB'


app.jinja_env.filters['hace'] = _hace
app.jinja_env.filters['fecha'] = _fecha
app.jinja_env.filters['tamano'] = _tamano


def _fromjson(texto):
    try:
        v = json.loads(texto or '{}')
        return v if isinstance(v, dict) else {}
    except (ValueError, TypeError):
        return {}


app.jinja_env.filters['fromjson'] = _fromjson
app.jinja_env.globals['puede_actuar'] = puede_actuar


def _cliente_de(row):
    try:
        return (json.loads(row['notes'] or '{}') or {}).get('cliente', '') or ''
    except (ValueError, TypeError):
        return ''


def _clientes_lista():
    """Nombres de cliente que ya existen (para los desplegables)."""
    conn = get_db_connection()
    rows = conn.execute('SELECT notes FROM systems').fetchall()
    conn.close()
    nombres = set()
    for r in rows:
        try:
            c = (json.loads(r['notes'] or '{}') or {}).get('cliente', '')
        except (ValueError, TypeError):
            c = ''
        if c:
            nombres.add(c)
    return sorted(nombres, key=str.lower)


def _clientes_resumen():
    """Por cada cliente: nº de equipos, cuántos conectados, cuántos con problema de copia, avisos abiertos."""
    lista = _equipos_con_estado()
    clientes = {}
    for e in lista:
        nombre = _cliente_de(e['sys']) or 'Sin cliente'
        c = clientes.setdefault(nombre, {'nombre': nombre, 'equipos': 0, 'online': 0, 'problemas': 0})
        c['equipos'] += 1
        if e['est'].get('online'):
            c['online'] += 1
        if e['est'].get('nivel') in ('mal', 'error', 'atencion'):
            c['problemas'] += 1
    orden = sorted(clientes.values(), key=lambda c: (c['nombre'] == 'Sin cliente', c['nombre'].lower()))
    return orden


def _equipos_con_estado(force=False):
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM systems ORDER BY hostname').fetchall()
    conn.close()
    lista = []
    for r in rows:
        est = agentes.estado_equipo(r, force=force)
        lista.append({'sys': r, 'est': est, 'trabajos': agentes.trabajos_de(r['id'], 1)})
    return lista


SOLUCIONES_FILE = Path(BASE_DIR) / 'data' / 'soluciones.json'


def _leer_soluciones():
    try:
        return json.loads(SOLUCIONES_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _guardar_solucion(codigo, sid, estado, detalle):
    """Último intento de «Solucionar» de cada aviso (se enseña debajo del aviso)."""
    datos = _leer_soluciones()
    datos[f'{codigo}:{sid or ""}'] = {'estado': estado, 'detalle': str(detalle)[:400],
                                       'fecha': datetime.now().astimezone().isoformat(timespec='seconds')}
    try:
        SOLUCIONES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SOLUCIONES_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding='utf-8')
        tmp.replace(SOLUCIONES_FILE)
    except OSError:
        pass


def _aviso(codigo, equipo=None, sid=None, soluciones=None, **datos):
    """Aviso del catálogo, rellenado para este caso (qué pasa, por qué importa, pasos y botón Solucionar)."""
    a = _av.ficha(codigo, equipo=equipo, **datos)
    a.update(equipo=equipo, id=sid, detalle=str(datos.get('detalle') or ''))
    if a.get('enlace'):
        ruta, _, ancla = a['enlace'].partition('#')
        a['enlace'] = url_for(ruta) + ('#' + ancla if ancla else '')
    a['ultimo_intento'] = (soluciones or {}).get(f'{codigo}:{sid or ""}')
    # se arregla solo (sin riesgo) o necesita permiso (puede borrar datos)
    a['auto'] = _aa.es_automatica(a.get('accion')) and config_manager.get_config('autoarreglo') is not False
    a['riesgo'] = _aa.riesgo(a.get('accion'))
    a['rendido'] = a['auto'] and _aa.rendido(f'{codigo}:{sid or ""}')
    # para las pantallas que solo enseñan un texto corto
    a['que_hacer'] = ' '.join(a['pasos'][:2])
    return a


def _avisos(lista):
    """Avisos en lenguaje claro, con código, qué pasa, por qué importa, qué hacer y botón «Solucionar»."""
    import mantenimiento as _mant
    avisos = []
    pruebas = _mant.leer_pruebas()
    sol = _leer_soluciones()
    for e in lista:
        nombre = e['sys']['hostname']
        est = e['est']
        sid = e['sys']['id']
        if est['nivel'] == 'problema':
            avisos.append(_aviso('OCT-EQ-01', nombre, sid, sol))
        elif est['texto'] == 'Aún sin copias':
            avisos.append(_aviso('OCT-EQ-02', nombre, sid, sol))
        elif est['texto'] == 'Copia antigua':
            avisos.append(_aviso('OCT-EQ-03', nombre, sid, sol, detalle=_hace(est['ultima'])))
        for t in e['trabajos']:
            if t['estado'] == 'error' and t.get('tipo', 'copia') == 'copia':
                avisos.append(_aviso('OCT-EQ-04', nombre, sid, sol, detalle=str(t['mensaje'])[:300]))
        p = pruebas.get(nombre.lower())
        if p and not p.get('ok'):
            avisos.append(_aviso('OCT-EQ-05', nombre, sid, sol, detalle=p.get('detalle', '')))
        if est['copias'] and _inc.marcar_copias(sid, est['copias'][:1])[0]['sospechosa']:
            avisos.append(_aviso('OCT-EQ-06', nombre, sid, sol))
    try:   # monitorización (solo equipos con ella activada)
        for m in _mon.avisos():
            avisos.append(_aviso(m['codigo'], m['hostname'], m['system_id'], sol, detalle=m['detalle']))
    except Exception:
        pass
    # Avisos generales (no de un equipo concreto): id=None
    if lista:
        mant = _mant.leer_estado()
        for k, r in (mant.get('resultados') or {}).items():
            if r.get('ok'):
                continue
            codigo = r.get('codigo') or _av.codigo_mantenimiento(k, r)
            if codigo:
                avisos.append(_aviso(codigo, None, None, sol, detalle=str(r.get('detalle', ''))[:300]))
        atraso = _av.mantenimiento_atrasado(mant, Path(DB_FILE))
        if atraso:
            avisos.append(_aviso('OCT-SRV-02', None, None, sol, detalle=atraso))
        dias = _av.caducidad_certificado()
        if dias is not None and dias < 30:
            avisos.append(_aviso('OCT-CERT-01', None, None, sol, detalle=f'quedan {dias} días'))
        act = _av.leer_actualizacion()
        if act.get('hay_nueva') and not __import__('actualizar').la_hara_sola(
                act, config_manager.get_config('actualizar_solo') is not False):
            avisos.append(_aviso('OCT-ACT-01', None, None, sol, detalle=act.get('remota', '')))
        try:
            with get_db_connection() as c:
                kit_bajado = c.execute("SELECT 1 FROM audit_logs WHERE action = 'RECOVERY_KIT' LIMIT 1").fetchone()
        except sqlite3.Error:
            kit_bajado = True
        if not kit_bajado:
            avisos.append(_aviso('OCT-KIT-01', None, None, sol))
        try:
            import sugerencias as _sug
            if _sug.pendientes(Path(DB_FILE)) and _sug.hay_destino(_mant.leer_env()):
                avisos.append(_aviso('OCT-SUG-01', None, None, sol))
        except Exception:
            pass
    # lo grave primero
    avisos.sort(key=lambda a: 0 if a['nivel'] == 'problema' else 1)
    return avisos


def _ejecutar_arreglo(codigo, accion, row, uid, usuario, al_terminar=None):
    """Hace la solución de un aviso (la usan el botón «Solucionar» y el arreglo automático).
    Devuelve (mensaje, 'success'|'error'). al_terminar(ok, detalle) se llama cuando se sabe el resultado."""
    def _fin_ok(ok, detalle=''):
        if al_terminar:
            try:
                al_terminar(ok, str(detalle)[:400])
            except Exception:
                pass

    if accion in ('copia_equipo', 'prueba_equipo'):
        if not row:
            _fin_ok(False, 'el equipo ya no existe')
            return 'Ese equipo ya no existe.', 'error'
        prueba = accion == 'prueba_equipo'

        def _fin(s_id, ok, resp, _row=row):
            _copia_terminada(s_id, ok, resp)
            _guardar_solucion(codigo, s_id, 'ok' if ok else 'error',
                              ('Copia hecha' + ('; repitiendo la prueba de recuperación' if prueba else '')) if ok
                              else f'La copia volvió a fallar: {str(resp.get("message", ""))[:200]}')
            if ok and prueba:
                _lanzar_prueba(_row, uid)
            _fin_ok(ok, ('copia hecha' + ('; ahora se repite la prueba de recuperación' if prueba else '')) if ok
                    else f'la copia volvió a fallar: {str(resp.get("message", ""))[:200]}')
        agentes.lanzar_copia(row, on_done=_fin)
        _guardar_solucion(codigo, row['id'], 'en_curso', 'Copia en marcha...')
        return (f'Copia de {row["hostname"]} en marcha' + (' (después se repite la prueba)' if prueba else '') +
                '. Cuando termine bien, el aviso desaparecerá solo.'), 'success'

    if accion == 'reenviar_sugerencias':
        import sugerencias as _sug
        import mantenimiento as _m2
        r = _sug.reenviar_pendientes(_m2.leer_env(), Path(DB_FILE))
        _guardar_solucion(codigo, None, 'ok' if r.get('ok') else 'error', r['detalle'])
        _fin_ok(bool(r.get('ok')), r['detalle'])
        return r['detalle'], 'success' if r.get('ok') else 'error'

    fn = _av.ACCIONES_SERVIDOR.get(accion)
    if not fn:
        _fin_ok(False, 'acción desconocida')
        return 'Acción desconocida.', 'error'
    if accion in ('mantenimiento_ahora', 'comprobar_actualizacion', 'renovar_certificado'):
        try:
            r = fn()
        except Exception as exc:
            r = {'ok': False, 'detalle': f'Error inesperado: {exc}'}
        _guardar_solucion(codigo, None, 'ok' if r.get('ok') else ('en_curso' if r.get('en_marcha') else 'error'),
                          r['detalle'])
        _ban.marcar('avisos', f'Solucionar {accion} ({usuario}): {r["detalle"]}', codigo=codigo,
                    nivel='ok' if r.get('ok') else 'error')
        _fin_ok(bool(r.get('ok') or r.get('en_marcha')), r['detalle'])
        return r['detalle'], 'success' if r.get('ok') else 'error'

    _guardar_solucion(codigo, None, 'en_curso', 'Arreglando... (puede tardar unos minutos)')

    def _run():
        try:
            r = fn()
        except Exception as exc:
            r = {'ok': False, 'detalle': f'Error inesperado: {exc}'}
        _guardar_solucion(codigo, None, 'ok' if r.get('ok') else 'error', r.get('detalle', ''))
        _ban.marcar('avisos', f'Solucionar {accion} ({usuario}): {r.get("detalle", "")}', codigo=codigo,
                    nivel='ok' if r.get('ok') else 'error')
        if r.get('ok'):  # el aviso desaparece: se apunta en el estado del mantenimiento que ya está arreglado
            try:
                import mantenimiento as _m3
                est = _m3.leer_estado()
                tareas = {'desbloquear_almacen': ('verificar', 'retencion'), 'reparar_almacen': ('verificar',),
                          'limpiar_copias': ('retencion',), 'copia_servidor': ('autocopia',)}.get(accion, ())
                cambiado = False
                for t in tareas:
                    res_t = (est.get('resultados') or {}).get(t)
                    if res_t is None or res_t.get('ok'):
                        continue
                    # solo se da por arreglada la tarea que fallaba por ESTE aviso (quitar un bloqueo no arregla
                    # una limpieza que falló por otra cosa); limpiar copias sí cuenta como limpieza hecha
                    cod_t = res_t.get('codigo') or _av.codigo_mantenimiento(t, res_t)
                    if cod_t == codigo or (accion == 'limpiar_copias' and t == 'retencion'):
                        est['resultados'][t].update(ok=True, codigo=None,
                                                    detalle=f'Solucionado ({usuario}): {r.get("detalle", "")}'[:300])
                        cambiado = True
                if accion == 'limpiar_copias' and 'vigilar' in (est.get('resultados') or {}):
                    est['resultados']['vigilar']['disco_lleno'] = False
                    cambiado = True
                if cambiado:
                    _m3.guardar_estado(est['resultados'])
            except Exception:
                pass
        _fin_ok(bool(r.get('ok')), r.get('detalle', ''))
    threading.Thread(target=_run, daemon=True).start()
    return 'Arreglando... puede tardar unos minutos. El resultado aparecerá debajo del aviso.', 'success'


@app.route('/avisos/solucionar', methods=['POST'])
@login_required
def avisos_solucionar():
    """Botón «Solucionar» de un aviso. Lo que puede borrar datos pide confirmarlo antes."""
    codigo = request.form.get('codigo', '')
    sid = request.form.get('system_id', type=int)
    volver = request.form.get('volver', '')
    if not volver.startswith('/') or volver.startswith('//'):
        volver = url_for('avisos')
    if not puede_actuar():
        flash('Tu usuario no tiene permiso para hacer cambios.', 'error')
        return redirect(volver)
    accion = (_av.CATALOGO.get(codigo) or {}).get('accion')
    if not accion:
        flash('Este aviso no se puede arreglar solo: sigue los pasos que indica.', 'error')
        return redirect(volver)
    if _aa.riesgo(accion) and request.form.get('confirmado') != '1':
        flash('Esto puede borrar datos: marca la casilla «Entiendo lo que se va a hacer» para dar tu permiso.', 'error')
        return redirect(volver)
    row = _get_system(sid) if sid else None
    equipo = row['hostname'] if row else None
    usuario = session.get('username', '?')
    log_audit(session['user_id'], 'AVISO_SOLUCIONAR', f'{codigo} ({accion}) {equipo or ""}'
              f'{" - con permiso para el riesgo" if _aa.riesgo(accion) else ""}'.strip(), request.remote_addr)
    _ban.marcar('avisos', f'{usuario} pulsa Solucionar: {accion}', equipo=equipo, codigo=codigo)
    clave = f'{codigo}:{sid or ""}'
    _aa.olvidar(clave)   # a mano: OCTOPUS recupera sus intentos automáticos para la próxima vez
    msg, cat = _ejecutar_arreglo(codigo, accion, row, session['user_id'], usuario)
    flash(msg, cat)
    return redirect(volver)


# ---------------------------------------------------------------- vigilante de avisos
# Mira los avisos cada 10 minutos y, además, AL MOMENTO cuando algo falla (una copia, una prueba, el mantenimiento).
# Por cada problema nuevo manda un mensaje (correo y Telegram) con qué ha pasado y cómo se arregla; lo que no tiene
# riesgo lo arregla solo y después avisa de qué ha hecho y cómo ha ido. Lo que puede borrar datos espera al botón.
_autoarreglo_hilo = {'iniciado': False}
_autoarreglo_lock = threading.Lock()
_vigilante_ya = threading.Event()
_ciclo_lock = threading.Lock()


def _despertar_vigilante():
    """Algo acaba de fallar: que el vigilante mire los avisos ya, sin esperar a los 10 minutos."""
    _vigilante_ya.set()


def _direccion_panel():
    try:
        import mantenimiento as _m
        env = _m.leer_env()
        host = env.get('OCTOPUS_PUBLIC_HOST') or env.get('OCTOPUS_IP') or ''
        return f"https://{host}:{env.get('ADMIN_PORT', '8080')}" if host else ''
    except Exception:
        return ''


def _mandar_mensajes(mensajes):
    """mensajes: lista de (tipo, texto). Si hay muchos a la vez, van juntos en uno solo."""
    if not mensajes:
        return
    if len(mensajes) > 3:
        tipo = 'backup_failed' if all(m[0] == 'backup_failed' for m in mensajes) else 'mantenimiento'
        mensajes = [(tipo, f'OCTOPUS: {len(mensajes)} avisos a la vez\n\n' + '\n\n'.join(m[1] for m in mensajes))]
    registro = Path(BASE_DIR) / 'data' / 'logs' / 'avisos_enviados.log'
    for tipo, texto in mensajes:
        _notificar_incidente(tipo, texto)
        _ban.marcar('vigilante', 'Mensaje enviado: ' + texto.splitlines()[0][:150])
        try:   # copia de lo enviado (lo ve el soporte en el diagnóstico); se queda en ~200 KB
            registro.parent.mkdir(parents=True, exist_ok=True)
            if registro.exists() and registro.stat().st_size > 200_000:
                registro.replace(registro.with_suffix('.log.1'))
            with open(registro, 'a', encoding='utf-8') as fh:
                fh.write(f'===== {datetime.now():%d/%m/%Y %H:%M:%S} ({tipo})\n{texto}\n\n')
        except OSError:
            pass


def _autoarreglo_ciclo():
    """Una vuelta del vigilante. Devuelve las claves de lo que ha empezado a arreglar solo."""
    with _ciclo_lock:
        return _autoarreglo_ciclo_sin_lock()


def _autoarreglo_ciclo_sin_lock():
    try:
        _mon.revisar_silencio()      # equipos monitorizados que dejaron de mandar datos (aviso OCT-MON-08)
    except Exception:
        pass
    activado = config_manager.get_config('autoarreglo') is not False
    with app.test_request_context():
        lista = _equipos_con_estado()
        avisos = _avisos(lista)
    _aa.limpiar_viejos({f'{a["codigo"]}:{a["id"] or ""}' for a in avisos})
    if _aa.primera_vez():   # recién instalado o actualizado: lo que ya había no se reenvía (ya se avisó antes)
        for a in avisos:
            _aa.apuntar_avisado(f'{a["codigo"]}:{a["id"] or ""}', silencioso=True)
        _ban.marcar('vigilante', f'Vigilante en marcha ({len(avisos)} avisos que ya había, no se reenvían)')
    try:
        incidente = bool(_inc.abiertos())
    except Exception:
        incidente = False
    conectados = {e['sys']['id']: e['est'].get('online') for e in lista}
    copias_en_marcha = any(j.get('estado') == 'en_curso' for j in agentes.trabajos_de(None, 50))
    panel = _direccion_panel()
    mensajes, lanzados = [], []
    for a in avisos:
        accion = a.get('accion')
        clave = f'{a["codigo"]}:{a["id"] or ""}'
        # qué se va a hacer con este aviso
        plan, motivo = 'manual', ''
        if a.get('riesgo'):
            plan = 'permiso'
        elif accion and _aa.es_automatica(accion) and activado:
            if _aa.rendido(clave):
                plan = 'rendido'
            elif incidente:
                plan, motivo = 'luego', 'hay un incidente abierto (posible ataque) y mientras tanto no se toca nada solo'
            elif _aa.politica(accion).get('equipo_conectado') and not conectados.get(a['id']):
                plan, motivo = 'luego', 'el equipo no está conectado'
            elif accion == 'desbloquear_almacen' and copias_en_marcha:
                plan, motivo = 'luego', 'hay copias en marcha y el almacén se comprueba cuando terminen'
            else:
                si, motivo = _aa.toca(clave, accion)
                plan = 'arreglando' if si else 'luego'
        if _aa.hay_que_avisar(clave, a['codigo']):
            mensajes.append((_aa.tipo_alerta(a['codigo']), _aa.mensaje_nuevo(a, plan, motivo, panel)))
            _aa.apuntar_avisado(clave)
        if plan != 'arreglando':
            continue
        row = _get_system(a['id']) if a['id'] else None
        _aa.empezar(clave)
        _ban.marcar('autoarreglo', f'Arreglando solo: {a["titulo"]} ({accion})', equipo=a.get('equipo'),
                    codigo=a['codigo'])
        log_audit(None, 'AUTOARREGLO', f'{a["codigo"]} ({accion}) {a.get("equipo") or ""}'.strip(), 'servidor')

        def _al_terminar(ok, detalle, _c=clave, _a=a):
            _aa.terminar(_c, ok)
            _ban.marcar('autoarreglo', f'{"Arreglado solo" if ok else "No se pudo arreglar solo"}: {_a["titulo"]} '
                                       f'— {detalle}', equipo=_a.get('equipo'), codigo=_a['codigo'],
                        nivel='ok' if ok else 'aviso')
            if _a['codigo'] not in _aa.NO_SE_AVISA:
                _mandar_mensajes([(_aa.tipo_alerta(_a['codigo']), _aa.mensaje_resultado(_a, ok, detalle, _c, panel))])
        _ejecutar_arreglo(a['codigo'], accion, row, None, 'automático', al_terminar=_al_terminar)
        lanzados.append(clave)
    _mandar_mensajes(mensajes)
    return lanzados


def _autoarreglo_bucle():
    _vigilante_ya.wait(90)   # dejar que los agentes conecten tras arrancar (salvo que algo falle antes)
    while True:
        _vigilante_ya.clear()
        try:
            _autoarreglo_ciclo()
        except Exception as exc:
            _ban.marcar('vigilante', f'Error inesperado en el vigilante de avisos: {exc}', nivel='error')
        fin = time.time() + max(60, _aa.INTERVALO)
        while time.time() < fin:      # cada 15 s mira si el mantenimiento (otro proceso) ha pedido mirar ya
            if _vigilante_ya.wait(15) or _aa.toca_despertar():
                time.sleep(5)          # que termine de escribir lo que ha fallado
                break


@app.before_request
def _iniciar_autoarreglo():
    """Arranca el vigilante con la primera petición (solo en el panel que está funcionando)."""
    if _autoarreglo_hilo['iniciado'] or os.environ.get('OCTOPUS_AUTOARREGLO', 'si').lower() in ('no', '0', 'false'):
        return
    with _autoarreglo_lock:
        if not _autoarreglo_hilo['iniciado']:
            _autoarreglo_hilo['iniciado'] = True
            threading.Thread(target=_autoarreglo_bucle, daemon=True, name='vigilante').start()


def _semaforo_321(lista):
    """Regla de oro de las copias: 3 copias de los datos, en 2 soportes distintos, 1 fuera de la oficina."""
    import mantenimiento as _mant
    env = _mant.leer_env()
    auto = (_mant.leer_estado().get('resultados') or {}).get('autocopia') or {}
    sin_copia = [e['sys']['hostname'] for e in lista if not e['est']['copias']]
    todos = bool(lista) and not sin_copia
    externo = bool(env.get('OFFSITE_RESTIC_REPOSITORY'))
    externo_ok = externo and bool(auto.get('ok')) and 'externo' in str(auto.get('detalle', ''))
    if not externo:
        falta_ext = ('Configura un almacén externo (Backblaze, Wasabi, S3 o un NAS en otro sitio) con '
                     '«sudo bash octopus.sh ajustes». Está explicado en PRODUCCION.md.')
    else:
        falta_ext = 'El almacén externo está configurado pero la última copia allí no salió bien: revisa los avisos.'
    luces = [
        {'n': '3', 'titulo': '3 copias de tus datos', 'ok': todos and externo_ok,
         'texto': 'El original en cada equipo, la copia del servidor y la del almacén externo.' if todos and externo_ok
         else (('Faltan copias de: ' + ', '.join(sin_copia[:5]) + '. ') if sin_copia else '') + ('' if externo_ok else falta_ext)},
        {'n': '2', 'titulo': '2 soportes distintos', 'ok': todos,
         'texto': 'Cada equipo tiene su copia en el disco del servidor.' if todos else
         ('Aún no hay equipos.' if not lista else 'Sin copia todavía: ' + ', '.join(sin_copia[:5]) + '. Pulsa «Copiar todo ahora».')},
        {'n': '1', 'titulo': '1 copia fuera de la oficina', 'ok': externo_ok,
         'texto': 'Hay copia fuera de la oficina (con bloqueo por tiempo, ni un atacante puede borrarla).'
         if externo_ok else falta_ext},
    ]
    return {'luces': luces, 'ok': all(l['ok'] for l in luces)}


@app.route('/inicio')
@login_required
def inicio():
    lista = _equipos_con_estado()
    total = len(lista)
    ok = sum(1 for e in lista if e['est']['nivel'] == 'ok')
    avisos_lista = _avisos(lista)
    ultima = max((e['est']['ultima'] for e in lista if e['est']['ultima']), default=None)
    if total == 0:
        resumen = {'nivel': 'atencion', 'titulo': 'Aún no hay equipos protegidos',
                   'texto': 'Añade tu primer equipo para empezar a hacer copias.'}
    elif ok == total:
        resumen = {'nivel': 'ok', 'titulo': 'Todo está protegido',
                   'texto': f'Tus {total} equipos tienen una copia reciente. Última copia {_hace(ultima)}.'}
    else:
        nivel = 'problema' if any(a['nivel'] == 'problema' for a in avisos_lista) else 'atencion'
        resumen = {'nivel': nivel, 'titulo': f'{total - ok} de {total} equipos necesitan atención',
                   'texto': 'Abajo te explicamos qué pasa y qué hacer.'}
    conn = get_db_connection()
    actividad = conn.execute(
        "SELECT a.*, u.username FROM audit_logs a LEFT JOIN users u ON a.user_id = u.id "
        "WHERE a.action IN ('BACKUP_START','BACKUP_OK','BACKUP_ERROR','RESTORE_OK','RESTORE_ERROR','SYSTEM_ADD') "
        "ORDER BY a.timestamp DESC LIMIT 8").fetchall()
    conn.close()
    return render_template('inicio.html', lista=lista, resumen=resumen, avisos=avisos_lista[:5],
                           total=total, ok=ok, actividad=actividad, semaforo=_semaforo_321(lista))


@app.route('/equipos')
@login_required
def equipos():
    lista = _equipos_con_estado()
    multi = _fun.activa('multiempresa')
    cliente = (request.args.get('cliente') or '').strip()
    if multi and cliente:
        lista = [e for e in lista if (_cliente_de(e['sys']) or 'Sin cliente') == cliente]
    return render_template('equipos.html', lista=lista, multi=multi, cliente_de=_cliente_de,
                           clientes=_clientes_lista() if multi else [], cliente_filtro=cliente)


def _get_system(system_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM systems WHERE id = ?', (system_id,)).fetchone()
    conn.close()
    return row


@app.route('/clientes')
@login_required
def clientes():
    if not _fun.activa('multiempresa'):
        return redirect(url_for('equipos'))
    return render_template('clientes.html', clientes=_clientes_resumen())


@app.route('/equipos/<int:system_id>/cliente', methods=['POST'])
@login_required
def equipo_cliente(system_id):
    row = _get_system(system_id)
    if not row or not puede_actuar() or not _fun.activa('multiempresa'):
        return redirect(url_for('equipos'))
    nombre = (request.form.get('cliente') or '').strip()[:120]
    notas = agentes.notas_equipo(row)
    if nombre:
        notas['cliente'] = nombre
    else:
        notas.pop('cliente', None)
    with get_db_connection() as c:
        c.execute('UPDATE systems SET notes = ? WHERE id = ?', (json.dumps(notas) if notas else None, system_id))
    agentes.invalidar(system_id)
    log_audit(session['user_id'], 'SYSTEM_SETTINGS', f'{row["hostname"]}: cliente={nombre or "(ninguno)"}', request.remote_addr)
    flash('Cliente guardado.' if nombre else 'Equipo sin cliente.', 'success')
    return redirect(url_for('equipo', system_id=system_id))


@app.route('/equipos/<int:system_id>')
@login_required
def equipo(system_id):
    row = _get_system(system_id)
    if not row:
        flash('Ese equipo no existe.', 'error')
        return redirect(url_for('equipos'))
    est = agentes.estado_equipo(row, force=request.args.get('refrescar') == '1')
    import mantenimiento as _mant
    copias = _inc.marcar_copias(row['id'], est['copias'])
    return render_template('equipo.html', monitor_activa=_mon.activa(system_id), monitor_estado=_mon.estado(system_id), s=row, est=est, copias=copias, trabajos=agentes.trabajos_de(row['id'], 5),
                           prueba=_mant.leer_pruebas().get(row['hostname'].lower()),
                           horas_sin_copia=agentes.horas_sin_copia(row),
                           horas_propias=agentes.notas_equipo(row).get('horas_sin_copia'),
                           completa_activa=bool(agentes.notas_equipo(row).get('copia_completa')),
                           ultima_completa=next((c for c in copias if 'completa' in (c.get('tags') or [])), None),
                           limpia=_inc.ultima_limpia(copias) if any(c['sospechosa'] for c in copias) else None,
                           pasos=_ban.leer(equipo=row['hostname'], limite=12),
                           multi=_fun.activa('multiempresa'), cliente=_cliente_de(row),
                           clientes=_clientes_lista() if _fun.activa('multiempresa') else [])


def _lanzar_prueba(row, user_id=None):
    """Prueba de recuperacion en segundo plano (recupera de verdad unos archivos de la ultima copia)."""
    import mantenimiento as _mant
    import uuid as _uuid
    job_id = _uuid.uuid4().hex[:10]
    with agentes._jobs_lock:
        for j in agentes.JOBS.values():
            if j['system_id'] == row['id'] and j['estado'] == 'en_curso' and j.get('tipo') == 'prueba':
                return j['id']
        agentes.JOBS[job_id] = {'id': job_id, 'system_id': row['id'], 'equipo': row['hostname'], 'tipo': 'prueba',
                                'estado': 'en_curso', 'mensaje': 'Recuperando unos archivos de la última copia...',
                                'inicio': datetime.now(timezone.utc), 'fin': None}

    def _run():
        _ban.marcar('pruebas', 'Empieza la prueba de recuperación', equipo=row['hostname'])
        try:
            r = _mant.probar_equipo(_mant.leer_env(), row['hostname'])
        except Exception as exc:
            r = {'ok': False, 'detalle': f'Error inesperado: {exc}'}
        with agentes._jobs_lock:
            agentes.JOBS[job_id].update(estado='ok' if r['ok'] else 'error', mensaje=r['detalle'],
                                        fin=datetime.now(timezone.utc))
        log_audit(user_id, 'RESTORE_TEST_OK' if r['ok'] else 'RESTORE_TEST_ERROR', f'{row["hostname"]}: {r["detalle"]}'[:300])
        _ban.marcar('pruebas', f'Prueba de recuperación: {r["detalle"]}', equipo=row['hostname'],
                    codigo=None if r['ok'] else 'OCT-EQ-05', nivel='ok' if r['ok'] else 'error')
        if not r['ok']:
            _despertar_vigilante()   # el vigilante manda el aviso con su solución (y la intenta si no tiene riesgo)

    threading.Thread(target=_run, daemon=True).start()
    return job_id


@app.route('/equipos/<int:system_id>/probar-recuperacion', methods=['POST'])
@login_required
def probar_recuperacion(system_id):
    row = _get_system(system_id)
    if row and puede_actuar():
        _lanzar_prueba(row, session['user_id'])
        flash('Prueba de recuperación en marcha: se recuperan unos archivos de la última copia para comprobar que '
              'se pueden recuperar de verdad. Tarda unos segundos.', 'success')
    return redirect(url_for('equipo', system_id=system_id))


HORAS_SIN_COPIA = [(0, 'Lo normal (avisar si pasa más de 1 día)'), (48, 'Avisar a los 2 días'),
                   (72, 'Avisar a los 3 días'), (168, 'Avisar a la semana (portátiles que salen fuera)')]
app.jinja_env.globals['HORAS_SIN_COPIA'] = HORAS_SIN_COPIA


@app.route('/equipos/<int:system_id>/ajustes', methods=['POST'])
@login_required
def equipo_ajustes(system_id):
    row = _get_system(system_id)
    if not row or not puede_actuar():
        return redirect(url_for('equipos'))
    try:
        horas = int(request.form.get('horas_sin_copia', '0'))
    except ValueError:
        horas = 0
    if horas not in [h for h, _ in HORAS_SIN_COPIA]:
        horas = 0
    notas = agentes.notas_equipo(row)
    if horas:
        notas['horas_sin_copia'] = horas
    else:
        notas.pop('horas_sin_copia', None)
    with get_db_connection() as c:
        c.execute('UPDATE systems SET notes = ? WHERE id = ?', (json.dumps(notas) if notas else None, system_id))
    agentes.invalidar(system_id)
    log_audit(session['user_id'], 'SYSTEM_SETTINGS', f'{row["hostname"]}: horas_sin_copia={horas or "general"}', request.remote_addr)
    flash('Guardado.', 'success')
    return redirect(url_for('equipo', system_id=system_id))


# ------------------------------------------------------------------ copias de las bases de datos de un equipo
import re as _re_vm
_MOTORES_BD = {'sqlserver': 'SQL Server', 'mysql': 'MySQL / MariaDB', 'postgresql': 'PostgreSQL'}
_FRECUENCIAS_BD = [(24, 'Cada día (con la copia diaria)'), (4, 'Cada 4 horas'),
                   (1, 'Cada hora (recomendado si se trabaja todo el día con el programa)')]


def _clave_bd(b):
    return f"{b.get('motor')}:{b.get('instancia', 'local')}:{b.get('nombre')}"


@app.route('/equipos/<int:system_id>/bd')
@login_required
def equipo_bd(system_id):
    """Las bases de datos de un equipo: cuáles copiar, cada cuánto, permisos, copias hechas, recuperar y descargar."""
    row = _get_system(system_id)
    if not row:
        return redirect(url_for('equipos'))
    ok, motivo = _fun.para_equipo('copias_bd', row['os_family'] or '')
    datos, error = {}, ''
    if ok:
        if agentes.estado_equipo(row).get('online'):
            r = agentes.Agente(agentes.ip_de(row)).bd()
            if r.get('status') == 'success':
                datos = r
            else:
                error = r.get('message') or 'El equipo no ha contestado.'
        else:
            error = 'El equipo está apagado o desconectado: enciéndelo para ver sus bases de datos.'
    conf = agentes.notas_equipo(row).get('bd') or {}
    grupos = {}
    for c in datos.get('copias', []):
        grupos.setdefault((c['motor'], c['instancia'], c['nombre']), []).append(c)
    return render_template('bd.html', s=row, ok=ok, motivo=motivo, error=error, motores=datos.get('motores', []),
                           grupos=grupos, conf=conf, con_clave=sorted(_bd_credenciales(conf)),
                           trabajos=agentes.trabajos_de(row['id'], 5), MOTORES=_MOTORES_BD,
                           FRECUENCIAS=_FRECUENCIAS_BD, clave_bd=_clave_bd)


@app.route('/equipos/<int:system_id>/bd', methods=['POST'])
@login_required
def equipo_bd_accion(system_id):
    row = _get_system(system_id)
    if not row or not puede_actuar():
        return redirect(url_for('equipos'))
    ok, motivo = _fun.para_equipo('copias_bd', row['os_family'] or '')
    volver = redirect(url_for('equipo_bd', system_id=system_id))
    if not ok:
        flash(motivo, 'error')
        return volver
    accion = request.form.get('accion')
    notas = agentes.notas_equipo(row)
    conf = dict(notas.get('bd') or {})

    def guardar(texto_log):
        notas['bd'] = conf
        with get_db_connection() as c:
            c.execute('UPDATE systems SET notes = ? WHERE id = ?', (json.dumps(notas), system_id))
        agentes.invalidar(system_id)
        log_audit(session['user_id'], 'SYSTEM_SETTINGS', f'{row["hostname"]}: {texto_log}', request.remote_addr)

    if accion == 'guardar':
        horas = request.form.get('horas', type=int)
        conf.update(activa=request.form.get('activa') == 'on', horas=horas if horas in (1, 4, 24) else 24,
                    excluir=sorted(set(request.form.getlist('todas')) - set(request.form.getlist('incluir'))))
        guardar(f"copias_bd activa={conf['activa']} horas={conf['horas']} fuera={conf['excluir']}")
        texto = {24: 'cada día', 4: 'cada 4 horas', 1: 'cada hora'}[conf['horas']]
        flash(f'Copias de bases de datos activadas: {texto}. La primera llega en unos minutos (o pulsa «Copiar ahora»).'
              if conf['activa'] else 'Copias de bases de datos desactivadas. Las ya hechas se borran solas con las antiguas.',
              'success')
    elif accion == 'credenciales':
        motor = request.form.get('motor', '')
        if motor not in _MOTORES_BD:
            return volver
        cred = _bd_credenciales(conf)
        if request.form.get('borrar'):
            cred.pop(motor, None)
            flash(f'Usuario de {_MOTORES_BD[motor]} borrado.', 'success')
        else:
            usuario = (request.form.get('usuario') or '').strip()[:120]
            if not usuario:
                flash('Escribe el usuario.', 'error')
                return volver
            cred[motor] = {'usuario': usuario, 'clave': request.form.get('clave') or ''}
            flash(f'Guardado (cifrado). En unos segundos verás si ya puedo entrar en {_MOTORES_BD[motor]}.', 'success')
        conf['cred_cifradas'] = _dosfa.cifrar(DB_FILE, json.dumps(cred)) if cred else None
        guardar(f'credenciales de {motor} {"borradas" if request.form.get("borrar") else "cambiadas"}')
    elif accion == 'ahora':
        if not conf.get('activa'):
            flash('Primero activa las copias de bases de datos de este equipo.', 'error')
            return volver
        agentes.lanzar_copia(row, on_done=_copia_terminada, bd=True)
        log_audit(session['user_id'], 'DB_BACKUP_START', f'equipo={row["hostname"]}', request.remote_addr)
        flash('Copiando las bases de datos ahora. Suele tardar poco; recarga la página en un momento.', 'success')
    elif accion == 'restaurar':
        snap, motor = request.form.get('snapshot', ''), request.form.get('motor', '')
        nombre, instancia = request.form.get('nombre', '')[:128], request.form.get('instancia', 'local')[:128]
        if not _re_vm.fullmatch(r'[0-9a-fA-F]{6,64}', snap) or motor not in _MOTORES_BD:
            flash('Copia no válida.', 'error')
            return volver
        agentes.lanzar_restauracion_bd(row, snap, motor, nombre, instancia, on_done=_copia_terminada)
        log_audit(session['user_id'], 'DB_RESTORE_START', f'equipo={row["hostname"]} bd={nombre} copia={snap}',
                  request.remote_addr)
        flash(f'Recuperando «{nombre}» como una base de datos NUEVA (la original no se toca). Recarga en un momento.',
              'success')
    return volver


@app.route('/equipos/<int:system_id>/bd/descargar/<snap>')
@login_required
def equipo_bd_descargar(system_id, snap):
    """Descargar una copia de base de datos (el volcado o el .bak), leída directamente del almacén del servidor."""
    row = _get_system(system_id)
    if not row or not puede_actuar() or not _re_vm.fullmatch(r'[0-9a-fA-F]{6,64}', snap):
        abort(404)
    ruta, nombre = agentes.copia_bd_en_servidor(row, snap)
    if not ruta:
        flash('No encuentro esa copia en el almacén.', 'error')
        return redirect(url_for('equipo_bd', system_id=system_id))
    log_audit(session['user_id'], 'DB_DOWNLOAD', f'equipo={row["hostname"]} copia={snap} archivo={nombre}',
              request.remote_addr)
    proc = agentes.volcar_bd_en_servidor(snap, ruta)

    def trozos():
        try:
            while True:
                b = proc.stdout.read(1024 * 1024)
                if not b:
                    break
                yield b
        finally:
            proc.stdout.close()
            proc.wait()
    seguro = re.sub(r'[^A-Za-z0-9_.-]', '_', nombre) or 'copia'
    return Response(trozos(), mimetype='application/octet-stream',
                    headers={'Content-Disposition': f'attachment; filename="{snap}_{seguro}"'})


# ------------------------------------------------------------------ copias de las máquinas virtuales de un equipo
import re as _re_vm

_HIPERVISORES = {'hyperv': 'Hyper-V', 'libvirt': 'KVM / libvirt', 'proxmox': 'Proxmox'}


@app.route('/equipos/<int:system_id>/vms')
@login_required
def equipo_vms(system_id):
    """Las máquinas virtuales de un equipo: cuáles copiar, cada cuánto, las copias hechas y recuperar."""
    row = _get_system(system_id)
    if not row:
        return redirect(url_for('equipos'))
    ok, motivo = _fun.para_equipo('copias_vm', row['os_family'] or '')
    datos, error = {}, ''
    if ok:
        if agentes.estado_equipo(row).get('online'):
            r = agentes.Agente(agentes.ip_de(row)).vms()
            if r.get('status') == 'success':
                datos = r
            else:
                error = r.get('message') or 'El equipo no ha contestado.'
        else:
            error = 'El equipo está apagado o desconectado: enciéndelo para ver sus máquinas virtuales.'
    return render_template('vms.html', s=row, ok=ok, motivo=motivo, error=error, vms=datos.get('vms', []),
                           copias=datos.get('copias', []), conf=agentes.notas_equipo(row).get('vms') or {},
                           trabajos=agentes.trabajos_de(row['id'], 5), HIP=_HIPERVISORES)


@app.route('/equipos/<int:system_id>/vms', methods=['POST'])
@login_required
def equipo_vms_accion(system_id):
    row = _get_system(system_id)
    if not row or not puede_actuar():
        return redirect(url_for('equipos'))
    ok, motivo = _fun.para_equipo('copias_vm', row['os_family'] or '')
    volver = redirect(url_for('equipo_vms', system_id=system_id))
    if not ok:
        flash(motivo, 'error')
        return volver
    accion = request.form.get('accion')
    notas = agentes.notas_equipo(row)
    conf = notas.get('vms') or {}
    if accion == 'guardar':
        activa = request.form.get('activa') == 'on'
        todas = [n[:200] for n in request.form.getlist('todas')]
        marcadas = set(request.form.getlist('incluir'))
        notas['vms'] = {'activa': activa, 'dias': 7 if request.form.get('dias') == '7' else 1,
                        'excluir': sorted(n for n in todas if n not in marcadas)}
        with get_db_connection() as c:
            c.execute('UPDATE systems SET notes = ? WHERE id = ?', (json.dumps(notas), system_id))
        agentes.invalidar(system_id)
        log_audit(session['user_id'], 'SYSTEM_SETTINGS', f'{row["hostname"]}: copias_vm={notas["vms"]}', request.remote_addr)
        flash(('Copias de máquinas virtuales activadas: ' + ('cada semana' if notas['vms']['dias'] == 7 else 'cada día')
               + ' (la primera, en la próxima copia diaria; o pulsa «Copiar ahora»).') if activa else
              'Copias de máquinas virtuales desactivadas. Las ya hechas se borran solas con las antiguas.', 'success')
    elif accion == 'ahora':
        if not conf.get('activa'):
            flash('Primero activa las copias de máquinas virtuales de este equipo.', 'error')
            return volver
        agentes.lanzar_copia(row, on_done=_copia_terminada, vms=True)
        log_audit(session['user_id'], 'VM_BACKUP_START', f'equipo={row["hostname"]}', request.remote_addr)
        flash('Copia de las máquinas virtuales en marcha. La primera puede tardar horas; puedes seguir usando el panel.',
              'success')
    elif accion == 'restaurar':
        snap, nombre = request.form.get('snapshot', ''), request.form.get('nombre', '')[:200]
        hip = request.form.get('hipervisor', '')
        if not _re_vm.fullmatch(r'[0-9a-fA-F]{6,64}', snap) or hip not in _HIPERVISORES:
            flash('Copia no válida.', 'error')
            return volver
        agentes.lanzar_restauracion_vm(row, snap, nombre, hip, on_done=_copia_terminada)
        log_audit(session['user_id'], 'VM_RESTORE_START', f'equipo={row["hostname"]} vm={nombre} copia={snap}',
                  request.remote_addr)
        flash(f'Recuperando {nombre} en una carpeta aparte del equipo (la máquina original no se toca). '
              'Cuando termine, aquí verás dónde ha quedado y cómo arrancarla.', 'success')
    return volver


@app.route('/equipos/<int:system_id>/copia-completa', methods=['POST'])
@login_required
def equipo_copia_completa(system_id):
    """Copia completa del equipo (opcional): activar/desactivar, o hacerla ahora."""
    row = _get_system(system_id)
    if not row or not puede_actuar():
        return redirect(url_for('equipos'))
    if request.form.get('accion') == 'ahora':
        if agentes.notas_equipo(row).get('copia_completa'):
            agentes.lanzar_copia(row, on_done=_copia_terminada, completa=True)
            log_audit(session['user_id'], 'FULL_BACKUP_START', f'equipo={row["hostname"]}', request.remote_addr)
            flash(f'Copia completa de {row["hostname"]} en marcha. La primera puede tardar horas; puedes seguir usando '
                  'el panel.', 'success')
        return redirect(url_for('equipo', system_id=system_id))
    activa = request.form.get('activa') == 'on'
    notas = agentes.notas_equipo(row)
    if activa:
        notas['copia_completa'] = True
    else:
        notas.pop('copia_completa', None)
    with get_db_connection() as c:
        c.execute('UPDATE systems SET notes = ? WHERE id = ?', (json.dumps(notas) if notas else None, system_id))
    agentes.invalidar(system_id)
    log_audit(session['user_id'], 'SYSTEM_SETTINGS', f'{row["hostname"]}: copia_completa={activa}', request.remote_addr)
    flash('Copia completa activada: se hará una vez por semana (la primera, en la próxima copia diaria).' if activa
          else 'Copia completa desactivada. Las copias completas ya hechas se borran solas con las antiguas.', 'success')
    return redirect(url_for('equipo', system_id=system_id))


def _ajustes_agente(row):
    """Ajustes generales de las copias + los propios de este equipo (los recibe el agente en cada consulta)."""
    aj = _ajustes_copias()
    vms = agentes.notas_equipo(row).get('vms') or {}
    bd = agentes.notas_equipo(row).get('bd') or {}
    return {'limite_kbps': aj['limite_kbps'], 'solo_horario': aj['solo_horario'],
            'copia_completa': bool(agentes.notas_equipo(row).get('copia_completa')), 'copia_completa_dias': 7,
            'senuelos': config_manager.get_config('senuelos') is not False,
            # siempre se manda (aunque esté apagada): si no, el agente se quedaría con lo último que recibió
            'vms': {'activa': bool(vms.get('activa')) and _fun.activa('copias_vm'), 'dias': vms.get('dias') or 1,
                    'excluir': list(vms.get('excluir') or [])},
            'bd': {'activa': bool(bd.get('activa')) and _fun.activa('copias_bd'), 'horas': bd.get('horas') or 24,
                   'excluir': list(bd.get('excluir') or []), 'cred': _bd_credenciales(bd)}}


def _bd_credenciales(bd):
    """Usuarios y contraseñas de las bases de datos de un equipo (guardadas cifradas; solo si hicieron falta)."""
    if not bd.get('cred_cifradas'):
        return {}
    try:
        return json.loads(_dosfa.descifrar(DB_FILE, bd['cred_cifradas']))
    except Exception:
        return {}


def _copia_terminada(system_id, ok, resp):
    try:
        fila = _get_system(system_id)
        nombre = fila['hostname'] if fila else str(system_id)
        for paso in (resp.get('pasos') or [])[-30:]:
            _ban.marcar('copias', f'(en el equipo) {paso}', equipo=nombre)
        motivo = str(resp.get('message', ''))[:300]
        _ban.marcar('copias', ('Copia terminada' + (f' con aviso: {resp.get("aviso")}' if resp.get('aviso') else ''))
                    if ok else f'La copia falló: {motivo}', equipo=nombre,
                    codigo=None if ok else 'OCT-EQ-04', nivel='ok' if ok else 'error')
    except Exception:
        nombre, motivo = str(system_id), str(resp.get('message', ''))[:300]
    try:
        conn = get_db_connection()
        if ok:
            conn.execute("UPDATE systems SET last_backup = ?, status = 'online', last_seen = ? WHERE id = ?",
                         (datetime.now(), datetime.now(), system_id))
        conn.commit()
        conn.close()
        log_audit(None, 'BACKUP_OK' if ok else 'BACKUP_ERROR',
                  f'equipo={nombre} ' + ('' if ok else motivo[:200]))
        if not ok:
            _despertar_vigilante()   # el vigilante manda el aviso con su solución y repite la copia
    except Exception as e:
        print(f'[copia] aviso registrando resultado: {e}')


@app.route('/equipos/<int:system_id>/copia', methods=['POST'])
@login_required
def equipo_copia(system_id):
    if not puede_actuar():
        flash('Tu usuario no tiene permiso para lanzar copias.', 'error')
        return redirect(url_for('equipo', system_id=system_id))
    row = _get_system(system_id)
    if row:
        agentes.lanzar_copia(row, on_done=_copia_terminada)
        _ban.marcar('copias', f'Copia pedida desde el panel por {session.get("username", "?")}', equipo=row['hostname'])
        log_audit(session['user_id'], 'BACKUP_START', f'equipo={row["hostname"]}', request.remote_addr)
        flash(f'Copia de {row["hostname"]} en marcha. Tarda unos minutos; puedes seguir usando el panel.', 'success')
    volver = request.form.get('volver', '')
    if not volver.startswith('/') or volver.startswith('//'):
        volver = url_for('equipo', system_id=system_id)
    return redirect(volver)


@app.route('/copiar-todo', methods=['POST'])
@login_required
def copiar_todo():
    if not puede_actuar():
        flash('Tu usuario no tiene permiso para lanzar copias.', 'error')
        return redirect(url_for('inicio'))
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM systems').fetchall()
    conn.close()
    for r in rows:
        agentes.lanzar_copia(r, on_done=_copia_terminada)
        _ban.marcar('copias', f'Copia pedida con «Copiar todo» por {session.get("username", "?")}', equipo=r['hostname'])
    log_audit(session['user_id'], 'BACKUP_START', f'todos ({len(rows)} equipos)', request.remote_addr)
    flash(f'Copias en marcha en {len(rows)} equipos. Tardan unos minutos.', 'success')
    return redirect(url_for('inicio'))


@app.route('/restaurar')
@login_required
def restaurar():
    return render_template('restaurar.html', lista=_equipos_con_estado())


def _migas(path, paths):
    """Migas de pan para navegar dentro de una ruta protegida."""
    sep = '\\' if '\\' in path else '/'
    base = None
    for b in paths:
        bb = b.rstrip('/\\')
        if path == b or path == bb or path.startswith(bb + '/') or path.startswith(bb + '\\'):
            base = bb
            break
    if not base:
        return []
    migas = [(base, base)]
    acum = base
    for parte in [p for p in path[len(base):].replace('\\', '/').split('/') if p]:
        acum = acum + sep + parte
        migas.append((parte, acum))
    return migas


@app.route('/equipos/<int:system_id>/explorar')
@login_required
def explorar(system_id):
    row = _get_system(system_id)
    if not row:
        return redirect(url_for('restaurar'))
    est = dict(agentes.estado_equipo(row))
    est['copias'] = _inc.marcar_copias(row['id'], est['copias'])
    limpia = _inc.ultima_limpia(est['copias'])
    # por defecto se abre la ultima copia LIMPIA (no una hecha durante un ataque)
    snapshot = request.args.get('copia') or (limpia['id'] if limpia else (est['copias'][0]['id'] if est['copias'] else None))
    copia_sel = next((c for c in est['copias'] if c['id'] == snapshot), None)
    paths = (copia_sel or {}).get('paths') or (est.get('info') or {}).get('backup_paths') or []
    path = request.args.get('ruta') or ''
    contenido, error = None, None
    if snapshot and path:
        r = agentes.listar_en_servidor(row, snapshot, path)
        if r.get('status') == 'success':
            contenido = r['items']
        else:
            error = r.get('message')
    migas = _migas(path, paths) if path else []
    padre = migas[-2][1] if len(migas) > 1 else None
    return render_template('explorar.html', s=row, est=est, copia=snapshot, copia_sel=copia_sel, paths=paths,
                           ruta=path, contenido=contenido, error=error, migas=migas, padre=padre, limpia=limpia)


@app.route('/equipos/<int:system_id>/restaurar', methods=['POST'])
@login_required
def restaurar_ruta(system_id):
    row = _get_system(system_id)
    ruta = request.form.get('ruta', '')
    copia = request.form.get('copia', 'latest')
    destino = 'aparte' if request.form.get('destino') == 'aparte' else 'original'
    volver = url_for('explorar', system_id=system_id, copia=copia, ruta=request.form.get('carpeta', ''))
    if request.form.get('volver', '').startswith('/') and not request.form.get('volver', '').startswith('//'):
        volver = request.form['volver']
    if not row or not ruta:
        return redirect(url_for('restaurar'))
    if not puede_recuperar():
        flash('Tu usuario no tiene permiso para restaurar.', 'error')
        return redirect(volver)
    _ban.marcar('recuperacion', f'Recuperar «{ruta}» de la copia {copia} ({destino}), pedido por '
                f'{session.get("username", "?")}', equipo=row['hostname'])
    r = agentes.Agente(agentes.ip_de(row)).restore(ruta, copia, destino)
    _ban.marcar('recuperacion', f'Recuperado en {r.get("file")}' if r.get('status') == 'success'
                else f'La recuperación falló: {str(r.get("message", ""))[:300]}', equipo=row['hostname'],
                nivel='ok' if r.get('status') == 'success' else 'error')
    if r.get('status') == 'success':
        log_audit(session['user_id'], 'RESTORE_OK', f'{row["hostname"]}:{ruta} copia={copia} destino={destino}', request.remote_addr)
        _notificar_incidente('restauracion', f'Recuperación terminada en {row["hostname"]}: «{ruta}» '
                             f'(copia {copia}, {"en su sitio original" if str(r.get("file")) == ruta else "guardada aparte en " + str(r.get("file"))}). '
                             f'La pidió el usuario {session.get("username", "?")}.')
        if destino == 'aparte' or (r.get('file') and str(r.get('file')).rstrip('/\\') != ruta.rstrip('/\\')):
            # (desde una copia completa, lo que es del sistema se deja siempre al lado, sin sobrescribir)
            flash(f'Listo. La versión recuperada está en: {r.get("file")}', 'success')
        else:
            flash(f'Listo. «{ruta}» ha vuelto a como estaba en esa copia.', 'success')
    else:
        log_audit(session['user_id'], 'RESTORE_ERROR', f'{row["hostname"]}:{ruta} {str(r.get("message", ""))[:200]}', request.remote_addr)
        _notificar_incidente('restauracion', f'La recuperación de «{ruta}» en {row["hostname"]} ha fallado: '
                             f'{str(r.get("message", ""))[:300]}\nQué hacer: comprueba que el equipo está encendido y '
                             f'conectado, y vuelve a intentarlo desde el panel.')
        flash(f'No se pudo restaurar: {r.get("message")}', 'error')
    return redirect(volver)


@app.route('/equipos/nuevo', methods=['GET', 'POST'])
@login_required
def equipo_nuevo():
    import alta_equipos
    if request.method == 'POST':
        if not puede_actuar():
            flash('Tu usuario no tiene permiso para añadir equipos.', 'error')
            return redirect(url_for('equipos'))
        nombre = (request.form.get('hostname') or '').strip()
        so = request.form.get('os_family') if request.form.get('os_family') in ('linux', 'windows', 'macos') else 'windows'
        ip = (request.form.get('ip_address') or '').strip()
        if not alta_equipos.nombre_valido(nombre):
            flash('Escribe el nombre exacto del equipo, sin espacios (por ejemplo PC-ANA o portatil-ana).', 'error')
            return redirect(url_for('equipo_nuevo'))
        if ip:
            import ipaddress as _ipaddr
            try:
                _ipaddr.ip_address(ip)
            except ValueError:
                flash('La dirección IP no es válida (ejemplo: 192.168.1.25). Puedes dejarla vacía.', 'error')
                return redirect(url_for('equipo_nuevo'))
        try:
            rutas = alta_equipos.limpiar_rutas(request.form.get('rutas', ''), so)
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('equipo_nuevo'))
        remoto = request.form.get('modo') == 'remoto' and so in ('linux', 'macos', 'windows')
        usuario = (request.form.get('usuario') or '').strip()
        if remoto:
            error = _datos_remotos_validos(ip, usuario)
            if error:
                flash(error, 'error')
                return redirect(url_for('equipo_nuevo'))
        conn = get_db_connection()
        if conn.execute('SELECT 1 FROM systems WHERE lower(hostname) = lower(?)', (nombre,)).fetchone():
            conn.close()
            flash(f'Ya hay un equipo llamado {nombre}.', 'error')
            return redirect(url_for('equipo_nuevo'))
        conn.close()
        conn = get_db_connection()
        cur = conn.execute("INSERT INTO systems (hostname, ip_address, os_family, status, notes) "
                           "VALUES (?, ?, ?, 'unknown', ?)",
                           (nombre, ip or '', so,
                            json.dumps({'rutas': rutas, **({'cliente': (request.form.get('cliente') or '').strip()[:120]}
                                                           if (request.form.get('cliente') or '').strip() else {})})))
        conn.commit()
        sid = cur.lastrowid
        conn.close()
        log_audit(session['user_id'], 'SYSTEM_ADD', f'{nombre} ({so})', request.remote_addr)
        if remoto:
            _lanzar_instalacion_remota(_get_system(sid), ip, usuario, request.form.get('password') or '',
                                       request.form.get('solo_clave') == '1')
            flash(f'Conectando con {nombre} ({ip}) para instalar OCTOPUS. Tarda unos minutos; esta página se actualiza sola.', 'success')
            return redirect(url_for('equipo', system_id=sid))
        return redirect(url_for('equipo_instalar', system_id=sid))
    return render_template('equipo_nuevo.html', rutas_defecto=alta_equipos.RUTAS_POR_DEFECTO,
                           multi=_fun.activa('multiempresa'), clientes=_clientes_lista() if _fun.activa('multiempresa') else [])


def _rutas_de(system):
    try:
        return json.loads(system['notes'] or '{}').get('rutas') or []
    except (ValueError, TypeError, IndexError, KeyError):
        return []


@app.route('/equipos/<int:system_id>/instalar')
@login_required
@role_required('admin', 'supremo')
def equipo_instalar(system_id):
    system = _get_system(system_id)
    if not system:
        abort(404)
    import alta_equipos
    rutas = _rutas_de(system) or alta_equipos.RUTAS_POR_DEFECTO.get(system['os_family'], [])
    return render_template('equipo_instalar.html', sys=system, rutas=rutas)


@app.route('/equipos/<int:system_id>/instalador', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def equipo_instalador(system_id):
    """Paquete .zip con el agente y su configuracion (contiene la clave del equipo: queda registrado)."""
    system = _get_system(system_id)
    if not system:
        abort(404)
    import alta_equipos
    so = system['os_family'] if system['os_family'] in ('windows', 'linux', 'macos') else 'linux'
    rutas = _rutas_de(system) or alta_equipos.RUTAS_POR_DEFECTO.get(so, [])
    try:
        # cada descarga genera una clave nueva para el equipo: los instaladores descargados antes dejan de valer
        data = alta_equipos.paquete(system['hostname'], so, rutas, _ordenes.nuevo_token(system['hostname']))
    except Exception as exc:
        flash(f'No se pudo preparar el instalador: {exc}', 'error')
        return redirect(url_for('equipo_instalar', system_id=system_id))
    log_audit(session['user_id'], 'AGENT_PACKAGE', f'Instalador descargado para {system["hostname"]} (clave nueva)', request.remote_addr)
    resp = app.response_class(data, mimetype='application/zip')
    resp.headers['Content-Disposition'] = f'attachment; filename="octopus-{system["hostname"]}.zip"'
    return resp


def _datos_remotos_validos(ip, usuario):
    """Devuelve un mensaje de error o None."""
    import re as _re
    import ipaddress as _ipaddr
    try:
        _ipaddr.ip_address(ip)
    except ValueError:
        if not _re.match(r'^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$', ip or ''):
            return 'Escribe la dirección IP del equipo (ejemplo: 192.168.1.25).'
    if not _re.match(r'^[a-z_][a-z0-9_.-]{0,31}$', usuario or '', _re.I):
        return 'Escribe el usuario del equipo (un administrador, por ejemplo: ana).'
    return None


def _lanzar_instalacion_remota(system, ip, usuario, password, solo_clave):
    """Entra en el equipo por SSH e instala OCTOPUS en segundo plano. La contrasena no se guarda."""
    import alta_equipos
    import instalacion_remota
    so = system['os_family']
    rutas = _rutas_de(system) or alta_equipos.RUTAS_POR_DEFECTO.get(so, [])
    conn = get_db_connection()
    conn.execute('UPDATE systems SET ip_address = ? WHERE id = ?', (ip, system['id']))
    conn.commit()
    conn.close()

    def hacer_paquete():
        return alta_equipos.paquete(system['hostname'], so, rutas, _ordenes.nuevo_token(system['hostname']))

    def terminado(sys_row, ok, msg):
        log_audit(None, 'AGENT_REMOTE_OK' if ok else 'AGENT_REMOTE_ERROR', f'{sys_row["hostname"]}: {msg}'[:300])
        agentes.invalidar(sys_row['id'])

    jid = instalacion_remota.lanzar(dict(system), ip, usuario, password, solo_clave, agentes.JOBS, agentes._jobs_lock,
                                    hacer_paquete, _ordenes.en_linea, terminado)
    log_audit(session['user_id'], 'AGENT_REMOTE_START', f'{system["hostname"]} ({ip}, usuario {usuario})', request.remote_addr)
    _ban.marcar('instalacion', f'Instalación a distancia por SSH ({ip}, usuario {usuario})', equipo=system['hostname'])
    return jid


@app.route('/equipos/<int:system_id>/instalar-remoto', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def equipo_instalar_remoto(system_id):
    """Instalacion a distancia (Linux/Mac por SSH) desde la pagina del instalador."""
    system = _get_system(system_id)
    if not system:
        abort(404)
    ip = (request.form.get('ip') or '').strip()
    usuario = (request.form.get('usuario') or '').strip()
    volver = url_for('equipo_instalar', system_id=system_id)
    error = _datos_remotos_validos(ip, usuario)
    if error:
        flash(error, 'error')
        return redirect(volver)
    _lanzar_instalacion_remota(system, ip, usuario, request.form.get('password') or '', request.form.get('solo_clave') == '1')
    flash(f'Conectando con {system["hostname"]} ({ip}) para instalar OCTOPUS. Tarda unos minutos; esta página se actualiza sola.', 'success')
    return redirect(url_for('equipo', system_id=system_id))


@app.route('/avisos')
@login_required
def avisos():
    return render_template('avisos.html', avisos=_avisos(_equipos_con_estado()))


@app.route('/ajustes')
@login_required
def ajustes():
    conn = get_db_connection()
    user = conn.execute('SELECT username, email, role, last_login FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    eventos = conn.execute("SELECT * FROM audit_logs WHERE user_id = ? AND action LIKE 'LOGIN%' "
                           "ORDER BY timestamp DESC LIMIT 5", (session['user_id'],)).fetchall()
    conn.close()
    cfg = {k: config_manager.get_config(k) for k in ('incident_auto_response', 'incident_keep_isolated',
                                                    'security_contact', 'sandbox_terminal')}
    cfg['senuelos'] = config_manager.get_config('senuelos') is not False
    cfg['autoarreglo'] = config_manager.get_config('autoarreglo') is not False
    import mantenimiento as _mant
    with get_db_connection() as c:
        kit = c.execute("SELECT timestamp FROM audit_logs WHERE action = 'RECOVERY_KIT' ORDER BY timestamp DESC LIMIT 1").fetchone()
    return render_template('ajustes.html', user=user, eventos=eventos, https=USE_HTTPS, cfg=cfg,
                           aprobaciones=_seg.pendientes(DB_FILE),
                           mant=_mant.leer_estado(), mant_nombres=_mant.NOMBRES,
                           kit_fecha=kit['timestamp'] if kit else None,
                           ajustes_copias=_ajustes_copias(), act=_av.leer_actualizacion(),
                           act_estado=__import__('actualizar').estado(), version=_av.version_local(),
                           act_solo=config_manager.get_config('actualizar_solo') is not False,
                           act_atascada=__import__('actualizar').automatica_atascada(_av.leer_actualizacion().get('remota', '')))


@app.route('/ajustes/actualizaciones/automaticas', methods=['POST'])
@login_required
@role_required('supremo', 'admin')
def actualizaciones_automaticas():
    """Pausa o reanuda las actualizaciones automáticas (por si el cliente no quiere que se actualice solo)."""
    activar = request.form.get('activar') == '1'
    config_manager.set_config('actualizar_solo', activar, session['user_id'])
    log_audit(session['user_id'], 'UPDATE_AUTO_ON' if activar else 'UPDATE_AUTO_OFF', '', request.remote_addr)
    _ban.marcar('actualizacion', f'Actualizaciones automáticas {"activadas" if activar else "en pausa"} por '
                                 f'{session.get("username")}')
    if activar:
        flash('Actualizaciones automáticas activadas: cuando salga una versión nueva firmada, se instalará sola por la noche.',
              'success')
    else:
        flash('Actualizaciones automáticas en pausa: OCTOPUS seguirá avisando de las versiones nuevas, pero no las '
              'instalará hasta que pulses «Actualizar ahora» o las vuelvas a activar.', 'success')
    return redirect(url_for('ajustes') + '#actualizaciones')


@app.route('/ajustes/actualizaciones/buscar', methods=['POST'])
@login_required
@role_required('supremo', 'admin')
def buscar_actualizaciones():
    r = _av.comprobar_actualizacion()
    log_audit(session['user_id'], 'UPDATE_CHECK', r.get('detalle', ''), request.remote_addr)
    if r.get('hay_nueva'):
        flash(f'Hay una versión nueva: {r.get("remota")} (tienes la {r.get("local")}).', 'success')
    else:
        flash(f'Comprobado: {r.get("detalle")}.', 'success' if 'no se pudo' not in str(r.get('detalle')) else 'error')
    return redirect(url_for('ajustes') + '#actualizaciones')


@app.route('/ajustes/actualizaciones/actualizar', methods=['POST'])
@login_required
@role_required('supremo', 'admin')
def actualizar_ahora():
    """Pide al servidor que se actualice. Pide la contraseña otra vez; el equipo solo instala versiones firmadas."""
    import actualizar as _act
    volver = url_for('ajustes') + '#actualizaciones'
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    if request.form.get('accion') == 'cancelar':
        _act.cancelar()
        log_audit(session['user_id'], 'UPDATE_CANCEL', '', request.remote_addr)
        flash('Petición de actualización cancelada.', 'success')
        return redirect(volver)
    if not verify_password(request.form.get('password', ''), user['password_hash']):
        log_audit(session['user_id'], 'UPDATE_DENIED', 'Contraseña incorrecta', request.remote_addr)
        flash('La contraseña no es correcta.', 'error')
        return redirect(volver)
    act = _av.leer_actualizacion()
    if not act.get('hay_nueva'):
        flash('No hay ninguna versión nueva. Pulsa «Buscar actualizaciones» para comprobarlo otra vez.', 'error')
        return redirect(volver)
    if not _act.estado()['actualizador']:
        flash('El actualizador de este servidor no está activado (o el servidor es Windows): actualiza a mano con '
              '«sudo bash octopus.sh actualizar» (en Windows: octopus.ps1 actualizar).', 'error')
        return redirect(volver)
    _act.pedir(act.get('remota', ''), session.get('username', '?'))
    log_audit(session['user_id'], 'UPDATE_REQUEST', f'a la versión {act.get("remota")}', request.remote_addr)
    _ban.marcar('actualizacion', f'Actualización a {act.get("remota")} pedida por {session.get("username")}')
    flash(f'Actualización a la versión {act.get("remota")} pedida. En unos minutos se descarga, se comprueba su firma y se '
          f'instala; el panel se reiniciará solo. Si algo va mal, vuelve solo a la versión actual.', 'success')
    return redirect(volver)


@app.route('/ajustes/kit-recuperacion', methods=['POST'])
@login_required
@role_required('supremo', 'admin')
def kit_recuperacion():
    """Descarga el kit con las claves de las copias. Pide la contrasena otra vez y queda registrado."""
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    if not verify_password(request.form.get('password', ''), user['password_hash']):
        log_audit(session['user_id'], 'RECOVERY_KIT_DENIED', 'Contrasena incorrecta', request.remote_addr)
        flash('La contraseña no es correcta.', 'error')
        return redirect(url_for('ajustes'))
    if not _codigo_ok(session['user_id']):
        log_audit(session['user_id'], 'RECOVERY_KIT_DENIED', 'Código de doble autenticación incorrecto', request.remote_addr)
        flash('Falta el código de la app del móvil (o no es correcto).', 'error')
        return redirect(url_for('ajustes') + '#kit')
    import mantenimiento as _mant
    texto = _mant.kit(_mant.leer_env())
    codigo_rec = _dosfa.nuevo_codigo_recuperacion(DB_FILE)
    texto += ("\n\n=== CÓDIGO PARA QUITAR LA DOBLE AUTENTICACIÓN (si se pierde el móvil y los códigos de emergencia) ===\n"
              f"{codigo_rec}\n"
              "Solo sirve en la consola del servidor, como administrador del servidor:  octopus.sh quitar-2fa <usuario>\n"
              "Al usarlo se avisa a todos los administradores. Cada kit nuevo cambia este código: vale el del último kit.\n")
    clave_zip = request.form.get('clave_zip', '')
    if clave_zip:
        if len(clave_zip) < 8:
            flash('La contraseña del kit tiene que tener al menos 8 caracteres.', 'error')
            return redirect(url_for('ajustes') + '#kit')
        import tempfile as _tf
        import shutil as _sh
        if not _sh.which('7z'):
            flash('Este servidor no tiene 7-Zip para cifrar el kit. Descárgalo sin contraseña.', 'error')
            return redirect(url_for('ajustes') + '#kit')
        with _tf.TemporaryDirectory(prefix='octopus_kit_') as tmp:
            txt = os.path.join(tmp, 'OCTOPUS_kit_recuperacion.txt')
            zip_path = os.path.join(tmp, 'kit.zip')
            with open(txt, 'w', encoding='utf-8') as f:
                f.write(texto)
            # 7-Zip: zip con cifrado AES-256 (la contrasena va como argumento solo dentro del contenedor)
            r = subprocess.run(['7z', 'a', '-tzip', '-mem=AES256', f'-p{clave_zip}', '-y', zip_path, txt],
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0 or not os.path.isfile(zip_path):
                flash('No se pudo crear el kit cifrado. Descárgalo sin contraseña.', 'error')
                return redirect(url_for('ajustes') + '#kit')
            with open(zip_path, 'rb') as f:
                datos = f.read()
        log_audit(session['user_id'], 'RECOVERY_KIT', 'Kit de recuperacion descargado (zip cifrado)', request.remote_addr)
        resp = app.response_class(datos, mimetype='application/zip')
        resp.headers['Content-Disposition'] = 'attachment; filename="OCTOPUS_kit_recuperacion.zip"'
        return resp
    log_audit(session['user_id'], 'RECOVERY_KIT', 'Kit de recuperacion descargado', request.remote_addr)
    resp = app.response_class(texto, mimetype='text/plain; charset=utf-8')
    resp.headers['Content-Disposition'] = 'attachment; filename="OCTOPUS_kit_recuperacion.txt"'
    return resp


@app.route('/cuenta/contrasena', methods=['GET', 'POST'])
@login_required
def cambiar_password():
    if request.method == 'POST':
        actual = request.form.get('actual', '')
        nueva = request.form.get('nueva', '')
        repetir = request.form.get('repetir', '')
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        error = None
        if not verify_password(actual, user['password_hash']):
            error = 'La contraseña actual no es correcta.'
        elif nueva != repetir:
            error = 'Las dos contraseñas nuevas no coinciden.'
        elif len(nueva) < MIN_PASSWORD_LEN:
            error = f'La contraseña nueva debe tener al menos {MIN_PASSWORD_LEN} caracteres.'
        elif nueva == actual:
            error = 'La contraseña nueva tiene que ser distinta de la actual.'
        elif user['username'].lower() in nueva.lower() or nueva.lower() in ('password1234', 'contrasena123', '123456789012'):
            error = 'Esa contraseña es demasiado fácil de adivinar.'
        elif not _codigo_ok(user['id']):
            error = 'Falta el código de la app del móvil (o no es correcto).'
        if error:
            conn.close()
            flash(error, 'error')
            return redirect(url_for('cambiar_password'))
        conn.execute('UPDATE users SET password_hash = ?, must_change_password = 0, sesion_gen = COALESCE(sesion_gen, 0) + 1 '
                     'WHERE id = ?', (hash_password(nueva), user['id']))
        conn.commit()
        session['gen'] = conn.execute('SELECT sesion_gen FROM users WHERE id = ?', (user['id'],)).fetchone()[0]
        conn.close()
        session['must_change'] = False
        log_audit(user['id'], 'PASSWORD_CHANGE', 'Contraseña cambiada', request.remote_addr)
        flash('Contraseña cambiada. Guárdala en un sitio seguro.', 'success')
        return redirect(url_for('inicio'))
    return render_template('cambiar_password.html', minimo=MIN_PASSWORD_LEN, obligatorio=session.get('must_change'))


@app.route('/api/trabajos')
@login_required
def api_trabajos():
    jobs = agentes.trabajos_de(limit=20)
    for j in jobs:
        j['inicio'] = _hace(j['inicio'])
        j['fin'] = _hace(j['fin']) if j['fin'] else None
    return jsonify(jobs)


# ========================================
# INCIDENTES (respuesta automatica) y SALA DE ANALISIS (sandbox)
# ========================================
import incidentes as _inc


def _notificar_incidente(tipo, texto):
    try:
        notification_manager.send_alert(alert_type=tipo, details=texto)
    except Exception:
        pass
    try:
        telegram_integration.send_alert(tipo, texto)
    except Exception:
        pass


_inc.init(DB_FILE, notify=_notificar_incidente)


def _cfg_bool(key):
    v = config_manager.get_config(key)
    return bool(v) if v is not None else True


@app.context_processor
def _inyectar_incidentes():
    if 'user_id' not in session:
        return {}
    try:
        return {'incidentes_abiertos': _inc.abiertos()}
    except Exception:
        return {'incidentes_abiertos': 0}


import ordenes as _ordenes
# primero las tablas del panel: en una instalacion nueva, ordenes.init anade columnas a «systems» y tiene que existir ya
init_db()
_ordenes.init(DB_FILE)
_seg.init(DB_FILE)
_mon.init(DB_FILE)
import dosfa as _dosfa_ini
_dosfa_ini.init(DB_FILE)


def _agente_autenticado():
    """Cada agente se identifica con su nombre y su propia clave (cabeceras X-Octopus-Equipo / X-Octopus-Token)."""
    equipo = (request.headers.get('X-Octopus-Equipo') or '')[:64]
    token = request.headers.get('X-Octopus-Token', '')
    row = _ordenes.autenticar(equipo, token)
    if not row:
        log_audit(None, 'AGENT_REJECTED', f'equipo={equipo}', request.remote_addr)
    return row


@app.route('/api/agente/ordenes', methods=['POST'])
@limiter.exempt
def api_agente_ordenes():
    """El agente pregunta si hay ordenes para el (cada pocos segundos) y cuenta como esta."""
    row = _agente_autenticado()
    if not row:
        return jsonify({'error': 'no autorizado'}), 401
    info = request.get_json(silent=True) or {}
    _ordenes.latido(row, request.remote_addr, str(info.get('version', ''))[:20])
    if info.get('info'):
        try:
            with get_db_connection() as c:
                c.execute('UPDATE systems SET agent_info = ? WHERE id = ?', (json.dumps(info['info'])[:20000], row['id']))
        except sqlite3.Error:
            pass
    mon_activa = _fun.activa('monitorizacion') and _mon.activa(row['id'])
    return jsonify({'ordenes': _ordenes.pendientes(row['hostname']), 'espera': _ordenes.INTERVALO_AGENTE,
                    'ajustes': _ajustes_agente(row),
                    # al momento: si se activa la monitorización o alguien abre su pantalla, el agente lo sabe ya
                    'monitor': {'activa': mon_activa, 'intervalo': _mon.intervalo(row['id']) if mon_activa else 300}})


@app.route('/api/agente/ajustes', methods=['POST'])
@limiter.exempt
def api_agente_ajustes():
    """Ajustes para la copia diaria programada (que corre como proceso aparte del agente)."""
    row = _agente_autenticado()
    if not row:
        return jsonify({'error': 'no autorizado'}), 401
    return jsonify({'ajustes': _ajustes_agente(row)})


@app.route('/api/agente/resultado', methods=['POST'])
@limiter.exempt
def api_agente_resultado():
    row = _agente_autenticado()
    if not row:
        return jsonify({'error': 'no autorizado'}), 401
    data = request.get_json(silent=True) or {}
    ok = _ordenes.resultado(row['hostname'], str(data.get('id', '')), data.get('resultado') or {})
    return jsonify({'ok': ok})


def _dias_aprendiendo(system):
    """Días que le quedan al equipo en su periodo de aprendizaje (None si ya acabó o está apagado)."""
    if not _fun.activa('periodo_prueba'):
        return None
    try:
        alta = agentes.parse_time(system['created_at'])
    except (KeyError, IndexError, TypeError):
        return None
    if not alta:
        return None
    if alta.tzinfo is None:
        alta = alta.replace(tzinfo=timezone.utc)
    quedan = int(_fun.opcion('periodo_prueba', 'dias')) - (datetime.now(timezone.utc) - alta).days
    return quedan if quedan > 0 else None


@app.route('/api/agente/alerta', methods=['POST'])
@limiter.exempt
def api_agente_alerta():
    """El agente de un equipo avisa de un ataque (autenticado con la clave propia del equipo)."""
    system = _agente_autenticado()
    if not system:
        return jsonify({'error': 'no autorizado'}), 401
    data = request.get_json(silent=True) or {}
    host = system['hostname']
    origen_ip = request.remote_addr
    motivo = str(data.get('motivo', 'Ataque detectado'))[:500]
    senuelo = 'señuelo' in motivo.lower() or 'senuelo' in motivo.lower()
    auto, severidad = _cfg_bool('incident_auto_response'), data.get('severidad', 'critica')
    dias = _dias_aprendiendo(system)
    if dias is not None and not senuelo:
        # equipo nuevo: la deteccion aun no sabe lo que es normal en el. Aviso amarillo, sin aislar (un señuelo si actua)
        auto, severidad = False, 'aviso'
        motivo = (f'{motivo} — equipo en periodo de aprendizaje (quedan {dias} días): no se ha aislado. '
                  f'Revísalo y pulsa «Responder» si es un ataque de verdad.')[:600]
    inc_id, nuevo = _inc.crear(
        system, motivo, data.get('evidencias', [])[:100],
        detectado=data.get('detectado'), origen='detector del agente', severidad=severidad,
        auto=auto, mantener_aislado=_cfg_bool('incident_keep_isolated'),
        contacto=config_manager.get_config('security_contact') or 'el departamento de seguridad')
    log_audit(None, 'INCIDENT_CREATED' if nuevo else 'INCIDENT_REPEAT', f'#{inc_id} {host}: {data.get("motivo", "")}'[:300], origen_ip)
    _ban.marcar('incidentes', f'Alerta del equipo: {data.get("motivo", "")} (incidente #{inc_id})', equipo=host,
                codigo='OCT-SEN-01' if senuelo else None, nivel='aviso' if severidad == 'aviso' else 'error')
    return jsonify({'incidente': inc_id, 'nuevo': nuevo})


@app.route('/api/agente/metricas', methods=['POST'])
@limiter.exempt
def api_agente_metricas():
    """El agente manda lo que mide (solo si la monitorización está activada para ese equipo)."""
    row = _agente_autenticado()
    if not row:
        return jsonify({'error': 'no autorizado'}), 401
    if not _fun.activa('monitorizacion'):
        return jsonify({'activa': False, 'intervalo': 600})
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'datos no validos'}), 400
    return jsonify(_mon.recibir(row['id'], data))


# ------------------------------------------------------------------ Monitorización
def _monitorizables():
    with get_db_connection() as c:
        return c.execute('SELECT id, hostname, os_family FROM systems ORDER BY hostname').fetchall()


@app.route('/monitorizacion')
@login_required
def monitorizacion():
    if not _fun.activa('monitorizacion'):
        return render_template('monitorizacion.html', apagada=True, equipos=[], sin=[], pausados=[], avisos=[])
    est = _mon.estados()
    equipos = _monitorizables()
    return render_template('monitorizacion.html', apagada=False,
                           equipos=[e for e in equipos if est.get(e['id']) == 'activa'],
                           pausados=[e for e in equipos if est.get(e['id']) == 'pausada'],
                           sin=[e for e in equipos if e['id'] not in est], avisos=_mon.avisos())


@app.route('/monitorizacion/activar', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def monitorizacion_activar():
    """Activar (instala y empieza), Desactivar (pausa: deja de recoger, guarda el historial) o Desinstalar (borra todo)."""
    sid = request.form.get('system_id', type=int)
    accion = request.form.get('accion') or {'1': 'activar', '0': 'pausar'}.get(request.form.get('activar', ''), '')
    row = _get_system(sid) if sid else None
    destino_error = request.form.get('volver_error', '') or request.form.get('volver', '')
    destino_error = destino_error if destino_error.startswith('/') and not destino_error.startswith('//') else url_for('monitorizacion')
    if not row or accion not in ('activar', 'pausar', 'desinstalar'):
        flash('Elige un equipo.', 'error')
        return redirect(url_for('monitorizacion'))
    antes = _mon.estado(sid)
    quien = session.get('username', '')
    if accion == 'activar':
        if antes == 'desinstalada' and request.form.get('informado') != 'on':
            flash('Marca la casilla «He informado a quien usa este equipo» (o que nadie lo usa). Lo pide la ley de '
                  'protección de datos: tienes la nota para el trabajador en «Legal y privacidad».', 'error')
            return redirect(destino_error)
        _mon.activar(sid, True, quien)
        log_audit(session['user_id'], 'MONITOR_ON', row['hostname'] + (
            ' (instalada; confirma que ha informado a quien lo usa)' if antes == 'desinstalada' else ' (reanudada)'),
            request.remote_addr)
        flash(f'Monitorización {"instalada y activada" if antes == "desinstalada" else "activada otra vez"} en '
              f'{row["hostname"]}. Los primeros datos llegan en menos de un minuto.', 'success')
    elif accion == 'pausar':
        _mon.activar(sid, False, quien)
        log_audit(session['user_id'], 'MONITOR_PAUSA', row['hostname'], request.remote_addr)
        flash(f'Monitorización en pausa en {row["hostname"]}: ya no se recogen datos. El historial se guarda; '
              f'puedes activarla otra vez o desinstalarla.', 'success')
    else:
        if (request.form.get('confirmar') or '').strip().lower() != (row['hostname'] or '').lower():
            flash(f'Para desinstalar escribe el nombre del equipo ({row["hostname"]}) en la casilla. Así no se hace sin querer.', 'error')
            return redirect(destino_error)
        _mon.desinstalar(sid)
        log_audit(session['user_id'], 'MONITOR_DESINSTALADA', f'{row["hostname"]}: quitada y borrado su historial',
                  request.remote_addr)
        flash(f'Monitorización desinstalada de {row["hostname"]} y borrado todo su historial.', 'success')
    destino = request.form.get('volver', '')
    return redirect(destino if destino.startswith('/') and not destino.startswith('//') else
                    url_for('monitorizacion_equipo', system_id=sid) if accion == 'activar' else url_for('monitorizacion'))


@app.route('/monitorizacion/funcion', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def monitorizacion_funcion():
    """Encender o apagar la monitorización entera (lo mismo que en Ajustes → Funciones)."""
    si = request.form.get('encender') == '1'
    if not _guardar_protegido('monitorizacion', si, session['user_id']):
        return redirect(url_for('monitorizacion'))
    log_audit(session['user_id'], 'FUNCION_ON' if si else 'FUNCION_OFF', 'monitorizacion', request.remote_addr)
    flash('Monitorización encendida: ahora actívala en los equipos que quieras.' if si else
          'Monitorización apagada: ningún equipo recoge datos (el historial se guarda).', 'success')
    return redirect(url_for('monitorizacion') if si else url_for('inicio'))


@app.route('/monitorizacion/<int:system_id>')
@login_required
def monitorizacion_equipo(system_id):
    row = _get_system(system_id)
    if not row or not _fun.activa('monitorizacion'):
        return redirect(url_for('monitorizacion'))
    if not _mon.activa(system_id):
        flash(f'La monitorización no está activada en {row["hostname"]}.', 'info')
        return redirect(url_for('equipo', system_id=system_id))
    _mon.mirar(system_id)
    return render_template('monitor_equipo.html', s=row)


@app.route('/api/monitor/<int:system_id>')
@login_required
def api_monitor(system_id):
    """Lo último que ha mandado el equipo (y, si se pide, el historial). Mirar esto pone el equipo «en vivo»."""
    if not _fun.activa('monitorizacion') or not _mon.activa(system_id):
        return jsonify({'error': 'no activa'}), 404
    _mon.mirar(system_id)
    d = _mon.ultimo(system_id) or {}
    out = {'datos': d, 'ahora': datetime.now().timestamp(),
           'avisos': [_aviso(a['codigo'], None, system_id, None, detalle=a['detalle']) for a in _mon.avisos(system_id)]}
    if request.args.get('horas'):
        out['historial'] = _mon.historial(system_id, min(24 * 90, max(0.25, request.args.get('horas', type=float) or 1)))
    return jsonify(out)


@app.route('/api/monitor/resumen')
@login_required
def api_monitor_resumen():
    """Unos pocos números de cada equipo monitorizado, para la lista."""
    if not _fun.activa('monitorizacion'):
        return jsonify({})
    res = {}
    for sid in _mon.activos():
        d = _mon.ultimo(sid) or {}
        res[sid] = {'recibido': d.get('recibido'), **_mon._resumen(d),
                    'salud': min((x.get('estado') for x in (d.get('lento') or {}).get('discos_salud') or []),
                                 key=lambda e: {'mal': 0, 'atencion': 1, 'ok': 2}.get(e, 3), default=None),
                    'avisos': len(_mon.avisos(sid))}
    return jsonify({'equipos': res, 'ahora': datetime.now().timestamp()})


@app.route('/equipos/<int:system_id>/incidente', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def declarar_incidente(system_id):
    row = _get_system(system_id)
    if not row:
        return redirect(url_for('equipos'))
    motivo = (request.form.get('motivo') or 'Declarado manualmente desde el panel').strip()[:300]
    inc_id, _ = _inc.crear(row, motivo, [], origen=f'manual ({session.get("username")})',
                           auto=True, mantener_aislado=_cfg_bool('incident_keep_isolated'),
                           contacto=config_manager.get_config('security_contact') or 'el departamento de seguridad')
    log_audit(session['user_id'], 'INCIDENT_MANUAL', f'#{inc_id} {row["hostname"]}: {motivo}', request.remote_addr)
    flash(f'Incidente #{inc_id} abierto. El equipo se está aislando, copiando y restaurando.', 'success')
    return redirect(url_for('incidente', inc_id=inc_id))


@app.route('/incidentes')
@login_required
def incidentes():
    return render_template('incidentes.html', lista=_inc.listar())


@app.route('/incidentes/<int:inc_id>')
@login_required
def incidente(inc_id):
    inc = _inc.obtener(inc_id)
    if not inc:
        flash('Ese incidente no existe.', 'error')
        return redirect(url_for('incidentes'))
    return render_template('incidente.html', inc=inc, sala=_inc.sala_preparada(inc_id),
                           archivos=_inc.indice(inc_id)[:500] if _inc.sala_preparada(inc_id) else [])


@app.route('/incidentes/<int:inc_id>/accion', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def incidente_accion(inc_id):
    accion = request.form.get('accion')
    inc = _inc.obtener(inc_id)
    if not inc:
        return redirect(url_for('incidentes'))
    if accion == 'liberar':
        ok, msg = _inc.liberar(inc_id, cerrar=True, notas=request.form.get('notas', '')[:1000])
        flash('Equipo reincorporado a la red e incidente cerrado.' if ok else f'No se pudo liberar: {msg}', 'success' if ok else 'error')
    elif accion == 'responder':
        import threading as _th
        _th.Thread(target=_inc.responder, args=(inc_id, _cfg_bool('incident_keep_isolated'),
                   config_manager.get_config('security_contact') or 'el departamento de seguridad'), daemon=True).start()
        flash('Respuesta en marcha.', 'success')
    elif accion == 'preparar_sala':
        ok, msg = _inc.preparar_sala(inc_id)
        flash(f'Sala de análisis lista: {msg}' if ok else f'No se pudo preparar la sala: {msg}', 'success' if ok else 'error')
    elif accion == 'borrar_sala':
        _inc.borrar_sala(inc_id)
        flash('Sala de análisis eliminada del servidor.', 'success')
    elif accion == 'eliminar_amenaza':
        ruta = request.form.get('ruta_sala')
        rutas = [_inc.ruta_en_equipo(inc_id, ruta)] if ruta else None
        ok, msg = _inc.eliminar_amenaza(inc_id, rutas)
        flash(f'Amenaza eliminada del equipo: {msg}.' if ok else f'No se pudo eliminar: {msg}', 'success' if ok else 'error')
        if ruta:
            log_audit(session['user_id'], 'INCIDENT_ELIMINAR_AMENAZA', f'#{inc_id} {ruta}', request.remote_addr)
            return redirect(url_for('sala', inc_id=inc_id, archivo=ruta) + '#detalle')
    elif accion == 'destruir_forense':
        ok, msg = _inc.destruir_forense(inc_id)
        flash(msg + '.' if ok else f'No se pudo destruir: {msg}', 'success' if ok else 'error')
    log_audit(session['user_id'], f'INCIDENT_{str(accion).upper()}', f'#{inc_id}', request.remote_addr)
    return redirect(url_for('incidente', inc_id=inc_id))


@app.route('/incidentes/<int:inc_id>/sala')
@login_required
@role_required('admin', 'supremo')
def sala(inc_id):
    inc = _inc.obtener(inc_id)
    if not inc or not _inc.sala_preparada(inc_id):
        flash('Primero prepara la sala de análisis.', 'error')
        return redirect(url_for('incidente', inc_id=inc_id))
    detalle, error = None, None
    ruta = request.args.get('archivo')
    if ruta:
        try:
            detalle = _inc.ver_archivo(inc_id, ruta)
        except (ValueError, OSError) as e:
            error = str(e)
    return render_template('sala.html', inc=inc, archivos=_inc.indice(inc_id), detalle=detalle, error=error,
                           terminal=_cfg_bool('sandbox_terminal'), salida=session.pop(f'sala_out_{inc_id}', None))


@app.route('/incidentes/<int:inc_id>/sala/ejecutar', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def sala_ejecutar(inc_id):
    if not _cfg_bool('sandbox_terminal'):
        flash('El terminal de la sala está desactivado en Ajustes.', 'error')
        return redirect(url_for('sala', inc_id=inc_id))
    comando = (request.form.get('comando') or '').strip()[:1000]
    if comando:
        code, out = _inc.ejecutar(inc_id, comando)
        log_audit(session['user_id'], 'SANDBOX_EXEC', f'#{inc_id}: {comando}'[:300], request.remote_addr)
        session[f'sala_out_{inc_id}'] = {'comando': comando, 'codigo': code, 'salida': out[-8000:]}
    return redirect(url_for('sala', inc_id=inc_id) + '#terminal')


@app.route('/incidentes/<int:inc_id>/descargar', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def incidente_descargar(inc_id):
    from flask import send_file
    path, clave = _inc.paquete(inc_id)
    if not path:
        flash(f'No se pudo generar el paquete: {clave}', 'error')
        return redirect(url_for('incidente', inc_id=inc_id))
    log_audit(session['user_id'], 'FORENSIC_DOWNLOAD', f'#{inc_id}', request.remote_addr)
    return send_file(path, as_attachment=True, download_name=os.path.basename(path), mimetype='application/x-7z-compressed')


LIMITES_COPIA = [(0, 'Sin límite'), (256, 'Suave: 256 KB/s (~2 Mbit/s)'), (1024, 'Medio: 1 MB/s (~8 Mbit/s)'),
                 (5120, 'Alto: 5 MB/s (~40 Mbit/s)'), (12800, 'Muy alto: 12,5 MB/s (~100 Mbit/s)')]


def _ajustes_copias():
    """Ajustes que el servidor manda a los agentes en cada consulta (sin reinstalar nada)."""
    try:
        kbps = int(config_manager.get_config('copias_limite_kbps') or 0)
    except (TypeError, ValueError):
        kbps = 0
    return {'limite_kbps': max(kbps, 0), 'solo_horario': bool(config_manager.get_config('copias_limite_solo_horario')),
            'informe_mensual': bool(config_manager.get_config('informe_mensual')),
            'retencion': str(config_manager.get_config('backup_retention') or 'daily_30')}


app.jinja_env.globals['LIMITES_COPIA'] = LIMITES_COPIA
RETENCIONES = [('daily_7', 'Menos espacio: la última semana día a día, 4 semanas y 6 meses'),
               ('daily_30', 'Lo normal: el último mes día a día, 8 semanas y 1 año (recomendado)'),
               ('daily_90', 'Más historial: 3 meses día a día, medio año por semanas y 2 años')]
app.jinja_env.globals['RETENCIONES'] = RETENCIONES


@app.route('/informe')
@login_required
def informe():
    """Informe mensual listo para imprimir o guardar en PDF (Ctrl+P)."""
    import informe as _informe
    mes = request.args.get('mes') or datetime.now().strftime('%Y-%m')
    if not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])', mes):
        mes = datetime.now().strftime('%Y-%m')
    hoy = datetime.now()
    meses = [f'{hoy.year - (hoy.month - i <= 0)}-{(hoy.month - i - 1) % 12 + 1:02d}' for i in range(12)]
    return render_template('informe.html', d=_informe.datos(mes), meses=meses, nombre_mes=_informe.nombre_mes)


# ------------------------------------------------------------------ copia de la nube (Microsoft 365 / Google)
import copia_nube as _nube
_NUBE_JOBS = {}      # un único trabajo de servidor en marcha (clave 'nube')


def _nube_config():
    """La configuración de la nube (con las credenciales descifradas). {} si no hay nada."""
    cif = config_manager.get_config('nube_cifrada')
    if not cif:
        return {}
    try:
        return json.loads(_dosfa.descifrar(DB_FILE, cif))
    except Exception:
        return {}


def _nube_guardar(cfg):
    config_manager.set_config('nube_cifrada', _dosfa.cifrar(DB_FILE, json.dumps(cfg)) if cfg else '', session['user_id'])


@app.route('/ajustes/nube')
@login_required
@role_required('admin', 'supremo')
def ajustes_nube():
    ok = _fun.activa('copia_nube')
    cfg = _nube_config()
    import mantenimiento as _mant
    copias = _nube.copias(_mant.leer_env()) if ok and cfg else []
    estado = _NUBE_JOBS.get('nube')
    return render_template('nube.html', ok=ok, tiene_ms=bool(cfg.get('microsoft')), tiene_google=bool(cfg.get('google')),
                           ms=cfg.get('microsoft', {}), google_usuarios=', '.join((cfg.get('google') or {}).get('usuarios', [])),
                           activa=bool(config_manager.get_config('nube_activa')),
                           dias=config_manager.get_config('nube_dias') or 1, copias=copias, estado=estado)


def _nube_lanzar(solo=None):
    import mantenimiento as _mant
    env = _mant.leer_env()
    cfg = _nube_config()
    _NUBE_JOBS['nube'] = {'estado': 'en_curso', 'mensaje': 'Copiando la nube...', 'inicio': datetime.now(timezone.utc)}

    def _run():
        try:
            r = _nube.copiar(env, cfg, solo)
            _NUBE_JOBS['nube'] = {'estado': 'ok' if r.get('status') in ('success', 'parcial') else 'error',
                                  'mensaje': '; '.join(r.get('pasos', [])[-4:]) or r.get('message', ''),
                                  'fin': datetime.now(timezone.utc), 'aviso': r.get('aviso')}
            _ban.marcar('copias', f"Copia de la nube: {r.get('status')}",
                        nivel='ok' if r.get('status') != 'error' else 'error')
        except Exception as exc:
            _NUBE_JOBS['nube'] = {'estado': 'error', 'mensaje': str(exc), 'fin': datetime.now(timezone.utc)}

    threading.Thread(target=_run, daemon=True).start()


@app.route('/ajustes/nube', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def ajustes_nube_accion():
    if not _fun.activa('copia_nube'):
        flash('Enciende antes «Copia de Microsoft 365 y Google» en Ajustes → Funciones.', 'error')
        return redirect(url_for('ajustes_nube'))
    accion = request.form.get('accion')
    cfg = _nube_config()
    if accion == 'microsoft':
        tenant = (request.form.get('tenant') or '').strip()
        cid = (request.form.get('client_id') or '').strip()
        secreto = request.form.get('client_secret') or ''
        if request.form.get('borrar'):
            cfg.pop('microsoft', None)
            _nube_guardar(cfg)
            flash('Conexión con Microsoft 365 borrada.', 'success')
        elif tenant and cid:
            ms = cfg.get('microsoft', {})
            ms.update(tenant=tenant, client_id=cid)
            if secreto:
                ms['client_secret'] = secreto
            if not ms.get('client_secret'):
                flash('Falta el «secreto» de la aplicación.', 'error')
                return redirect(url_for('ajustes_nube'))
            cfg['microsoft'] = ms
            _nube_guardar(cfg)
            flash('Microsoft 365 conectado (cifrado). Pulsa «Copiar ahora» para la primera copia.', 'success')
        else:
            flash('Faltan datos de Microsoft 365.', 'error')
    elif accion == 'google':
        usuarios = [u.strip() for u in (request.form.get('usuarios') or '').replace('\n', ',').split(',') if u.strip()]
        sa = request.form.get('cuenta_servicio') or ''
        if request.form.get('borrar'):
            cfg.pop('google', None)
            _nube_guardar(cfg)
            flash('Conexión con Google borrada.', 'success')
        else:
            g = cfg.get('google', {})
            if sa.strip():
                try:
                    json.loads(sa)
                except ValueError:
                    flash('El archivo de la cuenta de servicio no es un JSON válido.', 'error')
                    return redirect(url_for('ajustes_nube'))
                g['cuenta_servicio'] = sa
            if usuarios:
                g['usuarios'] = usuarios
            if not g.get('cuenta_servicio') or not g.get('usuarios'):
                flash('Pega el archivo de la cuenta de servicio y escribe al menos un usuario.', 'error')
                return redirect(url_for('ajustes_nube'))
            cfg['google'] = g
            _nube_guardar(cfg)
            flash('Google conectado (cifrado). Pulsa «Copiar ahora» para la primera copia.', 'success')
    elif accion == 'programa':
        config_manager.set_config('nube_activa', request.form.get('activa') == 'on', session['user_id'])
        config_manager.set_config('nube_dias', 7 if request.form.get('dias') == '7' else 1, session['user_id'])
        flash('Guardado.', 'success')
    elif accion == 'ahora':
        if not cfg:
            flash('Conecta antes Microsoft 365 o Google.', 'error')
        elif _NUBE_JOBS.get('nube', {}).get('estado') == 'en_curso':
            flash('Ya hay una copia de la nube en marcha.', 'info')
        else:
            _nube_lanzar()
            log_audit(session['user_id'], 'NUBE_BACKUP_START', 'copia de la nube', request.remote_addr)
            flash('Copia de la nube en marcha. Recarga la página en un rato para ver cómo va.', 'success')
    elif accion == 'restaurar':
        snap = request.form.get('snapshot', '')
        import re as _re_n
        if not _re_n.fullmatch(r'[0-9a-fA-F]{6,64}', snap):
            flash('Copia no válida.', 'error')
        else:
            import mantenimiento as _mant
            r = _nube.restaurar(_mant.leer_env(), snap)
            log_audit(session['user_id'], 'NUBE_RESTORE', f'copia={snap}', request.remote_addr)
            flash((f'Recuperado en el servidor: {r.get("carpeta")} ({r.get("archivos")} archivos). '
                   + r.get('instrucciones', '')) if r.get('status') == 'success'
                  else 'No se pudo recuperar: ' + r.get('message', ''), 'success' if r.get('status') == 'success' else 'error')
    return redirect(url_for('ajustes_nube'))


@app.route('/ajustes/copias', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def ajustes_copias():
    uid = session['user_id']
    try:
        kbps = int(request.form.get('limite_kbps', '0'))
    except ValueError:
        kbps = 0
    if kbps not in [k for k, _ in LIMITES_COPIA]:
        kbps = 0
    config_manager.set_config('copias_limite_kbps', kbps, uid)
    config_manager.set_config('copias_limite_solo_horario', request.form.get('solo_horario') == 'on', uid)
    config_manager.set_config('informe_mensual', request.form.get('informe') == 'on', uid)
    import mantenimiento as _mant
    ret = request.form.get('retencion', '')
    if ret in _mant.POLITICAS:
        _guardar_protegido('backup_retention', ret, uid)
    log_audit(uid, 'CONFIG_BACKUP_SPEED', f'limite={kbps} KB/s solo_horario={request.form.get("solo_horario") == "on"} '
                                          f'retencion={ret or "sin cambios"}',
              request.remote_addr)
    flash('Guardado. Los equipos lo aplican en su próxima copia.', 'success')
    return redirect(url_for('ajustes'))


@app.route('/ajustes/incidentes', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def ajustes_incidentes():
    uid = session['user_id']
    _guardar_protegido('incident_auto_response', request.form.get('auto') == 'on', uid)
    _guardar_protegido('incident_keep_isolated', request.form.get('aislado') == 'on', uid)
    config_manager.set_config('sandbox_terminal', request.form.get('terminal') == 'on', uid)
    _guardar_protegido('senuelos', request.form.get('senuelos') == 'on', uid)
    config_manager.set_config('autoarreglo', request.form.get('autoarreglo') == 'on', uid)
    contacto = (request.form.get('contacto') or '').strip()[:200] or 'el departamento de seguridad'
    config_manager.set_config('security_contact', contacto, uid)
    log_audit(uid, 'CONFIG_INCIDENTS', 'Ajustes de respuesta a ataques', request.remote_addr)
    flash('Ajustes de respuesta a ataques guardados.', 'success')
    return redirect(url_for('ajustes'))


# ------------------------------------------------------------------ Ajustes -> Funciones (todo lo configurable)
import funciones as _fun
_fun.usar(config_manager)
app.jinja_env.globals['funcion_activa'] = _fun.activa
app.jinja_env.globals['para_equipo'] = _fun.para_equipo


@app.route('/equipos/<int:system_id>/levantar/<que>')
@login_required
@role_required('admin', 'supremo')
def levantar(system_id, que):
    """USB de rescate, imagen de disco o arranque por red de un equipo (funciones en pruebas)."""
    row = _get_system(system_id)
    if not row or que not in ('usb_rescate', 'imagen_disco', 'arranque_red'):
        return redirect(url_for('equipos'))
    ok, motivo = _fun.para_equipo(que, row['os_family'])
    if not ok:
        flash(motivo, 'error')
        return redirect(url_for('equipo', system_id=system_id))
    f = next(x for x in _fun.FUNCIONES if x['clave'] == que)
    return render_template('levantar.html', s=row, f=f)


def _funciones_vista():
    """Las funciones por grupos, con su estado, para la pantalla (en modo básico no salen las de experto)."""
    experto = modo_experto()
    aceptadas = set(config_manager.get_config('funciones_en_pruebas_aceptadas') or [])
    grupos = []
    for g, titulo, explica in _fun.GRUPOS:
        filas = []
        for f in _fun.FUNCIONES:
            if f['grupo'] != g or (f['nivel'] == 'experto' and not experto):
                continue
            ok, motivo = _fun.disponible(f['clave'])
            valor = config_manager.get_config(f['clave'])
            opciones = []
            for (k, nombre, tipo, defecto, nivel, ayuda, extra) in f.get('opciones', []):
                if nivel == 'experto' and not experto:
                    continue
                v = config_manager.get_config(f"{f['clave']}.{k}")
                opciones.append({'k': k, 'nombre': nombre, 'tipo': tipo, 'ayuda': ayuda, 'extra': extra,
                                 'valor': '' if tipo == 'secreto' else (defecto if v is None else v),
                                 'tiene_secreto': tipo == 'secreto' and bool(v)})
            filas.append({**{k: f.get(k) for k in ('clave', 'nombre', 'explica', 'nivel', 'requiere')},
                          'en_pruebas': bool(f.get('en_pruebas')), 'aceptada': f['clave'] in aceptadas,
                          'encendida': bool(valor), 'disponible': ok, 'motivo': motivo, 'opciones': opciones,
                          'no_mac': bool(f.get('no_mac'))})
        if filas:
            grupos.append({'clave': g, 'titulo': titulo, 'explica': explica, 'filas': filas})
    return grupos


# ---- doble aprobación: lo peligroso lo aprueba otro administrador (si la función está encendida)
_PROTEGIDOS_AL_APAGAR = {'dosfa', 'senuelos', 'incident_auto_response', 'incident_keep_isolated', 'aviso_acceso_nuevo',
                         'bloqueo_atacantes', 'panel_solo_redes', 'doble_aprobacion', 'email_notifications',
                         'telegram_enabled'}
_PROTEGIDOS_SIEMPRE = {'backup_retention'}
_NOMBRES_PROTEGIDOS = {'email_notifications': 'Avisos por correo', 'telegram_enabled': 'Avisos por Telegram',
                       'backup_retention': 'Cuántas copias se guardan',
                       **{f['clave']: f['nombre'] for f in _fun.FUNCIONES}}


def _pedir_aprobacion(accion, datos, resumen):
    """Si hace falta doble aprobación, deja la petición pendiente, avisa y devuelve True (no hacer nada aún)."""
    if not _fun.activa('doble_aprobacion'):
        return False
    with get_db_connection() as c:
        otros = c.execute("SELECT COUNT(*) FROM users WHERE role IN ('admin','supremo') AND id != ?",
                          (session['user_id'],)).fetchone()[0]
    if not otros:   # no hay nadie más que pueda aprobar: no se bloquea al único administrador
        return False
    aid = _seg.pedir(DB_FILE, accion, datos, resumen, session['user_id'], session.get('username', '?'),
                     int(_fun.opcion('doble_aprobacion', 'horas')))
    log_audit(session['user_id'], 'APROBACION_PEDIDA', f'#{aid}: {resumen}', request.remote_addr)
    _notificar_incidente('acceso', f'OCTOPUS: {session.get("username")} pide aprobar «{resumen}». Lo tiene que aprobar '
                                   f'otro administrador en Ajustes → Pendiente de aprobar.')
    flash(f'«{resumen}» necesita que lo apruebe otro administrador. Queda pendiente en Ajustes → Pendiente de aprobar.',
          'info')
    return True


def _guardar_protegido(clave, valor, uid):
    """Guarda un ajuste; si apagarlo (o cambiarlo) es peligroso y hay doble aprobación, lo deja pendiente."""
    actual = config_manager.get_config(clave)
    peligroso = (clave in _PROTEGIDOS_SIEMPRE and valor != actual) or \
                (clave in _PROTEGIDOS_AL_APAGAR and bool(actual) and not valor)
    if peligroso and _pedir_aprobacion('ajuste', {'clave': clave, 'valor': valor},
                                       f'{"Cambiar" if clave in _PROTEGIDOS_SIEMPRE else "Apagar"} '
                                       f'«{_NOMBRES_PROTEGIDOS.get(clave, clave)}»'
                                       + (f' a «{valor}»' if clave in _PROTEGIDOS_SIEMPRE else '')):
        return False
    config_manager.set_config(clave, valor, uid)
    return True


def _ejecutar_aprobada(p, uid):
    """Hace lo que se aprobó. Devuelve el texto para el mensaje."""
    if p['accion'] == 'ajuste':
        config_manager.set_config(p['datos']['clave'], p['datos']['valor'], uid)
        return 'hecho'
    if p['accion'] == 'borrar_usuario':
        with get_db_connection() as c:
            u = c.execute('SELECT role FROM users WHERE id = ?', (p['datos']['id'],)).fetchone()
        if not u:
            return 'ese usuario ya no existía'
        if u['role'] in ('admin', 'supremo') and not _admins_restantes(p['datos']['id']):
            return 'no se ha borrado: tiene que quedar al menos un administrador'
        _borrar_usuario(p['datos']['id'])
        return 'usuario borrado'
    if p['accion'] == 'borrar_equipo':
        with get_db_connection() as c:
            c.execute('DELETE FROM systems WHERE id = ?', (p['datos']['id'],))
        return 'equipo quitado del panel (sus copias siguen guardadas)'
    return 'acción desconocida: no se ha hecho nada'


@app.route('/aprobaciones/<int:aid>', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def decidir_aprobacion(aid):
    aprobar = request.form.get('decision') == 'aprobar'
    p, motivo = _seg.decidir(DB_FILE, aid, session['user_id'], session.get('username', '?'), aprobar)
    if not p:
        flash(motivo, 'error')
        return redirect(url_for('ajustes') + '#aprobaciones')
    if aprobar:
        resultado = _ejecutar_aprobada(p, session['user_id'])
        log_audit(session['user_id'], 'APROBACION_OK', f'#{aid}: {p["resumen"]} (pedido por {p["pedido_nombre"]}): '
                                                       f'{resultado}', request.remote_addr)
        flash(f'Aprobado: «{p["resumen"]}» — {resultado}.', 'success')
    else:
        log_audit(session['user_id'], 'APROBACION_NO', f'#{aid}: {p["resumen"]} (pedido por {p["pedido_nombre"]})',
                  request.remote_addr)
        flash(f'Rechazado: «{p["resumen"]}».', 'success')
    return redirect(url_for('ajustes') + '#aprobaciones')


@app.route('/ajustes/bloqueos/quitar', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def quitar_bloqueo():
    ip = (request.form.get('ip') or '').strip()[:64] or None
    n = _seg.desbloquear(DB_FILE, ip)
    log_audit(session['user_id'], 'IP_DESBLOQUEADA', ip or f'todas ({n})', request.remote_addr)
    flash(f'Desbloqueada{"s" if not ip else ""} {ip or f"{n} direcciones"}.', 'success')
    return redirect(url_for('ajustes_funciones') + '#bloqueo_atacantes')


@app.route('/ajustes/funciones', methods=['GET', 'POST'])
@login_required
def ajustes_funciones():
    if request.method == 'GET':
        return render_template('funciones.html', grupos=_funciones_vista(), mi_ip=request.remote_addr,
                               bloqueadas=_seg.lista_bloqueadas(DB_FILE) if modo_experto() else [],
                               nombres={f['clave']: f['nombre'] for f in _fun.FUNCIONES})
    if not puede_actuar():
        flash('Solo un administrador puede cambiar las funciones.', 'error')
        return redirect(url_for('ajustes_funciones'))
    uid, experto = session['user_id'], modo_experto()
    clave = request.form.get('clave', '')
    f = next((x for x in _fun.FUNCIONES if x['clave'] == clave), None)
    if not f or (f['nivel'] == 'experto' and not experto):
        flash('Esa función no existe o necesita el modo experto.', 'error')
        return redirect(url_for('ajustes_funciones'))
    volver = url_for('ajustes_funciones') + '#' + clave
    errores, cambios = [], []
    encender = request.form.get('encendida') == 'on'
    if encender and not config_manager.get_config(clave):
        ok, motivo = _fun.disponible(clave)
        if not ok:
            flash(motivo, 'error')
            return redirect(volver)
        if f.get('en_pruebas'):
            if not experto or request.form.get('acepto_pruebas') != 'on':
                flash(f'«{f["nombre"]}» está en pruebas: para encenderla marca «Sé que está en pruebas».', 'error')
                return redirect(volver)
            aceptadas = list(config_manager.get_config('funciones_en_pruebas_aceptadas') or [])
            if clave not in aceptadas:
                config_manager.set_config('funciones_en_pruebas_aceptadas', aceptadas + [clave], uid)
        if f.get('requiere') and not config_manager.get_config(f['requiere']):
            nombre = next(x['nombre'] for x in _fun.FUNCIONES if x['clave'] == f['requiere'])
            flash(f'Para «{f["nombre"]}» hace falta encender antes «{nombre}».', 'error')
            return redirect(volver)
    nuevos = {}
    for (k, nombre, tipo, defecto, nivel, ayuda, extra) in f.get('opciones', []):
        campo = f'op_{k}'
        if (nivel == 'experto' and not experto) or campo not in request.form:
            continue
        texto = request.form.get(campo, '')
        if tipo == 'secreto' and not texto:
            continue        # vacio = dejar el que habia (nunca se enseña)
        try:
            nuevos[k] = _fun.validar(tipo, texto, extra)
        except ValueError as exc:
            errores.append(f'{nombre}: {exc}')
    if clave == 'panel_solo_redes' and encender:
        redes = nuevos.get('redes', _fun.opcion(clave, 'redes'))
        if not _fun.en_redes(request.remote_addr, redes):
            # para no quedarse fuera: se añade la red desde la que se esta ahora
            nuevos['redes'] = ', '.join(x for x in [redes, request.remote_addr + '/32'] if x)
            cambios.append(f'añadida tu dirección actual ({request.remote_addr}) para que no te quedes fuera')
    if clave == 'doble_aprobacion' and encender:
        with get_db_connection() as c:
            n = c.execute("SELECT COUNT(*) FROM users WHERE role IN ('admin','supremo')").fetchone()[0]
        if n < 2:
            errores.append('hacen falta al menos dos administradores (crea otro usuario administrador primero)')
    if errores:
        flash('No se ha guardado: ' + '; '.join(errores) + '.', 'error')
        return redirect(volver)
    for k, v in nuevos.items():
        config_manager.set_config(f'{clave}.{k}', v, uid)
    antes = bool(config_manager.get_config(clave))
    if not _guardar_protegido(clave, encender, uid):
        return redirect(volver)
    detalle = ('encendida' if encender else 'apagada') + (f'; opciones: {", ".join(sorted(nuevos))}' if nuevos else '')
    log_audit(uid, 'FUNCION_CAMBIADA', f'{clave}: {detalle}', request.remote_addr)
    if antes != encender:
        _ban.marcar('ajustes', f'«{f["nombre"]}» {"encendida" if encender else "apagada"} por {session.get("username")}')
    flash(f'«{f["nombre"]}» {"encendida" if encender else "apagada"}' + (f' ({"; ".join(cambios)})' if cambios else '')
          + '.', 'success')
    return redirect(volver)


# ------------------------------------------------------------------ Ajustes -> Usuarios
_RE_USUARIO = re.compile(r'^[A-Za-z0-9._-]{3,40}$')


def _admins_restantes(sin_id):
    with get_db_connection() as c:
        return c.execute("SELECT COUNT(*) FROM users WHERE role IN ('admin','supremo') AND id != ?", (sin_id,)).fetchone()[0]


def _clave_temporal():
    return secrets.token_urlsafe(9)   # 12 caracteres; se cambia obligatoriamente al entrar


@app.route('/ajustes/usuarios')
@login_required
@role_required('admin', 'supremo')
def usuarios():
    with get_db_connection() as c:
        filas = c.execute('SELECT id, username, email, role, last_login, locked_until, must_change_password, origen, '
                          'totp_activo FROM users ORDER BY id').fetchall()
    nueva = session.pop('clave_una_vez', None)   # la contraseña temporal se enseña una sola vez
    return render_template('usuarios.html', filas=filas, roles=ROLES, nueva=nueva)


@app.route('/ajustes/usuarios/nuevo', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def usuario_nuevo():
    nombre = (request.form.get('username') or '').strip()
    correo = (request.form.get('email') or '').strip().lower()
    rol = request.form.get('role', 'lectura')
    if not _RE_USUARIO.match(nombre):
        flash('El nombre de usuario tiene que tener de 3 a 40 letras, números, puntos o guiones (sin espacios).', 'error')
        return redirect(url_for('usuarios'))
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', correo):
        flash('Escribe un correo válido (sirve para recuperar la contraseña).', 'error')
        return redirect(url_for('usuarios'))
    if rol not in [r for r, _, _ in ROLES]:
        flash('Elige un papel de la lista.', 'error')
        return redirect(url_for('usuarios'))
    clave = _clave_temporal()
    try:
        with get_db_connection() as c:
            c.execute('INSERT INTO users (username, email, password_hash, role, must_change_password) VALUES (?, ?, ?, ?, 1)',
                      (nombre, correo, hash_password(clave), rol))
    except sqlite3.IntegrityError:
        flash('Ya hay un usuario con ese nombre o ese correo.', 'error')
        return redirect(url_for('usuarios'))
    log_audit(session['user_id'], 'USER_ADD', f'{nombre} ({NOMBRE_ROL[rol]})', request.remote_addr)
    session['clave_una_vez'] = {'usuario': nombre, 'clave': clave}
    return redirect(url_for('usuarios'))


@app.route('/ajustes/usuarios/<int:uid>', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def usuario_cambiar(uid):
    accion = request.form.get('accion', '')
    with get_db_connection() as c:
        u = c.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    if not u:
        flash('Ese usuario ya no existe.', 'error')
        return redirect(url_for('usuarios'))
    yo = uid == session['user_id']
    if u['role'] == 'supremo' and session.get('role') != 'supremo':   # ni su papel, ni su contraseña, ni borrarlo
        flash('Al administrador principal solo lo puede cambiar él mismo.', 'error')
        return redirect(url_for('usuarios'))
    if accion == 'rol':
        rol = request.form.get('role', '')
        if (u['origen'] or 'local') != 'local':
            flash('Es un usuario de la empresa: su papel sale de sus grupos (o del ajuste de RADIUS) cada vez que entra.',
                  'error')
        elif rol not in [r for r, _, _ in ROLES] or u['role'] == 'supremo':
            flash('Ese papel no se puede poner aquí.', 'error')
        elif yo:
            flash('No puedes cambiar tu propio papel (pídeselo a otro administrador).', 'error')
        elif u['role'] in ('admin', 'supremo') and rol not in ('admin',) and not _admins_restantes(uid):
            flash('Tiene que quedar al menos un administrador.', 'error')
        else:
            with get_db_connection() as c:
                c.execute('UPDATE users SET role = ? WHERE id = ?', (rol, uid))
            log_audit(session['user_id'], 'USER_ROLE', f'{u["username"]}: {NOMBRE_ROL.get(u["role"])} → {NOMBRE_ROL[rol]}',
                      request.remote_addr)
            flash(f'{u["username"]} ahora es «{NOMBRE_ROL[rol]}».', 'success')
    elif accion == 'clave':
        if yo:
            flash('Para tu propia contraseña usa «Cambiar contraseña».', 'error')
            return redirect(url_for('usuarios'))
        if (u['origen'] or 'local') != 'local':
            flash('Es un usuario de la empresa: su contraseña se cambia en el servidor de la empresa.', 'error')
            return redirect(url_for('usuarios'))
        clave = _clave_temporal()
        with get_db_connection() as c:
            c.execute('UPDATE users SET password_hash = ?, must_change_password = 1, failed_logins = 0, locked_until = NULL, '
                      'recovery_token = NULL, sesion_gen = COALESCE(sesion_gen, 0) + 1 WHERE id = ?',
                      (hash_password(clave), uid))
        _seg.olvidar_dispositivos(DB_FILE, uid)
        log_audit(session['user_id'], 'USER_PASSWORD_RESET', u['username'], request.remote_addr)
        session['clave_una_vez'] = {'usuario': u['username'], 'clave': clave}
    elif accion == 'quitar2fa':
        if yo:
            flash('Para la tuya usa «Tu cuenta → Doble autenticación».', 'error')
        elif not _codigo_ok(session['user_id']):
            flash('Para quitar la doble autenticación de otro usuario hace falta tu código de la app.', 'error')
        else:
            _dosfa.quitar(DB_FILE, uid)
            log_audit(session['user_id'], '2FA_QUITADA', f'{u["username"]}: quitada por {session.get("username")}',
                      request.remote_addr)
            _notificar_incidente('acceso', f'OCTOPUS: {session.get("username")} ha quitado la doble autenticación de '
                                           f'«{u["username"]}» (al entrar tendrá que volver a activarla).')
            flash(f'Doble autenticación de {u["username"]} quitada: la próxima vez que entre tendrá que activarla otra vez '
                  f'con su móvil.', 'success')
    elif accion == 'borrar':
        if yo:
            flash('No puedes borrar tu propio usuario.', 'error')
        elif u['role'] in ('admin', 'supremo') and not _admins_restantes(uid):
            flash('Tiene que quedar al menos un administrador.', 'error')
        elif not _pedir_aprobacion('borrar_usuario', {'id': uid, 'usuario': u['username']},
                                   f'Borrar el usuario «{u["username"]}»'):
            _borrar_usuario(uid)
            log_audit(session['user_id'], 'USER_DELETE', u['username'], request.remote_addr)
            flash(f'Usuario {u["username"]} borrado.', 'success')
    return redirect(url_for('usuarios'))


def _borrar_usuario(uid):
    with get_db_connection() as c:
        c.execute('DELETE FROM users WHERE id = ?', (uid,))
    _seg.olvidar_dispositivos(DB_FILE, uid)


@app.route('/ajustes/nivel', methods=['POST'])
@login_required
def cambiar_nivel():
    """Modo básico (lo justo) o experto (todos los números finos). Cada usuario elige el suyo."""
    nivel = 'experto' if request.form.get('nivel') == 'experto' else 'basico'
    with get_db_connection() as c:
        c.execute('UPDATE users SET nivel = ? WHERE id = ?', (nivel, session['user_id']))
    session['nivel'] = nivel
    destino = request.form.get('volver', '')
    return redirect(destino if destino.startswith('/') and not destino.startswith('//') else url_for('ajustes'))


# ------------------------------------------------------------------ diagnóstico para soporte
@app.route('/ajustes/diagnostico')
@login_required
@role_required('admin', 'supremo')
def descargar_diagnostico():
    """Zip con los banderines y el estado del servidor, sin contraseñas ni nombres de archivos."""
    import diagnostico
    from flask import Response
    datos = diagnostico.zip_bytes(Path(DB_FILE))
    log_audit(session['user_id'], 'DIAGNOSTICO', 'Descargado el diagnóstico para soporte', request.remote_addr)
    nombre = f'octopus_diagnostico_{datetime.now():%Y%m%d_%H%M}.zip'
    return Response(datos, mimetype='application/zip',
                    headers={'Content-Disposition': f'attachment; filename="{nombre}"', 'Cache-Control': 'no-store'})


# ------------------------------------------------------------------ asistente para recuperar
@app.route('/recuperar/asistente')
@login_required
def asistente_recuperar():
    """¿Qué quieres recuperar? → ¿De cuándo? → Listo. Busca por nombre en las copias del servidor."""
    lista = [e for e in _equipos_con_estado() if e['est']['copias']]
    sid = request.args.get('equipo', type=int)
    if not sid and len(lista) == 1:
        sid = lista[0]['sys']['id']
    row = _get_system(sid) if sid else None
    q = (request.args.get('q') or '').strip()[:100]
    ruta = request.args.get('ruta') or ''
    resultados, versiones, error = None, None, None
    if row and q and not ruta:
        r = agentes.buscar_en_servidor(row, q)
        if r.get('status') == 'success':
            resultados = r['resultados']
        else:
            error = r.get('message')
    if row and ruta:
        r = agentes.buscar_en_servidor(row, ruta.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1], exacta=ruta)
        if r.get('status') == 'success' and r['resultados']:
            versiones = r['resultados'][0]['versiones']
        else:
            error = r.get('message') or 'No se encuentra en ninguna copia.'
    paso = 1 if not row else (2 if not q and not ruta else (3 if not ruta else 4))
    return render_template('asistente.html', lista=lista, s=row, q=q, ruta=ruta, resultados=resultados,
                           versiones=versiones, error=error, paso=paso)


# ------------------------------------------------------------------ sugerencias y problemas para el soporte
@app.route('/sugerencia', methods=['GET', 'POST'])
@login_required
def sugerencia():
    import sugerencias as _sug
    import mantenimiento as _m
    env = _m.leer_env()
    if request.method == 'POST':
        texto = (request.form.get('texto') or '').strip()
        if len(texto) < 5:
            flash('Cuéntanos un poco más (al menos unas palabras).', 'error')
            return redirect(url_for('sugerencia'))
        diag = ''
        if request.form.get('diagnostico') == 'on':
            try:
                import diagnostico
                diag = diagnostico.resumen_texto(Path(DB_FILE))
            except Exception as exc:
                diag = f'(no se pudo generar el diagnóstico: {exc})'
        sid = _sug.guardar(Path(DB_FILE), session.get('username', '?'), request.form.get('gravedad', 'problema'),
                           texto, (request.form.get('correo') or '').strip(), diag)
        log_audit(session['user_id'], 'SUGERENCIA', f'#{sid} {request.form.get("gravedad", "")}', request.remote_addr)
        _ban.marcar('sugerencias', f'Sugerencia {sid} recibida ({request.form.get("gravedad", "")})')
        if _sug.hay_destino(env):
            threading.Thread(target=_sug.enviar, args=(env, Path(DB_FILE), sid), daemon=True).start()
            flash('¡Gracias! Lo hemos recibido y se está enviando al soporte.', 'success')
        else:
            flash('¡Gracias! Queda guardado en el servidor. (El envío al soporte todavía no está configurado en este '
                  'servidor: se enviará en cuanto se configure.)', 'success')
        return redirect(url_for('sugerencia'))
    with get_db_connection() as c:
        correo = (c.execute('SELECT email FROM users WHERE id = ?', (session['user_id'],)).fetchone() or {'email': ''})['email']
        try:
            envios = c.execute('SELECT id, fecha, gravedad, estado, destinos, error FROM sugerencias '
                               'WHERE usuario = ? ORDER BY id DESC LIMIT 10', (session.get('username'),)).fetchall()
        except sqlite3.Error:
            envios = []
    return render_template('sugerencia.html', gravedades=_sug.GRAVEDADES, correo=correo, envios=envios,
                           configurado=_sug.hay_destino(env))


@app.route('/sugerencia/prueba', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def sugerencia_prueba():
    """Envía un mensaje de prueba al soporte para comprobar que llega (y dice por dónde ha ido o por qué no)."""
    import sugerencias as _sug
    import mantenimiento as _m
    env = _m.leer_env()
    sid = _sug.guardar(Path(DB_FILE), session.get('username', '?'), 'prueba', 'Prueba de envío desde el panel', '', '')
    r = _sug.enviar(env, Path(DB_FILE), sid)
    flash(('Prueba enviada: ' if r['ok'] else 'La prueba no llegó: ') + r['detalle'], 'success' if r['ok'] else 'error')
    return redirect(url_for('sugerencia'))


def _marcado(nombre):
    """Casillas de los formularios (los navegadores mandan «on»; algunos formularios antiguos «true»)."""
    return (request.form.get(nombre) or '').strip().lower() in ('on', 'true', '1', 'si', 'yes')


# ------------------------------------------------------------------ buscar equipos en la red y darlos de alta en grupo
GRUPOS_SUGERIDOS = ['Oficina', 'Servidores', 'Portátiles', 'Dirección', 'Almacén']


def _conocidos():
    import alta_grupo
    return alta_grupo.conocidos(DB_FILE)


@app.before_request
def _buscar_apagado():
    if request.endpoint in ('buscar_equipos', 'buscar_resultado', 'buscar_credenciales', 'buscar_progreso') \
            and not _fun.activa('buscar_equipos'):
        flash('«Buscar equipos en la red» está apagada en Ajustes → Funciones.', 'error')
        return redirect(url_for('equipos'))


@app.route('/equipos/buscar', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def buscar_equipos():
    """Paso 1: qué redes barrer."""
    import descubrir
    import configuracion as _conf
    env = _conf.leer_env()
    propuestas = descubrir.redes_propuestas(env)
    if request.method == 'POST':
        redes, errores = [], []
        for r in request.form.getlist('red') + (request.form.get('otras') or '').replace(';', ',').replace('\n', ',').split(','):
            if not r.strip():
                continue
            try:
                red = descubrir.validar_red(r)
                if red not in redes:
                    redes.append(red)
            except ValueError as exc:
                errores.append(f'«{r.strip()}»: {exc}')
        if errores:
            flash('Revisa estas redes: ' + '; '.join(errores), 'error')
            return redirect(url_for('buscar_equipos'))
        if not redes:
            flash('Elige al menos una red.', 'error')
            return redirect(url_for('buscar_equipos'))
        ips, _, _ = _conocidos()
        propias = {x.strip() for x in [env.get('OCTOPUS_IP', '')] + env.get('OCTOPUS_NOMBRES_EXTRA', '').split(',')}
        eid = descubrir.empezar(redes, ips, propias)
        _ban.marcar('descubrir', f'Buscar equipos en {", ".join(redes)} (pedido por {session.get("username")})')
        log_audit(session['user_id'], 'NET_SCAN', ', '.join(redes), request.remote_addr)
        return redirect(url_for('buscar_resultado', eid=eid))
    return render_template('buscar.html', paso=1, propuestas=propuestas)


@app.route('/equipos/buscar/<eid>', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def buscar_resultado(eid):
    """Paso 2: lo encontrado; se eligen equipos, su nombre, su sistema y su grupo."""
    import descubrir
    e = descubrir.ver(eid)
    if not e:
        flash('Esa búsqueda ya no está (el panel se reinició). Vuelve a buscar.', 'error')
        return redirect(url_for('buscar_equipos'))
    if request.method == 'POST':
        _, _, nombres_usados = _conocidos()
        grupos, errores, vistos = {}, [], set()
        for x in e['encontrados']:
            ip = x['ip']
            if request.form.get(f'usar_{ip}') != 'on':
                continue
            nombre = (request.form.get(f'nombre_{ip}') or x['nombre']).strip()
            so = request.form.get(f'so_{ip}') or x['so']
            grupo = (request.form.get(f'grupo_{ip}') or 'Oficina').strip()[:40] or 'Oficina'
            import alta_equipos
            if not alta_equipos.nombre_valido(nombre):
                errores.append(f'{ip}: el nombre «{nombre}» no vale (sin espacios ni símbolos raros)')
            elif nombre.lower() in nombres_usados or nombre.lower() in vistos:
                errores.append(f'{ip}: ya hay un equipo llamado «{nombre}»')
            elif so not in ('linux', 'windows', 'macos'):
                errores.append(f'{ip}: elige si es Windows, Linux o Mac')
            vistos.add(nombre.lower())
            grupos.setdefault(grupo, []).append({'ip': ip, 'nombre': nombre, 'so': so, 'ssh': x['ssh']})
        if errores:
            flash('Revisa: ' + '; '.join(errores), 'error')
            return redirect(url_for('buscar_resultado', eid=eid))
        if not grupos:
            flash('Marca al menos un equipo.', 'error')
            return redirect(url_for('buscar_resultado', eid=eid))
        descubrir.guardar(eid, grupos=grupos)
        return redirect(url_for('buscar_credenciales', eid=eid))
    _, grupos_existentes, _ = _conocidos()
    return render_template('buscar.html', paso=2, e=e, grupos=list(dict.fromkeys(grupos_existentes + GRUPOS_SUGERIDOS)),
                           segundos=int((e['fin'] or time.time()) - e['inicio']))


@app.route('/equipos/buscar/<eid>/credenciales', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def buscar_credenciales(eid):
    """Paso 3: usuario y contraseña por grupo (se usan una vez y se olvidan) y se instala en todos."""
    import descubrir
    import alta_equipos
    e = descubrir.ver(eid)
    if not e or not e['grupos']:
        return redirect(url_for('buscar_equipos'))
    if request.method == 'POST':
        import alta_grupo
        trabajos = []
        for i, (grupo, equipos_g) in enumerate(e['grupos'].items()):
            usuario = (request.form.get(f'usuario_{i}') or '').strip()
            password = request.form.get(f'password_{i}') or ''
            solo_clave = request.form.get(f'solo_clave_{i}') == 'on'
            for q in equipos_g:
                sid = alta_grupo.alta(DB_FILE, q, grupo, f'panel, {session.get("username", "?")}', session['user_id'])
                if sid is None:
                    trabajos.append({'nombre': q['nombre'], 'ip': q['ip'], 'grupo': grupo, 'job': None,
                                     'mensaje': 'Ya existía un equipo con ese nombre: no se ha tocado.'})
                    continue
                falta = alta_grupo.que_falta(q, usuario, password)
                if falta:
                    trabajos.append({'nombre': q['nombre'], 'ip': q['ip'], 'grupo': grupo, 'job': None, 'sid': sid,
                                     'mensaje': falta})
                    continue
                jid = _lanzar_instalacion_remota(_get_system(sid), q['ip'], usuario, password, solo_clave and q['so'] == 'linux')
                trabajos.append({'nombre': q['nombre'], 'ip': q['ip'], 'grupo': grupo, 'job': jid, 'sid': sid})
            password = None
        descubrir.guardar(eid, trabajos=trabajos, grupos={})
        _ban.marcar('descubrir', f'Alta en grupo: {len(trabajos)} equipos, {sum(1 for t in trabajos if t["job"])} instalándose')
        return redirect(url_for('buscar_progreso', eid=eid))
    return render_template('buscar.html', paso=3, e=e)


@app.route('/equipos/buscar/<eid>/progreso')
@login_required
@role_required('admin', 'supremo')
def buscar_progreso(eid):
    """Paso 4: cómo va la instalación de cada equipo."""
    import descubrir
    e = descubrir.ver(eid)
    if not e:
        return redirect(url_for('equipos'))
    jobs = {j['id']: j for j in agentes.trabajos_de(None, 500)}
    filas = []
    for t in e['trabajos']:
        j = jobs.get(t.get('job')) if t.get('job') else None
        estado = (j or {}).get('estado') or ('error' if t.get('job') is None and 'Ya existía' not in t.get('mensaje', '') else 'nada')
        if t.get('job') is None and 'Dado de alta' in t.get('mensaje', ''):
            estado = 'pendiente'
        filas.append({**t, 'estado': estado, 'mensaje': (j or {}).get('mensaje') or t.get('mensaje', '')})
    en_curso = sum(1 for f in filas if f['estado'] == 'en_curso')
    ok = sum(1 for f in filas if f['estado'] == 'ok')
    return render_template('buscar.html', paso=4, e=e, filas=filas, en_curso=en_curso, ok=ok)


# Funciones auxiliares
def hash_password(password):
    """Hashea contraseña usando bcrypt (o PBKDF2-SHA256 si bcrypt no está instalado)"""
    if bcrypt is not None:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode(), 310000)
    return f"pbkdf2${salt}${dk.hex()}"

def verify_password(password, password_hash):
    """Verifica contraseña (bcrypt o PBKDF2)"""
    try:
        if password_hash.startswith('pbkdf2$'):
            _, salt, digest = password_hash.split('$', 2)
            dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode(), 310000)
            return secrets.compare_digest(dk.hex(), digest)
        if bcrypt is None:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False

def send_recovery_email(email, token):
    """Envía el enlace de recuperación por correo (usa la configuración SMTP del panel)."""
    base = os.environ.get('PANEL_PUBLIC_URL') or request.host_url.rstrip('/')
    enlace = f"{base}{url_for('reset_password', token=token)}"
    cuerpo = ("Hola,\n\nHas pedido cambiar la contraseña del panel OCTOPUS. Abre este enlace (caduca en 30 minutos):\n\n"
              f"{enlace}\n\nSi no lo has pedido tú, ignora este correo y avisa al administrador.\n")
    ok, msg = notification_manager.send_email(email, '[OCTOPUS] Recuperar contraseña', cuerpo)
    if not ok:
        print(f"[RECUPERACIÓN] No se pudo enviar el correo a {email}: {msg}. Configura el correo en Ajustes.")
    return ok

def create_initial_admin():
    """Crea usuario admin inicial si no existe. Usa ADMIN_PASSWORD del .env si existe."""
    conn = get_db_connection()
    admin = conn.execute("SELECT * FROM users WHERE role = 'supremo'").fetchone()

    if not admin:
        default_password = (
            os.environ.get('ADMIN_PASSWORD')
            or os.environ.get('ADMIN_MASTER_PASSWORD')
            or secrets.token_urlsafe(18)
        )
        admin_email = (
            os.environ.get('ADMIN_EMAIL')
            or "admin@zerotouch.local"
        )
        password_hash = hash_password(default_password)

        conn.execute('''
            INSERT INTO users (username, email, password_hash, role, must_change_password)
            VALUES (?, ?, ?, ?, ?)
        ''', ('admin', admin_email, password_hash, 'supremo',
              0 if os.environ.get('OCTOPUS_NO_FORCE_PASSWORD_CHANGE') == '1' else 1))
        conn.commit()

        masked = default_password[:4] + ("*" * max(0, len(default_password) - 4))
        print(f"[SETUP] Admin supremo creado: admin / {masked}")
        if not os.environ.get('ADMIN_PASSWORD') and not os.environ.get('ADMIN_MASTER_PASSWORD'):
            # contrasena aleatoria: se deja en un archivo solo legible por root (no hay contrasena por defecto)
            cred = os.path.join(BASE_DIR, 'data', 'CREDENCIALES_INICIALES.txt')
            try:
                os.makedirs(os.path.dirname(cred), exist_ok=True)
                fd = os.open(cred, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w') as fh:
                    fh.write(f"Usuario: admin\nContrasena inicial (de un solo uso): {default_password}\n")
                print(f"[SETUP]  -> Contrasena inicial guardada en {cred}")
            except OSError:
                print(f"[SETUP]  -> Contrasena inicial: {default_password}")
        print(f"[SETUP] CAMBIAR ESTA CONTRASEÑA INMEDIATAMENTE via Panel Web -> Perfil")

    conn.close()

# Inicializar BD y admin al importar (funciona tanto con `python admin_panel.py`
# como con systemd / gunicorn / tests)
try:
    init_db()
    create_initial_admin()
except Exception as _e:  # pragma: no cover
    print(f"[SETUP] Aviso inicializando BD: {_e}")

if __name__ == '__main__':
    app.run(host=os.environ.get('ADMIN_BIND', '0.0.0.0'),
            port=int(os.environ.get('ADMIN_PORT', 8080)),
            ssl_context=(TLS_CERT, TLS_KEY) if USE_HTTPS else None,
            debug=os.environ.get('FLASK_DEBUG', '0') == '1')