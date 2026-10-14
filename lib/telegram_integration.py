#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
ZeroTouch - Integración con Telegram
Envía alertas por Telegram usando Bot API
"""

import requests
import json
from datetime import datetime
from typing import List, Optional

class TelegramIntegration:
    """Integración con Telegram Bot API"""
    
    def __init__(self, config_manager):
        self.config = config_manager
        self.bot_token = None
        self.chat_id = None
        self._load_config()
    
    def _load_config(self):
        """Carga configuración de Telegram"""
        config = self.config.get_config()
        
        telegram_bot_token = config.get('telegram_bot_token', '')
        telegram_chat_id = config.get('telegram_chat_id', '')
        
        self.bot_token = telegram_bot_token
        self.chat_id = telegram_chat_id
    
    def is_configured(self):
        """Verifica si Telegram está configurado (relee la configuracion: los cambios del panel valen al momento)"""
        self._load_config()
        return bool(self.bot_token and self.chat_id)
    
    def send_message(self, message: str, parse_mode: str = 'HTML') -> dict:
        """Envía mensaje por Telegram"""
        if not self.is_configured():
            return {'success': False, 'error': 'Telegram no está configurado'}
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            
            response = requests.post(url, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    return {'success': True, 'message_id': result['result']['message_id']}
                else:
                    return {'success': False, 'error': result.get('description', 'Error desconocido')}
            else:
                return {'success': False, 'error': f'Error {response.status_code}: {response.text}'}
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    LEVELS = {'incidente': 'critical', 'incident': 'critical', 'critical': 'critical',
              'backup_failed': 'high', 'restauracion': 'high', 'prueba_fallida': 'high', 'mantenimiento': 'high', 'senuelo': 'critical', 'acceso': 'high', 'high': 'high', 'medium': 'medium', 'low': 'low', 'test': 'test'}

    def send_alert(self, alert_type: str, details: str, include_timestamp: bool = True, level: str = None) -> dict:
        """Envía alerta formateada por Telegram"""
        import html as _html
        config = self.config.get_config()
        level = (level or self.LEVELS.get(str(alert_type).lower(), 'medium')).lower()
        
        # Verificar si Telegram está habilitado
        if not config.get('telegram_enabled', False):
            return {'success': False, 'error': 'Telegram deshabilitado'}
        
        # Verificar si este nivel de alerta debe enviarse
        notification_levels = config.get('telegram_notification_levels', ['critical', 'high'])
        if level != 'test' and level not in notification_levels:
            return {'success': False, 'error': 'Nivel de alerta no configurado para Telegram'}
        details = _html.escape(str(details))  # Telegram rechaza el mensaje si hay '<' o '&' sin escapar
        alert_type = level
        
        # Formatear mensaje
        emoji = {
            'critical': '🚨',
            'high': '⚠️',
            'medium': 'ℹ️',
            'low': '📌',
            'test': '🧪'
        }.get(alert_type.lower(), '📢')
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if include_timestamp else ''
        
        message = f"""
{emoji} <b>Alerta OCTOPUS Zero-Touch</b>

<b>Tipo:</b> {alert_type.upper()}
<b>Fecha:</b> {timestamp}

<b>Detalles:</b>
<pre>{details}</pre>

<i>Este es un mensaje automático de OCTOPUS Zero-Touch</i>
"""
        
        return self.send_message(message)
    
    def test_connection(self) -> dict:
        """Prueba la conexión con Telegram"""
        if not self.is_configured():
            return {'success': False, 'error': 'Telegram no está configurado'}
        
        message = f"""
✅ <b>Prueba de Conexión OCTOPUS</b>

<b>Fecha:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<i>Si recibes este mensaje, la integración con Telegram funciona correctamente.</i>
"""
        
        return self.send_message(message)
    
    def get_bot_info(self) -> dict:
        """Obtiene información del bot"""
        if not self.bot_token:
            return {'success': False, 'error': 'Bot token no configurado'}
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    return {'success': True, 'bot_info': result['result']}
                else:
                    return {'success': False, 'error': result.get('description')}
            else:
                return {'success': False, 'error': f'Error {response.status_code}'}
        
        except Exception as e:
            return {'success': False, 'error': str(e)}

def main():
    """Función principal para pruebas"""
    from config_manager import ConfigManager
    
    config_manager = ConfigManager()
    telegram = TelegramIntegration(config_manager)
    
    print("=== Integración con Telegram ===")
    print()
    
    if telegram.is_configured():
        print("Telegram está configurado")
        
        # Probar conexión
        print("Enviando mensaje de prueba...")
        result = telegram.test_connection()
        print(f"Resultado: {result}")
        
    else:
        print("Telegram no está configurado")
        print("Configura telegram_bot_token y telegram_chat_id")

if __name__ == "__main__":
    main()
