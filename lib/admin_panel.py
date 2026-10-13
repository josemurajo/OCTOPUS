#!/usr/bin/env python3
"""
ZeroTouch - Panel de Administración Web
Interfaz web para gestión de sistemas, configuración y monitorización
"""

import os
import sys
import json
import threading
import re
import sqlite3
import hashlib
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
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
from intelligent_detection import IntelligentDetection
from wazuh_integration import WazuhIntegration
from telegram_integration import TelegramIntegration
from alert_manager import AlertManager
from config_presets import ConfigPresets
import agentes
import avisos as _av
import banderines as _ban
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
        storage_uri="memory://"
    )
else:
    print("[AVISO] flask-limiter no instalado: rate limiting desactivado")

    class _NoLimiter:
        def limit(self, *a, **k):
            return lambda f: f

        def exempt(self, f):
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

# Pantallas de la version 1 que guardaban ajustes que la version 2 ya no usa: se mandan a Ajustes
PANTALLAS_RETIRADAS = {'config', 'config_presets', 'config_backup', 'config_paths', 'config_security',
                       'config_detection', 'approvals', 'dashboard_avanzado'}

PUBLIC_ENDPOINTS = {'login', 'static', 'recover_password', 'reset_password', 'index', 'healthz'}


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
        # Contrasena inicial: obligar a cambiarla antes de usar el panel
        if session.get('must_change') and request.endpoint not in ('cambiar_password', 'logout', 'static'):
            return redirect(url_for('cambiar_password'))
        if request.endpoint in PANTALLAS_RETIRADAS:
            return redirect(url_for('ajustes'))


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

# Instancia del detector inteligente
intelligent_detector = IntelligentDetection(DB_FILE)

# Instancia de integración con Wazuh
wazuh_integration = WazuhIntegration(config_manager)

# Instancia de integración con Telegram
telegram_integration = TelegramIntegration(config_manager)

# Instancia del gestor de alertas
alert_manager = AlertManager(DB_FILE)

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
    
    # Tabla de aprobaciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester_id INTEGER NOT NULL,
            approver_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            decided_at TIMESTAMP,
            FOREIGN KEY (requester_id) REFERENCES users (id),
            FOREIGN KEY (approver_id) REFERENCES users (id)
        )
    ''')
    
    # Migraciones (columnas nuevas en instalaciones existentes)
    for table, col, ddl in (
        ('users', 'must_change_password', 'INTEGER DEFAULT 0'),
        ('users', 'failed_logins', 'INTEGER DEFAULT 0'),
        ('users', 'locked_until', 'TIMESTAMP'),
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

    conn.commit()
    conn.close()

def get_db_connection():
    """Obtiene conexión a la base de datos"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def _hash_registro(anterior, rid, user_id, action, details, ts, ip):
    base = '|'.join('' if x is None else str(x) for x in (anterior, rid, user_id, action, details, ts, ip))
    return hashlib.sha256(base.encode('utf-8')).hexdigest()


def log_audit(user_id, action, details="", ip_address=""):
    """Registra la acción en el registro de actividad. Cada línea va encadenada con la anterior (huella SHA-256):
    si alguien borra o cambia una línea por detrás, la cadena se rompe y el panel lo avisa."""
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        prev = conn.execute('SELECT hash FROM audit_logs ORDER BY id DESC LIMIT 1').fetchone()
        anterior = prev['hash'] if prev and prev['hash'] else ''
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute('INSERT INTO audit_logs (user_id, action, details, ip_address, timestamp, hash_anterior) '
                           'VALUES (?, ?, ?, ?, ?, ?)', (user_id, action, details, ip_address, ts, anterior))
        conn.execute('UPDATE audit_logs SET hash = ? WHERE id = ?',
                     (_hash_registro(anterior, cur.lastrowid, user_id, action, details, ts, ip_address), cur.lastrowid))
        conn.commit()
    finally:
        conn.close()


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
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Rutas de autenticación
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # Protección contra fuerza bruta
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

        if user and verify_password(password, user['password_hash']):
            conn.execute('UPDATE users SET last_login = ?, failed_logins = 0, locked_until = NULL WHERE id = ?',
                         (datetime.now(), user['id']))
            conn.commit()
            conn.close()
            session.clear()  # evita fijacion de sesion
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['must_change'] = bool(user['must_change_password'])
            session['_last_seen'] = datetime.now().timestamp()
            session.permanent = True
            log_audit(user['id'], 'LOGIN', 'Inicio de sesion', request.remote_addr)
            if session['must_change']:
                flash('Por seguridad, elige una contrasena nueva antes de continuar.', 'info')
                return redirect(url_for('cambiar_password'))
            return redirect(url_for('inicio'))

        if user:
            fails = (user['failed_logins'] or 0) + 1
            locked_until = datetime.now() + timedelta(minutes=LOCKOUT_MINUTES) if fails >= MAX_FAILED_LOGINS else None
            conn.execute('UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?',
                         (0 if locked_until else fails, locked_until, user['id']))
            conn.commit()
            log_audit(user['id'], 'LOGIN_FAILED', f'Contrasena incorrecta ({fails})', request.remote_addr)
        conn.close()
        flash('Usuario o contrasena incorrectos.', 'error')

    return render_template('login.html')

@app.route('/logout')
def logout():
    """Cerrar sesión"""
    if 'user_id' in session:
        log_audit(session['user_id'], 'LOGOUT', 'User logged out', request.remote_addr)
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('login'))

@app.route('/recover', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def recover_password():
    """Recuperacion de contrasena por correo (mismo mensaje exista o no el correo: no revela usuarios)"""
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE lower(email) = ?', (email,)).fetchone()
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
        conn.execute('UPDATE users SET password_hash = ?, recovery_token = NULL, recovery_token_expiry = NULL, failed_logins = 0, locked_until = NULL WHERE id = ?',
                   (password_hash, user['id']))
        conn.commit()
        conn.close()
        
        log_audit(user['id'], 'PASSWORD_RESET', 'Password reset via recovery token', request.remote_addr)
        flash('Contraseña restablecida exitosamente', 'success')
        return redirect(url_for('login'))
    
    conn.close()
    return render_template('reset_password.html', token=token)

@app.route('/config/update', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def config_update():
    """Actualizar configuración"""
    key = request.form['key']
    value = request.form['value']
    
    conn = get_db_connection()
    conn.execute('''
        INSERT OR REPLACE INTO config (key, value, updated_at)
        VALUES (?, ?, ?)
    ''', (key, value, datetime.now()))
    conn.commit()
    conn.close()
    
    log_audit(session['user_id'], 'CONFIG_UPDATE', f'Updated config: {key}', request.remote_addr)
    flash('Configuración actualizada', 'success')
    return redirect(url_for('config'))

@app.route('/approvals')
@login_required
def approvals():
    """Sistema de aprobaciones"""
    conn = get_db_connection()
    
    if session['role'] in ['admin', 'supremo']:
        pending = conn.execute('''
            SELECT a.*, r.username as requester_name, ap.username as approver_name
            FROM approvals a
            LEFT JOIN users r ON a.requester_id = r.id
            LEFT JOIN users ap ON a.approver_id = ap.id
            WHERE a.status = 'pending'
            ORDER BY a.created_at DESC
        ''').fetchall()
    else:
        pending = conn.execute('''
            SELECT a.*, r.username as requester_name, ap.username as approver_name
            FROM approvals a
            LEFT JOIN users r ON a.requester_id = r.id
            LEFT JOIN users ap ON a.approver_id = ap.id
            WHERE a.status = 'pending' AND a.requester_id = ?
            ORDER BY a.created_at DESC
        ''', (session['user_id'],)).fetchall()
    
    all_approvals = conn.execute('''
        SELECT a.*, r.username as requester_name, ap.username as approver_name
        FROM approvals a
        LEFT JOIN users r ON a.requester_id = r.id
        LEFT JOIN users ap ON a.approver_id = ap.id
        ORDER BY a.created_at DESC
        LIMIT 50
    ''').fetchall()
    
    conn.close()
    
    return render_template('approvals.html', pending=pending, all_approvals=all_approvals)

@app.route('/approve/<int:approval_id>/<action>')
@login_required
@role_required('admin', 'supremo')
def approve(approval_id, action):
    """Aprobar o rechazar solicitud"""
    if action not in ['approve', 'reject']:
        flash('Acción inválida', 'error')
        return redirect(url_for('approvals'))
    
    conn = get_db_connection()
    conn.execute('''
        UPDATE approvals 
        SET approver_id = ?, status = ?, decided_at = ?
        WHERE id = ?
    ''', (session['user_id'], action, datetime.now(), approval_id))
    conn.commit()
    conn.close()
    
    log_audit(session['user_id'], f'APPROVAL_{action.upper()}', f'Approval {action}d: {approval_id}', request.remote_addr)
    flash(f'Solicitud {action}d exitosamente', 'success')
    return redirect(url_for('approvals'))

# ========================================
# RUTAS DE CONFIGURACIÓN
# ========================================

@app.route('/config')
@login_required
def config():
    """Página de configuración del sistema"""
    conn = get_db_connection()
    
    # Obtener configuración actual del sistema
    config = config_manager.get_config()
    
    # Obtener sistemas registrados
    systems = conn.execute('SELECT * FROM systems ORDER BY hostname').fetchall()
    
    conn.close()
    
    return render_template('config.html', config=config, systems=systems)

@app.route('/config/backup', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def config_backup():
    """Configuración de backups"""
    if request.method == 'POST':
        key = request.form.get('key')
        value = request.form.get('value')
        
        valid, message = config_manager.validate_config_change(key, value)
        if not valid:
            flash(f'Error: {message}', 'error')
            return redirect(url_for('config_backup'))
        
        # Convertir valor según tipo
        config = config_manager.get_config()
        expected_type = type(config.get(key, str))
        
        try:
            if expected_type == bool:
                value = value.lower() == 'true'
            elif expected_type == int:
                value = int(value)
            elif expected_type == float:
                value = float(value)
            elif expected_type == list:
                value = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            flash(f'Error: Valor inválido para {key}', 'error')
            return redirect(url_for('config_backup'))
        
        success, message = config_manager.set_config(key, value, session['user_id'])
        if success:
            log_audit(session['user_id'], 'CONFIG_BACKUP_UPDATE', f'{key} = {value}', request.remote_addr)
            flash(f'Configuración actualizada: {message}', 'success')
        else:
            flash(f'Error: {message}', 'error')
        
        return redirect(url_for('config_backup'))
    
    # GET: mostrar configuración actual
    config = config_manager.get_config()
    schedule = config_manager.get_backup_schedule()
    retention = config_manager.get_retention_policy()
    
    return render_template('config_backup.html', config=config, schedule=schedule, retention=retention)

@app.route('/config/security', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def config_security():
    """Configuración de seguridad"""
    if request.method == 'POST':
        key = request.form.get('key')
        value = request.form.get('value')
        
        valid, message = config_manager.validate_config_change(key, value)
        if not valid:
            flash(f'Error: {message}', 'error')
            return redirect(url_for('config_security'))
        
        # Convertir valor según tipo
        config = config_manager.get_config()
        expected_type = type(config.get(key, str))
        
        try:
            if expected_type == bool:
                value = value.lower() == 'true'
            elif expected_type == int:
                value = int(value)
            elif expected_type == float:
                value = float(value)
            elif expected_type == list:
                value = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            flash(f'Error: Valor inválido para {key}', 'error')
            return redirect(url_for('config_security'))
        
        success, message = config_manager.set_config(key, value, session['user_id'])
        if success:
            log_audit(session['user_id'], 'CONFIG_SECURITY_UPDATE', f'{key} = {value}', request.remote_addr)
            flash(f'Configuración actualizada: {message}', 'success')
        else:
            flash(f'Error: {message}', 'error')
        
        return redirect(url_for('config_security'))
    
    # GET: mostrar configuración actual
    config = config_manager.get_config()
    policies = config_manager.get_security_policies()
    
    return render_template('config_security.html', config=config, policies=policies)

@app.route('/config/paths', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def config_paths():
    """Configuración de rutas protegidas"""
    if request.method == 'POST':
        config = config_manager.get_config()
        protected = config.get('protected_paths', {})
        excluded = config.get('excluded_paths', {})
        
        # Procesar rutas protegidas por SO
        protected_windows = request.form.get('protected_paths_windows', '').split('\n')
        protected_linux = request.form.get('protected_paths_linux', '').split('\n')
        protected_macos = request.form.get('protected_paths_macos', '').split('\n')
        
        # Limpiar rutas vacías
        protected_windows = [p.strip() for p in protected_windows if p.strip()]
        protected_linux = [p.strip() for p in protected_linux if p.strip()]
        protected_macos = [p.strip() for p in protected_macos if p.strip()]
        
        protected = {
            'windows': protected_windows,
            'linux': protected_linux,
            'macos': protected_macos
        }
        
        # Procesar rutas excluidas por SO
        excluded_windows = request.form.get('excluded_paths_windows', '').split('\n')
        excluded_linux = request.form.get('excluded_paths_linux', '').split('\n')
        excluded_macos = request.form.get('excluded_paths_macos', '').split('\n')
        
        # Limpiar rutas vacías
        excluded_windows = [p.strip() for p in excluded_windows if p.strip()]
        excluded_linux = [p.strip() for p in excluded_linux if p.strip()]
        excluded_macos = [p.strip() for p in excluded_macos if p.strip()]
        
        excluded = {
            'windows': excluded_windows,
            'linux': excluded_linux,
            'macos': excluded_macos
        }
        
        # Procesar ruta personalizada si se agregó
        custom_os = request.form.get('custom_os')
        custom_path = request.form.get('custom_path')
        custom_type = request.form.get('custom_type')
        
        if custom_os and custom_path and custom_type:
            if custom_type == 'protected':
                protected[custom_os].append(custom_path.strip())
            else:
                excluded[custom_os].append(custom_path.strip())
        
        # Guardar configuración
        success, message = config_manager.set_config('protected_paths', protected, session['user_id'])
        if success:
            config_manager.set_config('excluded_paths', excluded, session['user_id'])
            log_audit(session['user_id'], 'CONFIG_PATHS_UPDATE', f'Updated protected and excluded paths', request.remote_addr)
            flash('Rutas actualizadas correctamente', 'success')
        else:
            flash(f'Error: {message}', 'error')
        
        return redirect(url_for('config_paths'))
    
    # GET: mostrar rutas actuales
    config = config_manager.get_config()
    protected = config.get('protected_paths', {})
    excluded = config.get('excluded_paths', {})
    
    return render_template('config_paths.html', protected=protected, excluded=excluded)

@app.route('/config/reset/<key>')
@login_required
@role_required('supremo')
def config_reset(key):
    """Restablece configuración a valor por defecto"""
    success, message = config_manager.reset_config(key)
    if success:
        log_audit(session['user_id'], 'CONFIG_RESET', f'Key {key} reset to default', request.remote_addr)
        flash(f'Configuración restablecida: {message}', 'success')
    else:
        flash(f'Error: {message}', 'error')
    
    return redirect(url_for('config'))

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
            config_manager.set_config('email_notifications', _marcado('email_notifications'), uid)
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

@app.route('/config/detection', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def config_detection():
    """Configuración de detección inteligente"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_whitelist':
            file_path = request.form.get('file_path')
            pattern = request.form.get('pattern', '')
            user = request.form.get('user', '')
            process = request.form.get('process', '')
            reason = request.form.get('reason', '')
            expires_days = request.form.get('expires_days')
            
            expires_days = int(expires_days) if expires_days else None
            
            success, message = intelligent_detector.add_to_whitelist(
                file_path, pattern, user, process, reason, expires_days, session['user_id']
            )
            
            if success:
                log_audit(session['user_id'], 'WHITELIST_ADD', f'Added {file_path} to whitelist', request.remote_addr)
                flash(message, 'success')
            else:
                flash(message, 'error')
        
        elif action == 'remove_whitelist':
            whitelist_id = request.form.get('whitelist_id')
            success, message = intelligent_detector.remove_from_whitelist(int(whitelist_id))
            
            if success:
                log_audit(session['user_id'], 'WHITELIST_REMOVE', f'Removed whitelist entry {whitelist_id}', request.remote_addr)
                flash(message, 'success')
            else:
                flash(message, 'error')
        
        elif action == 'add_pattern':
            pattern = request.form.get('pattern')
            severity = request.form.get('severity', 'medium')
            description = request.form.get('description', '')
            
            success, message = intelligent_detector.add_suspicious_pattern(pattern, severity, description)
            
            if success:
                log_audit(session['user_id'], 'PATTERN_ADD', f'Added suspicious pattern: {pattern}', request.remote_addr)
                flash(message, 'success')
            else:
                flash(message, 'error')
        
        elif action == 'remove_pattern':
            pattern_id = request.form.get('pattern_id')
            success, message = intelligent_detector.remove_suspicious_pattern(int(pattern_id))
            
            if success:
                log_audit(session['user_id'], 'PATTERN_REMOVE', f'Removed pattern {pattern_id}', request.remote_addr)
                flash(message, 'success')
            else:
                flash(message, 'error')
        
        return redirect(url_for('config_detection'))
    
    # GET: mostrar configuración actual
    whitelist = intelligent_detector.get_whitelist()
    patterns = intelligent_detector.get_suspicious_patterns()
    
    return render_template('config_detection.html', whitelist=whitelist, patterns=patterns)

@app.route('/test_detection', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def test_detection():
    """Prueba la detección inteligente"""
    file_path = request.form.get('file_path')
    change_type = request.form.get('change_type', 'modify')
    user = request.form.get('user', '')
    process = request.form.get('process', '')
    
    result = intelligent_detector.analyze_change(file_path, change_type, user, process)
    
    return jsonify(result)

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
        
        config_manager.set_config('telegram_enabled', telegram_enabled, session['user_id'])
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

@app.route('/systems')
@login_required
def systems():
    return redirect(url_for('equipos'))

@app.route('/systems/add', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def add_system():
    """Agregar nuevo sistema"""
    hostname = request.form.get('hostname')
    ip_address = request.form.get('ip_address')
    os_family = request.form.get('os_family')
    os_version = request.form.get('os_version', '')
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO systems (hostname, ip_address, os_family, os_version, status)
        VALUES (?, ?, ?, ?, 'unknown')
    ''', (hostname, ip_address, os_family, os_version))
    conn.commit()
    conn.close()
    
    log_audit(session['user_id'], 'SYSTEM_ADD', f'Added system: {hostname} ({ip_address})', request.remote_addr)
    flash('Sistema agregado correctamente', 'success')
    
    return redirect(url_for('equipos'))

@app.route('/systems/<int:system_id>/delete', methods=['POST'])
@login_required
@role_required('admin', 'supremo')
def delete_system(system_id):
    """Eliminar sistema"""
    conn = get_db_connection()
    system = conn.execute('SELECT * FROM systems WHERE id = ?', (system_id,)).fetchone()
    
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

@app.route('/request_approval', methods=['POST'])
@login_required
def request_approval():
    """Crear solicitud de aprobación"""
    action = request.form.get('action')
    details = request.form.get('details', '')
    
    if not action:
        flash('Debe especificar una acción', 'error')
        return redirect(url_for('dashboard'))
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO approvals (requester_id, action, details, status)
        VALUES (?, ?, ?, 'pending')
    ''', (session['user_id'], action, details))
    conn.commit()
    conn.close()
    
    log_audit(session['user_id'], 'APPROVAL_REQUEST', f'Requested approval for: {action}', request.remote_addr)
    flash('Solicitud de aprobación creada', 'success')
    
    return redirect(url_for('approvals'))

# ========================================
# RUTA PRINCIPAL
# ========================================

@app.route('/')
def index():
    return redirect(url_for('inicio') if 'user_id' in session else url_for('login'))

@app.route('/peace-of-mind')
@login_required
def peace_of_mind():
    return redirect(url_for('inicio'))

@app.route('/config/presets', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'supremo')
def config_presets():
    """Configuración mediante presets"""
    if request.method == 'POST':
        preset_name = request.form.get('preset')
        
        if not preset_name:
            flash('Debes seleccionar un preset', 'error')
            return redirect(url_for('config_presets'))
        
        success, message = ConfigPresets.apply_preset(config_manager, preset_name, session['user_id'])
        
        if success:
            log_audit(session['user_id'], 'CONFIG_PRESET_APPLY', f'Applied preset: {preset_name}', request.remote_addr)
            flash(message, 'success')
        else:
            flash(message, 'error')
        
        return redirect(url_for('config_presets'))
    
    presets = ConfigPresets.get_all_presets()
    
    return render_template('config_presets.html', presets=presets)

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
        ("API interna", "8081", "Solo este servidor", ""),
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


def restart_docker_services():
    """Reinicia servicios Docker con nueva configuración"""
    try:
        install_dir = os.path.join(BASE_DIR, 'install')
        compose_file = os.path.join(install_dir, 'docker-compose.yml')
        
        env_file = os.path.join(BASE_DIR, '.env')
        base = ['docker', 'compose']
        if subprocess.run(base + ['version'], capture_output=True).returncode != 0:
            base = ['docker-compose']
        if os.name != 'nt' and os.geteuid() != 0:
            base = ['sudo', '-n'] + base
        args = ['-f', compose_file]
        if os.path.isfile(env_file):
            args += ['--env-file', env_file]
        subprocess.run(base + args + ['up', '-d'], capture_output=True, check=False, timeout=600)
        
        return True
    except Exception as e:
        print(f"Error reiniciando servicios: {e}")
        return False

# ========================================
# RUTAS DE DASHBOARD
# ========================================

@app.route('/dashboard')
@login_required
def dashboard():
    return redirect(url_for('inicio'))


@app.route('/avanzado/resumen')
@login_required
def dashboard_avanzado():
    """Resumen tecnico (antiguo dashboard)"""
    conn = get_db_connection()
    
    # Estadísticas
    total_systems = conn.execute('SELECT COUNT(*) FROM systems').fetchone()[0]
    total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    pending_approvals = conn.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'").fetchone()[0]
    
    # Sistemas con backups recientes
    recent_backups = conn.execute('''
        SELECT hostname, last_backup, status 
        FROM systems 
        WHERE last_backup IS NOT NULL
        ORDER BY last_backup DESC
        LIMIT 10
    ''').fetchall()
    
    # Sistemas offline
    offline_systems = conn.execute('''
        SELECT hostname, ip_address, last_seen 
        FROM systems 
        WHERE status = 'offline'
        ORDER BY last_seen DESC
        LIMIT 10
    ''').fetchall()
    
    # Logs recientes
    recent_logs = conn.execute('''
        SELECT al.*, u.username 
        FROM audit_logs al
        LEFT JOIN users u ON al.user_id = u.id
        ORDER BY al.timestamp DESC
        LIMIT 20
    ''').fetchall()
    
    conn.close()
    
    config = config_manager.get_config()
    
    return render_template('dashboard.html', 
                           total_systems=total_systems,
                           total_users=total_users,
                           pending_approvals=pending_approvals,
                           recent_backups=recent_backups,
                           offline_systems=offline_systems,
                           recent_logs=recent_logs,
                           config=config)


# ========================================
# PANEL SENCILLO (Inicio, Equipos, Restaurar, Avisos, Ajustes)
# ========================================

def puede_actuar():
    return session.get('role') in ('admin', 'supremo')


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
    a.update(equipo=equipo, id=sid)
    if a.get('enlace'):
        ruta, _, ancla = a['enlace'].partition('#')
        a['enlace'] = url_for(ruta) + ('#' + ancla if ancla else '')
    a['ultimo_intento'] = (soluciones or {}).get(f'{codigo}:{sid or ""}')
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
        if act.get('hay_nueva'):
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


@app.route('/avisos/solucionar', methods=['POST'])
@login_required
def avisos_solucionar():
    """Botón «Solucionar» de un aviso: hace sola la solución cuando se puede."""
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
    row = _get_system(sid) if sid else None
    equipo = row['hostname'] if row else None
    usuario = session.get('username', '?')
    log_audit(session['user_id'], 'AVISO_SOLUCIONAR', f'{codigo} ({accion}) {equipo or ""}'.strip(), request.remote_addr)
    _ban.marcar('avisos', f'{usuario} pulsa Solucionar: {accion}', equipo=equipo, codigo=codigo)

    if accion in ('copia_equipo', 'prueba_equipo'):
        if not row:
            flash('Ese equipo ya no existe.', 'error')
            return redirect(volver)
        uid = session['user_id']

        def _fin(s_id, ok, resp, _row=row, _prueba=(accion == 'prueba_equipo')):
            _copia_terminada(s_id, ok, resp)
            _guardar_solucion(codigo, s_id, 'ok' if ok else 'error',
                              ('Copia hecha' + ('; repitiendo la prueba de recuperación' if _prueba else '')) if ok
                              else f'La copia volvió a fallar: {str(resp.get("message", ""))[:200]}')
            if ok and _prueba:
                _lanzar_prueba(_row, uid)
        agentes.lanzar_copia(row, on_done=_fin)
        _guardar_solucion(codigo, sid, 'en_curso', 'Copia en marcha...')
        flash(f'Copia de {row["hostname"]} en marcha' + (' (después se repite la prueba)' if accion == 'prueba_equipo'
              else '') + '. Cuando termine bien, el aviso desaparecerá solo.', 'success')
        return redirect(volver)

    if accion == 'reenviar_sugerencias':
        import sugerencias as _sug
        import mantenimiento as _m2
        r = _sug.reenviar_pendientes(_m2.leer_env(), Path(DB_FILE))
        _guardar_solucion(codigo, None, 'ok' if r.get('ok') else 'error', r['detalle'])
        flash(r['detalle'], 'success' if r.get('ok') else 'error')
        return redirect(volver)

    fn = _av.ACCIONES_SERVIDOR.get(accion)
    if not fn:
        flash('Acción desconocida.', 'error')
        return redirect(volver)
    if accion in ('mantenimiento_ahora', 'comprobar_actualizacion', 'renovar_certificado'):
        try:
            r = fn()
        except Exception as exc:
            r = {'ok': False, 'detalle': f'Error inesperado: {exc}'}
        _guardar_solucion(codigo, None, 'ok' if r.get('ok') else ('en_curso' if r.get('en_marcha') else 'error'),
                          r['detalle'])
        _ban.marcar('avisos', f'Solucionar {accion}: {r["detalle"]}', codigo=codigo,
                    nivel='ok' if r.get('ok') else 'error')
        flash(r['detalle'], 'success' if r.get('ok') else 'error')
        return redirect(volver)

    _guardar_solucion(codigo, None, 'en_curso', 'Arreglando... (puede tardar unos minutos)')

    def _run():
        try:
            r = fn()
        except Exception as exc:
            r = {'ok': False, 'detalle': f'Error inesperado: {exc}'}
        _guardar_solucion(codigo, None, 'ok' if r.get('ok') else 'error', r.get('detalle', ''))
        _ban.marcar('avisos', f'Solucionar {accion}: {r.get("detalle", "")}', codigo=codigo,
                    nivel='ok' if r.get('ok') else 'error')
        if r.get('ok'):  # el aviso desaparece: se apunta en el estado del mantenimiento que ya está arreglado
            try:
                import mantenimiento as _m3
                est = _m3.leer_estado()
                tareas = {'desbloquear_almacen': ('verificar', 'retencion'), 'reparar_almacen': ('verificar',),
                          'limpiar_copias': ('retencion',), 'copia_servidor': ('autocopia',)}.get(accion, ())
                cambiado = False
                for t in tareas:
                    if t in (est.get('resultados') or {}):
                        est['resultados'][t].update(ok=True, codigo=None,
                                                    detalle=f'Solucionado desde el panel: {r.get("detalle", "")}'[:300])
                        cambiado = True
                if accion == 'limpiar_copias' and 'vigilar' in (est.get('resultados') or {}):
                    est['resultados']['vigilar']['disco_lleno'] = False
                    cambiado = True
                if cambiado:
                    _m3.guardar_estado(est['resultados'])
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True).start()
    flash('Arreglando... puede tardar unos minutos. El resultado aparecerá debajo del aviso.', 'success')
    return redirect(volver)


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
    return render_template('equipos.html', lista=_equipos_con_estado())


def _get_system(system_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM systems WHERE id = ?', (system_id,)).fetchone()
    conn.close()
    return row


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
    return render_template('equipo.html', s=row, est=est, copias=copias, trabajos=agentes.trabajos_de(row['id'], 5),
                           prueba=_mant.leer_pruebas().get(row['hostname'].lower()),
                           horas_sin_copia=agentes.horas_sin_copia(row),
                           horas_propias=agentes.notas_equipo(row).get('horas_sin_copia'),
                           completa_activa=bool(agentes.notas_equipo(row).get('copia_completa')),
                           ultima_completa=next((c for c in copias if 'completa' in (c.get('tags') or [])), None),
                           limpia=_inc.ultima_limpia(copias) if any(c['sospechosa'] for c in copias) else None,
                           pasos=_ban.leer(equipo=row['hostname'], limite=12))


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
            _notificar_incidente('prueba_fallida', _av.texto('OCT-EQ-05', equipo=row['hostname'], detalle=r['detalle']))

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
    return {'limite_kbps': aj['limite_kbps'], 'solo_horario': aj['solo_horario'],
            'copia_completa': bool(agentes.notas_equipo(row).get('copia_completa')), 'copia_completa_dias': 7,
            'senuelos': config_manager.get_config('senuelos') is not False}


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
            _notificar_incidente('backup_failed', _av.texto('OCT-EQ-04', equipo=nombre, detalle=motivo))
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
    if not puede_actuar():
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
                           (nombre, ip or '', so, json.dumps({'rutas': rutas})))
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
    return render_template('equipo_nuevo.html', rutas_defecto=alta_equipos.RUTAS_POR_DEFECTO)


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
    import mantenimiento as _mant
    with get_db_connection() as c:
        kit = c.execute("SELECT timestamp FROM audit_logs WHERE action = 'RECOVERY_KIT' ORDER BY timestamp DESC LIMIT 1").fetchone()
    return render_template('ajustes.html', user=user, eventos=eventos, https=USE_HTTPS, cfg=cfg,
                           mant=_mant.leer_estado(), mant_nombres=_mant.NOMBRES,
                           kit_fecha=kit['timestamp'] if kit else None,
                           ajustes_copias=_ajustes_copias(), act=_av.leer_actualizacion(),
                           act_estado=__import__('actualizar').estado(), version=_av.version_local())


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
    import mantenimiento as _mant
    texto = _mant.kit(_mant.leer_env())
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
        if error:
            conn.close()
            flash(error, 'error')
            return redirect(url_for('cambiar_password'))
        conn.execute('UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?',
                     (hash_password(nueva), user['id']))
        conn.commit()
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
import hmac as _hmac


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
_ordenes.init(DB_FILE)


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
    return jsonify({'ordenes': _ordenes.pendientes(row['hostname']), 'espera': _ordenes.INTERVALO_AGENTE,
                    'ajustes': _ajustes_agente(row)})


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
    inc_id, nuevo = _inc.crear(
        system, str(data.get('motivo', 'Ataque detectado'))[:500], data.get('evidencias', [])[:100],
        detectado=data.get('detectado'), origen='detector del agente', severidad=data.get('severidad', 'critica'),
        auto=_cfg_bool('incident_auto_response'), mantener_aislado=_cfg_bool('incident_keep_isolated'),
        contacto=config_manager.get_config('security_contact') or 'el departamento de seguridad')
    log_audit(None, 'INCIDENT_CREATED' if nuevo else 'INCIDENT_REPEAT', f'#{inc_id} {host}: {data.get("motivo", "")}'[:300], origen_ip)
    _ban.marcar('incidentes', f'Alerta del equipo: {data.get("motivo", "")} (incidente #{inc_id})', equipo=host,
                codigo='OCT-SEN-01' if 'señuelo' in str(data.get('motivo', '')).lower() else None, nivel='error')
    return jsonify({'incidente': inc_id, 'nuevo': nuevo})


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
        config_manager.set_config('backup_retention', ret, uid)
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
    config_manager.set_config('incident_auto_response', request.form.get('auto') == 'on', uid)
    config_manager.set_config('incident_keep_isolated', request.form.get('aislado') == 'on', uid)
    config_manager.set_config('sandbox_terminal', request.form.get('terminal') == 'on', uid)
    config_manager.set_config('senuelos', request.form.get('senuelos') == 'on', uid)
    contacto = (request.form.get('contacto') or '').strip()[:200] or 'el departamento de seguridad'
    config_manager.set_config('security_contact', contacto, uid)
    log_audit(uid, 'CONFIG_INCIDENTS', 'Ajustes de respuesta a ataques', request.remote_addr)
    flash('Ajustes de respuesta a ataques guardados.', 'success')
    return redirect(url_for('ajustes'))


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
    with get_db_connection() as c:
        filas = c.execute('SELECT hostname, ip_address, notes FROM systems').fetchall()
    ips = {f['ip_address']: f['hostname'] for f in filas if f['ip_address']}
    grupos = sorted({(json.loads(f['notes'] or '{}') or {}).get('grupo', '') for f in filas} - {''})
    return ips, grupos, {f['hostname'].lower() for f in filas}


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
        _, _, nombres_usados = _conocidos()
        trabajos = []
        for i, (grupo, equipos_g) in enumerate(e['grupos'].items()):
            usuario = (request.form.get(f'usuario_{i}') or '').strip()
            password = request.form.get(f'password_{i}') or ''
            solo_clave = request.form.get(f'solo_clave_{i}') == 'on'
            for q in equipos_g:
                if q['nombre'].lower() in nombres_usados:
                    trabajos.append({'nombre': q['nombre'], 'ip': q['ip'], 'grupo': grupo, 'job': None,
                                     'mensaje': 'Ya existía un equipo con ese nombre: no se ha tocado.'})
                    continue
                rutas = alta_equipos.RUTAS_POR_DEFECTO.get(q['so'], [])
                conn = get_db_connection()
                cur = conn.execute("INSERT INTO systems (hostname, ip_address, os_family, status, notes) VALUES (?, ?, ?, 'unknown', ?)",
                                   (q['nombre'], q['ip'], q['so'], json.dumps({'rutas': rutas, 'grupo': grupo})))
                conn.commit()
                sid = cur.lastrowid
                conn.close()
                nombres_usados.add(q['nombre'].lower())
                log_audit(session['user_id'], 'SYSTEM_ADD', f'{q["nombre"]} ({q["so"]}, grupo {grupo}, desde «Buscar equipos»)',
                          request.remote_addr)
                if not usuario or (not password and q['so'] == 'windows'):
                    trabajos.append({'nombre': q['nombre'], 'ip': q['ip'], 'grupo': grupo, 'job': None, 'sid': sid,
                                     'mensaje': 'Dado de alta. Falta instalarlo: no se escribió usuario/contraseña para su grupo. '
                                                'Usa «Instalar» en su ficha.'})
                    continue
                if not q['ssh']:
                    trabajos.append({'nombre': q['nombre'], 'ip': q['ip'], 'grupo': grupo, 'job': None, 'sid': sid,
                                     'mensaje': ('No tiene SSH activado, así que no se puede instalar a distancia. '
                                                 + ('En Windows: activa el «Servidor OpenSSH» o usa el instalador de doble clic de su ficha.'
                                                    if q['so'] == 'windows' else 'Activa SSH en el equipo o usa el instalador de su ficha.'))})
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