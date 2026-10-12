#!/usr/bin/env python3
"""
ZeroTouch - API REST
API para integración con herramientas externas y automatización
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify
from functools import wraps
import hashlib
import secrets

# Agregar directorio lib al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import ConfigManager
from notifications import NotificationManager
from intelligent_detection import IntelligentDetection
from wazuh_integration import WazuhIntegration
from telegram_integration import TelegramIntegration
import socket

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

# Directorios
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv():
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()
DB_FILE = os.environ.get('DB_PATH', os.path.join(BASE_DIR, "data", "admin_panel.db"))
if not os.path.isabs(DB_FILE):
    DB_FILE = os.path.join(BASE_DIR, DB_FILE)
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

# Instancias
config_manager = ConfigManager(DB_FILE)
notification_manager = NotificationManager(config_manager)
intelligent_detector = IntelligentDetection(DB_FILE)
wazuh_integration = WazuhIntegration(config_manager)

# ========================================
# AUTENTICACIÓN API
# ========================================

def api_key_required(f):
    """Decorador para requerir API key"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        
        if not api_key:
            return jsonify({'error': 'API key requerida'}), 401
        
        # Verificar API key en base de datos
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM api_keys WHERE api_key = ? AND expires_at > ?', 
                      (api_key, datetime.now()))
        key_record = cursor.fetchone()
        
        conn.close()
        
        if not key_record:
            return jsonify({'error': 'API key inválida o expirada'}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function

def init_api_keys_table():
    """Inicializa tabla de API keys"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            created_by INTEGER,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# ========================================
# ENDPOINTS DE CONFIGURACIÓN
# ========================================

@app.route('/api/v1/config', methods=['GET'])
@api_key_required
def get_config():
    """Obtiene configuración del sistema"""
    config = config_manager.get_config()
    
    # Remover datos sensibles
    safe_config = {k: v for k, v in config.items() 
                   if 'password' not in k.lower() and 'key' not in k.lower()}
    
    return jsonify({
        'success': True,
        'config': safe_config
    })

@app.route('/api/v1/config/<key>', methods=['GET'])
@api_key_required
def get_config_key(key):
    """Obtiene un valor de configuración específico"""
    config = config_manager.get_config()
    
    if key not in config:
        return jsonify({'error': 'Configuración no encontrada'}), 404
    
    # Remover datos sensibles
    if 'password' in key.lower() or 'key' in key.lower():
        return jsonify({'error': 'No se puede acceder a datos sensibles'}), 403
    
    return jsonify({
        'success': True,
        'key': key,
        'value': config[key]
    })

@app.route('/api/v1/config/<key>', methods=['PUT'])
@api_key_required
def update_config_key(key):
    """Actualiza un valor de configuración"""
    data = request.get_json()
    value = data.get('value')
    
    if value is None:
        return jsonify({'error': 'Valor requerido'}), 400
    
    valid, message = config_manager.validate_config_change(key, value)
    if not valid:
        return jsonify({'error': message}), 400
    
    success, message = config_manager.set_config(key, value)
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'error': message}), 400

# ========================================
# ENDPOINTS DE SISTEMAS
# ========================================

@app.route('/api/v1/systems', methods=['GET'])
@api_key_required
def get_systems():
    """Obtiene todos los sistemas"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    systems = cursor.execute('SELECT * FROM systems ORDER BY hostname').fetchall()
    
    conn.close()
    
    return jsonify({
        'success': True,
        'systems': [dict(row) for row in systems]
    })

@app.route('/api/v1/systems', methods=['POST'])
@api_key_required
def add_system():
    """Agrega un nuevo sistema"""
    data = request.get_json()
    
    hostname = data.get('hostname')
    ip_address = data.get('ip_address')
    os_family = data.get('os_family')
    os_version = data.get('os_version', '')
    
    if not all([hostname, ip_address, os_family]):
        return jsonify({'error': 'hostname, ip_address y os_family son requeridos'}), 400
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO systems (hostname, ip_address, os_family, os_version, status)
        VALUES (?, ?, ?, ?, 'unknown')
    ''', (hostname, ip_address, os_family, os_version))
    
    conn.commit()
    system_id = cursor.lastrowid
    conn.close()
    
    return jsonify({
        'success': True,
        'system_id': system_id,
        'message': 'Sistema agregado'
    })

@app.route('/api/v1/systems/<int:system_id>', methods=['DELETE'])
@api_key_required
def delete_system(system_id):
    """Elimina un sistema"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM systems WHERE id = ?', (system_id,))
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': 'Sistema eliminado'
    })

# ========================================
# ENDPOINTS DE BACKUPS
# ========================================

@app.route('/api/v1/backups/schedule', methods=['GET'])
@api_key_required
def get_backup_schedule():
    """Obtiene programación de backups"""
    schedule = config_manager.get_backup_schedule()
    
    return jsonify({
        'success': True,
        'schedule': schedule
    })

@app.route('/api/v1/backups/retention', methods=['GET'])
@api_key_required
def get_backup_retention():
    """Obtiene política de retención"""
    retention = config_manager.get_retention_policy()
    
    return jsonify({
        'success': True,
        'retention': retention
    })

# ========================================
# ENDPOINTS DE DETECCIÓN
# ========================================

@app.route('/api/v1/detection/analyze', methods=['POST'])
@api_key_required
def analyze_change():
    """Analiza un cambio de archivo"""
    data = request.get_json()
    
    file_path = data.get('file_path')
    change_type = data.get('change_type', 'modify')
    user = data.get('user', '')
    process = data.get('process', '')
    
    if not file_path:
        return jsonify({'error': 'file_path es requerido'}), 400
    
    result = intelligent_detector.analyze_change(file_path, change_type, user, process)
    
    return jsonify({
        'success': True,
        'analysis': result
    })

@app.route('/api/v1/detection/whitelist', methods=['GET'])
@api_key_required
def get_whitelist():
    """Obtiene whitelist de cambios permitidos"""
    whitelist = intelligent_detector.get_whitelist()
    
    return jsonify({
        'success': True,
        'whitelist': [dict(row) for row in whitelist]
    })

@app.route('/api/v1/detection/whitelist', methods=['POST'])
@api_key_required
def add_whitelist():
    """Agrega entrada a whitelist"""
    data = request.get_json()
    
    file_path = data.get('file_path')
    pattern = data.get('pattern', '')
    user = data.get('user', '')
    process = data.get('process', '')
    reason = data.get('reason', '')
    expires_days = data.get('expires_days')
    
    if not file_path and not pattern:
        return jsonify({'error': 'file_path o pattern es requerido'}), 400
    
    expires_days = int(expires_days) if expires_days else None
    
    success, message = intelligent_detector.add_to_whitelist(
        file_path, pattern, user, process, reason, expires_days
    )
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'error': message}), 400

# ========================================
# ENDPOINTS DE NOTIFICACIONES
# ========================================

@app.route('/api/v1/notifications/send', methods=['POST'])
@api_key_required
def send_notification():
    """Envía una notificación"""
    data = request.get_json()
    
    alert_type = data.get('alert_type')
    details = data.get('details', '')
    recipients = data.get('recipients')
    
    if not alert_type:
        return jsonify({'error': 'alert_type es requerido'}), 400
    
    success, message = notification_manager.send_alert(alert_type, details, recipients)
    
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'error': message}), 400

# ========================================
# ENDPOINTS DE WAZUH
# ========================================

@app.route('/api/v1/wazuh/alerts', methods=['GET'])
@api_key_required
def get_wazuh_alerts():
    """Obtiene alertas de Wazuh"""
    hours = request.args.get('hours', 24, type=int)
    level_min = request.args.get('level_min', 7, type=int)
    level_max = request.args.get('level_max', 15, type=int)
    
    result = wazuh_integration.get_alerts(hours, level_min, level_max)
    
    return jsonify(result)

@app.route('/api/v1/wazuh/critical', methods=['GET'])
@api_key_required
def get_wazuh_critical():
    """Obtiene alertas críticas de Wazuh"""
    hours = request.args.get('hours', 1, type=int)
    
    result = wazuh_integration.get_critical_alerts(hours)
    
    return jsonify(result)

@app.route('/api/v1/wazuh/agents', methods=['GET'])
@api_key_required
def get_wazuh_agents():
    """Obtiene estado de agentes Wazuh"""
    result = wazuh_integration.get_agent_status()
    
    return jsonify(result)

# ========================================
# ENDPOINTS DE API KEYS
# ========================================

@app.route('/api/v1/keys', methods=['GET'])
@api_key_required
def get_api_keys():
    """Obtiene todas las API keys (solo lectura del propio usuario)"""
    # En una implementación real, verificaría el usuario
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    keys = cursor.execute('SELECT id, name, created_at, expires_at FROM api_keys').fetchall()
    
    conn.close()
    
    return jsonify({
        'success': True,
        'keys': [dict(row) for row in keys]
    })

@app.route('/api/v1/keys', methods=['POST'])
@api_key_required
def create_api_key():
    """Crea una nueva API key"""
    data = request.get_json()
    
    name = data.get('name')
    expires_days = data.get('expires_days')
    
    if not name:
        return jsonify({'error': 'name es requerido'}), 400
    
    # Generar API key
    api_key = secrets.token_hex(32)
    
    expires_at = None
    if expires_days:
        expires_at = datetime.now() + timedelta(days=int(expires_days))
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO api_keys (name, api_key, expires_at)
        VALUES (?, ?, ?)
    ''', (name, api_key, expires_at))
    
    conn.commit()
    key_id = cursor.lastrowid
    conn.close()
    
    return jsonify({
        'success': True,
        'key_id': key_id,
        'api_key': api_key,
        'expires_at': expires_at.isoformat() if expires_at else None
    })

# ========================================
# ENDPOINT DE SALUD
# ========================================

@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """Verifica salud del API"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

# ========================================
# ENDPOINTS DE RED Y DESPLIEGUE
# ========================================

@app.route('/api/v1/network/local-ip', methods=['GET'])
@api_key_required
def get_local_ip():
    """Obtiene IP local del servidor"""
    try:
        # Intentar conectar a un servidor externo para obtener IP local
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        
        return jsonify({
            'success': True,
            'ip': local_ip
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/v1/services/status', methods=['GET'])
@api_key_required
def get_services_status():
    """Obtiene estado de servicios Docker"""
    try:
        import subprocess
        
        install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        compose_file = os.path.join(install_dir, 'install', 'docker-compose.yml')
        
        result = subprocess.run(
            _compose_cmd() + ['-f', compose_file, 'ps'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            # Parsear salida
            services = {}
            lines = result.stdout.split('\n')
            for line in lines:
                if 'minio' in line.lower():
                    services['minio'] = 'running' if 'Up' in line else 'stopped'
                elif 'n8n' in line.lower():
                    services['n8n'] = 'running' if 'Up' in line else 'stopped'
                elif 'wg-easy' in line.lower():
                    services['wg-easy'] = 'running' if 'Up' in line else 'stopped'
            
            return jsonify({
                'success': True,
                'services': services
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/v1/services/start', methods=['POST'])
@api_key_required
def start_services():
    """Inicia servicios Docker"""
    try:
        import subprocess
        
        install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        compose_file = os.path.join(install_dir, 'install', 'docker-compose.yml')
        
        result = subprocess.run(
            _compose_cmd() + ['-f', compose_file, 'up', '-d'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Servicios iniciados correctamente'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/v1/services/stop', methods=['POST'])
@api_key_required
def stop_services():
    """Detiene servicios Docker"""
    try:
        import subprocess
        
        install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        compose_file = os.path.join(install_dir, 'install', 'docker-compose.yml')
        
        result = subprocess.run(
            _compose_cmd() + ['-f', compose_file, 'down'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Servicios detenidos correctamente'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/api/v1/services/restart', methods=['POST'])
@api_key_required
def restart_services():
    """Reinicia servicios Docker"""
    try:
        import subprocess
        
        install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        compose_file = os.path.join(install_dir, 'install', 'docker-compose.yml')
        
        # Detener
        subprocess.run(_compose_cmd() + ['-f', compose_file, 'down'], 
                      capture_output=True, check=False)
        
        # Iniciar
        result = subprocess.run(
            _compose_cmd() + ['-f', compose_file, 'up', '-d'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Servicios reiniciados correctamente'
            })
        else:
            return jsonify({
                'success': False,
                'error': result.stderr
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

# /api/v1/deploy/auto se ha eliminado: reescribia el .env y dejaba las copias existentes sin clave.

def _compose_cmd():
    """Devuelve el comando docker compose disponible (plugin v2 o standalone)."""
    import subprocess as _sp
    base = ['docker', 'compose']
    try:
        if _sp.run(base + ['version'], capture_output=True, timeout=15).returncode != 0:
            base = ['docker-compose']
    except Exception:
        base = ['docker-compose']
    if os.name != 'nt' and os.geteuid() != 0:
        base = ['sudo', '-n'] + base
    env_file = os.path.join(BASE_DIR, '.env')
    if os.path.isfile(env_file):
        base = base + ['--env-file', env_file]
    return base


init_api_keys_table()


def main():
    """Inicia el servidor API"""
    
    print("=== OCTOPUS Zero-Touch API REST ===")
    print("API REST iniciada en http://0.0.0.0:8081")
    print()
    
    app.run(host=os.environ.get('API_BIND', '0.0.0.0'),
            port=int(os.environ.get('API_PORT', 8081)),
            debug=os.environ.get('FLASK_DEBUG', '0') == '1')

if __name__ == '__main__':
    main()
