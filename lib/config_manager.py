#!/usr/bin/env python3
"""
ZeroTouch - Gestor de Configuración Personalizable
Permite personalización de tiempos, políticas y reglas del sistema
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta
from enum import Enum

class BackupFrequency(Enum):
    """Frecuencia de backups"""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"

class BackupRetention(Enum):
    """Retención de backups"""
    DAILY_7 = "daily_7"
    DAILY_30 = "daily_30"
    DAILY_90 = "daily_90"
    WEEKLY_4 = "weekly_4"
    WEEKLY_12 = "weekly_12"
    MONTHLY_3 = "monthly_3"
    MONTHLY_12 = "monthly_12"
    CUSTOM = "custom"

class ResponseLevel(Enum):
    """Nivel de respuesta automática"""
    PARANOID = "paranoid"  # Todo requiere aprobación manual
    CONSERVATIVE = "conservative"  # Solo amenazas críticas
    BALANCED = "balanced"  # Amenazas nivel medio+
    AGGRESSIVE = "aggressive"  # Cualquier alerta

class ConfigManager:
    """Gestor de configuración personalizable"""
    
    # Configuración por defecto
    DEFAULT_CONFIG = {
        # Backup configuration
        "backup_frequency": BackupFrequency.DAILY.value,
        "backup_time": "20:00",
        "backup_retention": BackupRetention.DAILY_30.value,
        "backup_compression": True,
        "backup_encryption": True,
        
        # Security response
        "response_level": ResponseLevel.BALANCED.value,
        "isolation_time": 0,  # minutos antes de aislar
        "isolation_method": "automatic",
        "auto_restore": True,
        "restore_approval": True,
        
        # Monitoring
        "monitoring_interval": 60,  # segundos
        "alert_threshold": 7,  # nivel de alerta Wazuh
        "watchdog_enabled": True,
        
        # Network
        "auto_discovery": True,
        "discovery_interval": 3600,  # segundos
        "scan_networks": True,
        
        # Network Access (Configurable desde web)
        "bind_to_localhost": True,  # True = solo localhost, False = todas las IPs
        "allowed_ips": [],  # Lista de IPs permitidas (vacío = todas)
        "minio_port": "0.0.0.0",  # 0.0.0.0 = localhost, 0.0.0.0 = todas
        "n8n_port": "0.0.0.0",
        "wg_easy_port": "0.0.0.0",
        
        # Wazuh SIEM Integration
        "wazuh_enabled": False,
        "wazuh_url": "",
        "wazuh_api_key": "",
        "wazuh_verify_ssl": True,
        "wazuh_alert_level_min": 7,
        
        # Notifications
        "email_notifications": True,
        "smtp_enabled": False,
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_username": "",
        "smtp_password": "",
        "smtp_from": "",
        "smtp_use_tls": True,
        "alert_email": "",
        "notification_levels": ["critical", "high"],
        
        # Telegram
        "telegram_enabled": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "telegram_notification_levels": ["critical", "high"],
        
        # Retention
        "log_retention_days": 90,
        "audit_log_retention_days": 365,
        "backup_clean_enabled": True,
        
        # Performance
        "max_concurrent_backups": 5,
        "backup_timeout": 3600,  # segundos
        "snapshot_verification": True,
        
        # Respuesta a incidentes criticos
        "incident_auto_response": True,      # aislar + copia forense + restaurar + avisar automaticamente
        "incident_keep_isolated": True,      # el equipo sigue aislado hasta que seguridad lo libere
        "security_contact": "el departamento de seguridad",
        "sandbox_terminal": True,            # permitir comandos en la sala de analisis (solo administradores)

        # Velocidad de las copias (para no saturar la red): 0 = sin limite. En KB/s.
        "copias_limite_kbps": 0,
        "copias_limite_solo_horario": True,  # limitar solo de lunes a viernes de 8:00 a 20:00 (hora del equipo)

        # Informe mensual por correo el dia 1
        "informe_mensual": True,

        # Custom paths
        "protected_paths": {
            "windows": ["C:\\Users", "C:\\Program Files", "C:\\Windows"],
            "linux": ["/home", "/etc", "/var/www", "/opt"],
            "macos": ["/Users", "/Applications", "/Library", "/etc"]
        },
        
        "excluded_paths": {
            "windows": ["C:\\Windows\\Temp", "C:\\Users\\*\\AppData\\Local\\Temp"],
            "linux": ["/tmp", "/var/tmp", "/proc", "/sys"],
            "macos": ["/tmp", "/private/tmp"]
        }
    }
    
    def __init__(self, db_path=None):
        """Inicializa el gestor de configuración"""
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base_dir, "data", "admin_panel.db")
        
        self.db_path = db_path
        self._init_config_table()
    
    def get_db_connection(self):
        """Obtiene conexión a la base de datos"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_config_table(self):
        """Inicializa tabla de configuración"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                type TEXT DEFAULT 'string',
                description TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by INTEGER
            )
        ''')
        
        # Insertar configuración por defecto si no existe
        for key, value in self.DEFAULT_CONFIG.items():
            cursor.execute('''
                INSERT OR IGNORE INTO config (key, value, type)
                VALUES (?, ?, ?)
            ''', (key, json.dumps(value), self._get_value_type(value)))
        
        conn.commit()
        conn.close()
    
    def _get_value_type(self, value):
        """Determina el tipo de valor"""
        if isinstance(value, bool):
            return "boolean"
        elif isinstance(value, int):
            return "integer"
        elif isinstance(value, float):
            return "float"
        elif isinstance(value, (list, dict)):
            return "json"
        else:
            return "string"
    
    def get_config(self, key=None):
        """Obtiene configuración"""
        conn = self.get_db_connection()
        
        if key:
            row = conn.execute('SELECT * FROM config WHERE key = ?', (key,)).fetchone()
            conn.close()
            
            if not row:
                return self.DEFAULT_CONFIG.get(key)
            
            return self._parse_value(row['value'], row['type'])
        else:
            rows = conn.execute('SELECT * FROM config').fetchall()
            conn.close()
            
            config = {}
            for row in rows:
                config[row['key']] = self._parse_value(row['value'], row['type'])
            
            return config
    
    def _parse_value(self, value, value_type):
        """Parsea valor según tipo"""
        if value_type == "boolean":
            return value.lower() == "true"
        elif value_type == "integer":
            return int(value)
        elif value_type == "float":
            return float(value)
        elif value_type == "json":
            return json.loads(value)
        else:
            # set_config guarda los textos con json.dumps ("asi"): se quitan esas comillas al leer.
            # Si no, el correo de los avisos salia como "tu@correo.com" (con comillas) y no llegaba.
            if isinstance(value, str) and len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                try:
                    v = json.loads(value)
                    if isinstance(v, str):
                        return v
                except ValueError:
                    pass
            return value
    
    def set_config(self, key, value, user_id=None):
        """Establece valor de configuración"""
        conn = self.get_db_connection()
        
        # Verificar que la clave existe
        if key not in self.DEFAULT_CONFIG:
            conn.close()
            return False, "Configuración no válida"
        
        # Validar valor según tipo esperado
        expected_type = type(self.DEFAULT_CONFIG[key])
        if not isinstance(value, expected_type):
            try:
                if expected_type == bool:
                    value = str(value).lower() == "true"
                elif expected_type == int:
                    value = int(value)
                elif expected_type == float:
                    value = float(value)
                elif expected_type in (list, dict):
                    value = json.loads(value)
            except (ValueError, json.JSONDecodeError):
                conn.close()
                return False, f"Valor inválido para {key}"
        
        conn.execute('''
            UPDATE config 
            SET value = ?, type = ?, updated_at = ?, updated_by = ?
            WHERE key = ?
        ''', (json.dumps(value), self._get_value_type(value), datetime.now(), user_id, key))
        
        conn.commit()
        conn.close()
        
        return True, "Configuración actualizada"
    
    def reset_config(self, key=None):
        """Restablece configuración a valores por defecto"""
        conn = self.get_db_connection()
        
        if key:
            if key in self.DEFAULT_CONFIG:
                value = self.DEFAULT_CONFIG[key]
                conn.execute('''
                    UPDATE config 
                    SET value = ?, type = ?, updated_at = ?
                    WHERE key = ?
                ''', (json.dumps(value), self._get_value_type(value), datetime.now(), key))
        else:
            for key, value in self.DEFAULT_CONFIG.items():
                conn.execute('''
                    UPDATE config 
                    SET value = ?, type = ?, updated_at = ?
                    WHERE key = ?
                ''', (json.dumps(value), self._get_value_type(value), datetime.now(), key))
        
        conn.commit()
        conn.close()
        
        return True, "Configuración restablecida"
    
    def get_backup_schedule(self):
        """Obtiene configuración de programación de backups"""
        config = self.get_config()
        
        frequency = config.get("backup_frequency", BackupFrequency.DAILY.value)
        time = config.get("backup_time", "20:00")
        
        # Calcular próximo backup
        now = datetime.now()
        
        if frequency == BackupFrequency.HOURLY.value:
            next_backup = now + timedelta(hours=1)
        elif frequency == BackupFrequency.DAILY.value:
            hour, minute = map(int, time.split(':'))
            next_backup = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_backup <= now:
                next_backup += timedelta(days=1)
        elif frequency == BackupFrequency.WEEKLY.value:
            # Próximo domingo a la hora especificada
            hour, minute = map(int, time.split(':'))
            next_backup = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            days_until_sunday = (6 - now.weekday()) % 7
            if days_until_sunday == 0 and next_backup <= now:
                days_until_sunday = 7
            next_backup += timedelta(days=days_until_sunday)
        elif frequency == BackupFrequency.MONTHLY.value:
            # Primer día del próximo mes
            hour, minute = map(int, time.split(':'))
            next_backup = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
            if next_backup <= now:
                if now.month == 12:
                    next_backup = next_backup.replace(year=now.year + 1, month=1)
                else:
                    next_backup = next_backup.replace(month=now.month + 1)
        else:
            next_backup = now + timedelta(hours=1)
        
        return {
            "frequency": frequency,
            "time": time,
            "next_backup": next_backup.isoformat(),
            "retention": config.get("backup_retention", BackupRetention.DAILY_30.value)
        }
    
    def get_retention_policy(self):
        """Obtiene política de retención de backups"""
        config = self.get_config()
        retention = config.get("backup_retention", BackupRetention.DAILY_30.value)
        
        policies = {
            BackupRetention.DAILY_7.value: {"daily": 7, "weekly": 0, "monthly": 0},
            BackupRetention.DAILY_30.value: {"daily": 30, "weekly": 4, "monthly": 0},
            BackupRetention.DAILY_90.value: {"daily": 90, "weekly": 12, "monthly": 3},
            BackupRetention.WEEKLY_4.value: {"daily": 7, "weekly": 4, "monthly": 0},
            BackupRetention.WEEKLY_12.value: {"daily": 7, "weekly": 12, "monthly": 3},
            BackupRetention.MONTHLY_3.value: {"daily": 7, "weekly": 4, "monthly": 3},
            BackupRetention.MONTHLY_12.value: {"daily": 7, "weekly": 4, "monthly": 12},
        }
        
        return policies.get(retention, policies[BackupRetention.DAILY_30.value])
    
    def get_security_policies(self):
        """Obtiene políticas de seguridad"""
        config = self.get_config()
        
        return {
            "response_level": config.get("response_level", ResponseLevel.BALANCED.value),
            "isolation_time": config.get("isolation_time", 0),
            "isolation_method": config.get("isolation_method", "automatic"),
            "auto_restore": config.get("auto_restore", True),
            "restore_approval": config.get("restore_approval", True),
            "alert_threshold": config.get("alert_threshold", 7),
            "watchdog_enabled": config.get("watchdog_enabled", True)
        }
    
    def validate_config_change(self, key, value):
        """Valida cambio de configuración"""
        # Validaciones específicas por clave
        if key == "backup_time":
            try:
                hour, minute = map(int, value.split(':'))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    return False, "Hora inválida"
            except (ValueError, AttributeError):
                return False, "Formato de hora inválido (use HH:MM)"
        
        elif key == "isolation_time":
            if not isinstance(value, int) or value < 0 or value > 60:
                return False, "Tiempo de aislamiento debe ser 0-60 minutos"
        
        elif key == "alert_threshold":
            if not isinstance(value, int) or value < 1 or value > 15:
                return False, "Umbral de alerta debe ser 1-15"
        
        elif key == "backup_frequency":
            valid_frequencies = [freq.value for freq in BackupFrequency]
            if value not in valid_frequencies:
                return False, f"Frecuencia inválida. Opciones: {valid_frequencies}"
        
        elif key == "response_level":
            valid_levels = [level.value for level in ResponseLevel]
            if value not in valid_levels:
                return False, f"Nivel de respuesta inválido. Opciones: {valid_levels}"
        
        return True, "Validación exitosa"

def main():
    """Función principal para pruebas"""
    print(" ZeroTouch - Gestor de Configuración Personalizable")
    print("=" * 50)
    
    manager = ConfigManager()
    
    # Mostrar configuración actual
    print("\n Configuración Actual:")
    print("-" * 50)
    config = manager.get_config()
    
    for key, value in config.items():
        print(f"{key}: {value}")
    
    # Mostrar programación de backups
    print("\n Programación de Backups:")
    print("-" * 50)
    schedule = manager.get_backup_schedule()
    for key, value in schedule.items():
        print(f"{key}: {value}")
    
    # Mostrar políticas de seguridad
    print("\n Políticas de Seguridad:")
    print("-" * 50)
    policies = manager.get_security_policies()
    for key, value in policies.items():
        print(f"{key}: {value}")

if __name__ == "__main__":
    main()