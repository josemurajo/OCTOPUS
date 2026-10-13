#!/usr/bin/env python3
"""
ZeroTouch - Sistema de Notificaciones
Envía alertas por email usando SMTP
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

class NotificationManager:
    """Gestor de notificaciones por email"""
    
    def __init__(self, config_manager):
        self.config = config_manager
        
    def send_email(self, to_email, subject, body, is_html=False):
        """Envía email usando SMTP"""
        config = self.config.get_config()
        
        # Verificar si SMTP está habilitado
        if not config.get('smtp_enabled', False):
            print(f"[NOTIFICATION] SMTP deshabilitado - Email no enviado: {subject}")
            return False, "SMTP deshabilitado"
        
        # Obtener configuración SMTP
        smtp_server = config.get('smtp_server', 'smtp.gmail.com')
        smtp_port = config.get('smtp_port', 587)
        smtp_username = config.get('smtp_username', '')
        smtp_password = config.get('smtp_password', '')
        smtp_from = config.get('smtp_from', config.get('alert_email', 'noreply@zerotouch.local'))
        smtp_use_tls = config.get('smtp_use_tls', True)
        
        if not smtp_username or not smtp_password:
            print(f"[NOTIFICATION] Credenciales SMTP no configuradas - Email no enviado: {subject}")
            return False, "Credenciales SMTP no configuradas"
        
        try:
            # Crear mensaje
            msg = MIMEMultipart('alternative')
            msg['From'] = smtp_from
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Agregar cuerpo
            if is_html:
                msg.attach(MIMEText(body, 'html'))
            else:
                msg.attach(MIMEText(body, 'plain'))
            
            # Conectar y enviar
            context = ssl.create_default_context()
            
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if smtp_use_tls:
                    server.starttls(context=context)
                
                server.login(smtp_username, smtp_password)
                server.send_message(msg)
            
            print(f"[NOTIFICATION] Email enviado exitosamente: {subject} -> {to_email}")
            return True, "Email enviado exitosamente"
            
        except Exception as e:
            print(f"[NOTIFICATION] Error enviando email: {e}")
            return False, f"Error: {str(e)}"
    
    # Gravedad de cada tipo de aviso (los niveles que se eligen en el panel son critical/high/medium/low)
    LEVELS = {'incidente': 'critical', 'incident': 'critical', 'critical': 'critical',
              'backup_failed': 'high', 'restauracion': 'high', 'prueba_fallida': 'high', 'mantenimiento': 'high', 'senuelo': 'critical', 'high': 'high', 'medium': 'medium', 'low': 'low', 'test': 'test'}

    def send_alert(self, alert_type, details, recipients=None, level=None):
        """Envía alerta del sistema (respeta los niveles elegidos en el panel; 'test' siempre se envía)"""
        config = self.config.get_config()
        level = (level or self.LEVELS.get(str(alert_type).lower(), 'medium')).lower()
        
        # Verificar si las notificaciones están habilitadas
        if not config.get('email_notifications', False) and level != 'test':
            print(f"[NOTIFICATION] Notificaciones deshabilitadas - Alerta no enviada: {alert_type}")
            return False, "Notificaciones deshabilitadas"
        
        # Determinar si esta alerta debe enviarse según el nivel
        notification_levels = config.get('notification_levels', ['critical', 'high'])
        if level != 'test' and level not in notification_levels:
            print(f"[NOTIFICATION] Nivel de alerta no configurado para envío: {alert_type}")
            return False, "Nivel de alerta no configurado"
        
        # Determinar destinatarios: los elegidos para este tipo de aviso (Ajustes -> Avisos) o el correo general
        if recipients is None:
            recipients = self.destinatarios(alert_type, config)
        
        if not recipients or recipients == ['']:
            print(f"[NOTIFICATION] No hay destinatarios configurados")
            return False, "No hay destinatarios configurados"
        
        # Crear subject y body según tipo de alerta
        nombres = {'critical': 'CRÍTICA', 'high': 'ALTA', 'medium': 'MEDIA', 'low': 'BAJA', 'test': 'PRUEBA'}
        subject = f"[OCTOPUS] Alerta {nombres.get(level, level.upper())}: {str(details).splitlines()[0][:80] if details else alert_type}"
        
        body = f"""
Alerta de Seguridad - OCTOPUS Zero-Touch
=========================================

Tipo: {alert_type}   Gravedad: {nombres.get(level, level)}
Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Detalles:
{details}

=========================================
Este es un mensaje automático de OCTOPUS Zero-Touch
No responda a este email.
"""
        
        # Enviar a todos los destinatarios
        success_count = 0
        for recipient in recipients:
            success, message = self.send_email(recipient, subject, body)
            if success:
                success_count += 1
        
        if success_count == len(recipients):
            return True, f"Alerta enviada a {success_count} destinatarios"
        else:
            return False, f"Alerta enviada a {success_count}/{len(recipients)} destinatarios"
    
    # Tipos de aviso agrupados para elegir quien recibe cada grupo
    CATEGORIAS = {'incidente': 'ataques', 'incident': 'ataques', 'critical': 'ataques', 'senuelo': 'ataques',
                  'backup_failed': 'copias', 'restauracion': 'copias', 'prueba_fallida': 'copias',
                  'mantenimiento': 'servidor', 'informe': 'informe'}
    NOMBRES_CATEGORIAS = {'ataques': 'Ataques e incidentes', 'copias': 'Copias y recuperaciones',
                          'servidor': 'Servidor y mantenimiento', 'informe': 'Informe mensual'}

    def destinatarios(self, alert_type, config=None):
        """Correos que reciben este tipo de aviso. Si para su grupo no se ha elegido a nadie, el correo general."""
        import json as _json
        config = config or self.config.get_config()
        por_tipo = config.get('avisos_destinatarios') or {}
        if isinstance(por_tipo, str):
            try:
                por_tipo = _json.loads(por_tipo or '{}')
            except ValueError:
                por_tipo = {}
        cat = self.CATEGORIAS.get(str(alert_type).lower())
        lista = [c.strip() for c in str((por_tipo or {}).get(cat) or '').replace(';', ',').split(',') if c.strip()]
        return lista or [config.get('alert_email', '')]

def main():
    """Función principal para pruebas"""
    from config_manager import ConfigManager
    
    config_manager = ConfigManager()
    notification_manager = NotificationManager(config_manager)
    
    # Prueba de envío de alerta
    print("Enviando alerta de prueba...")
    success, message = notification_manager.send_alert(
        alert_type="critical",
        details="Prueba de alerta desde OCTOPUS Zero-Touch"
    )
    print(f"Resultado: {success} - {message}")

if __name__ == "__main__":
    main()
