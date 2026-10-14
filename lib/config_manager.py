#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
ZeroTouch - Gestor de Configuración Personalizable
Permite personalización de tiempos, políticas y reglas del sistema
"""

import os
import sys
import json
import sqlite3
from datetime import datetime
from enum import Enum

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

class ConfigManager:
    """Gestor de configuración personalizable"""
    
    # Configuración por defecto
    DEFAULT_CONFIG = {
        # Backup configuration
        "backup_retention": BackupRetention.DAILY_30.value,
        
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
        
        # Performance
        
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

        # Archivos señuelo en los equipos (un archivo trampa oculto por carpeta protegida)
        "senuelos": True,

        # Instalar solas (por la noche) las versiones nuevas firmadas; False = en pausa
        "actualizar_solo": True,

        # Arreglar solos los avisos sin riesgo (repetir copias, quitar bloqueos...); lo que borra datos pide permiso
        "autoarreglo": True,

        # Quien recibe cada tipo de aviso: {"ataques": "a@x, b@x", "copias": "", "servidor": "", "informe": ""}
        # (vacio = el correo general alert_email)
        "avisos_destinatarios": {},

        # Custom paths
        
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
        
        # Verificar que la clave existe (si no, se avisa en el registro: antes se ignoraba sin decir nada)
        if key not in self.DEFAULT_CONFIG:
            conn.close()
            print(f"[CONFIG] AVISO: '{key}' no es un ajuste conocido; no se guarda")
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
        
        # UPSERT: si la fila no existe (por ejemplo un ajuste nuevo aun sin sembrar), se crea; si existe, se actualiza.
        conn.execute('''
            INSERT INTO config (key, value, type, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE
            SET value = excluded.value, type = excluded.type, updated_at = excluded.updated_at, updated_by = excluded.updated_by
        ''', (key, json.dumps(value), self._get_value_type(value), datetime.now(), user_id))

        conn.commit()
        conn.close()
        
        return True, "Configuración actualizada"


# Todas las funciones de Ajustes -> Funciones (lib/funciones.py) y sus opciones son ajustes conocidos
def _anadir_funciones():
    try:
        import funciones
    except ImportError:  # por si se usa este archivo suelto
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import funciones
    for k, v in funciones.defectos().items():
        ConfigManager.DEFAULT_CONFIG.setdefault(k, v)


_anadir_funciones()
