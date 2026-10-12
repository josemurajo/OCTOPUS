#!/usr/bin/env python3
"""
ZeroTouch - Gestor de Alertas Inteligente
Implementa deduplicación, agrupación y alertas con contexto
"""

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Optional
import json

class AlertManager:
    """Gestor de alertas con deduplicación y agrupación"""
    
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_alerts_table()
        self._init_alert_rules_table()
    
    def get_db_connection(self):
        """Obtiene conexión a la base de datos"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_alerts_table(self):
        """Inicializa tabla de alertas"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT,
                context TEXT,
                action_url TEXT,
                action_label TEXT,
                system_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                acknowledged BOOLEAN DEFAULT 0,
                acknowledged_at TIMESTAMP,
                acknowledged_by INTEGER,
                deduplication_key TEXT,
                group_id INTEGER
            )
        ''')
        
        # Índice para deduplicación
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_deduplication 
            ON alerts(deduplication_key, created_at)
        ''')
        
        conn.commit()
        conn.close()
    
    def _init_alert_rules_table(self):
        """Inicializa tabla de reglas de alertas"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_type TEXT NOT NULL,
                min_severity TEXT,
                channel_email BOOLEAN DEFAULT 0,
                channel_telegram BOOLEAN DEFAULT 0,
                channel_push BOOLEAN DEFAULT 0,
                batching_window_minutes INTEGER DEFAULT 60,
                batch_only BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Insertar reglas por defecto
        cursor.execute('SELECT COUNT(*) FROM alert_rules')
        if cursor.fetchone()[0] == 0:
            default_rules = [
                ('backup_success', 'low', 0, 0, 0, 1440, 1),  # Resumen diario
                ('backup_failed', 'critical', 1, 1, 1, 5, 0),  # Inmediato
                ('backup_corrupted', 'critical', 1, 1, 1, 5, 0),  # Inmediato
                ('disk_full', 'high', 1, 1, 1, 15, 0),  # Inmediato
                ('ransomware_detected', 'critical', 1, 1, 1, 1, 0),  # Inmediato
                ('system_offline', 'medium', 0, 0, 0, 60, 1),  # Agrupado
                ('whitelist_change', 'low', 0, 0, 0, 1440, 1),  # Resumen diario
            ]
            
            for rule in default_rules:
                cursor.execute('''
                    INSERT INTO alert_rules (alert_type, min_severity, channel_email, channel_telegram, channel_push, batching_window_minutes, batch_only)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', rule)
        
        conn.commit()
        conn.close()
    
    def create_alert(self, alert_type: str, severity: str, title: str, 
                    message: str = "", context: Dict = None, 
                    action_url: str = "", action_label: str = "",
                    system_id: int = None, deduplication_key: str = None) -> int:
        """Crea una alerta con deduplicación automática"""
        
        # Generar deduplication_key si no se proporciona
        if not deduplication_key:
            deduplication_key = f"{alert_type}_{system_id or 'global'}_{title}"
        
        # Verificar si hay alerta similar reciente (deduplicación)
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        # Buscar alerta similar en los últimos 5 minutos
        cursor.execute('''
            SELECT id, created_at FROM alerts 
            WHERE deduplication_key = ? 
            AND created_at > datetime('now', '-5 minutes')
            ORDER BY created_at DESC
            LIMIT 1
        ''', (deduplication_key,))
        
        similar_alert = cursor.fetchone()
        
        if similar_alert:
            # Incrementar contador de ocurrencias (en un futuro podríamos agregar campo count)
            # Por ahora, actualizamos el timestamp para mostrar que sigue activo
            cursor.execute('''
                UPDATE alerts 
                SET created_at = CURRENT_TIMESTAMP,
                    message = ? || ' (Ocurrencia repetida)'
                WHERE id = ?
            ''', (message, similar_alert['id']))
            
            conn.commit()
            conn.close()
            return similar_alert['id']
        
        # Crear nueva alerta
        cursor.execute('''
            INSERT INTO alerts (alert_type, severity, title, message, context, action_url, action_label, system_id, deduplication_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (alert_type, severity, title, message, json.dumps(context) if context else None, 
              action_url, action_label, system_id, deduplication_key))
        
        alert_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return alert_id
    
    def get_alert_rules(self, alert_type: str) -> Dict:
        """Obtiene reglas de notificación para un tipo de alerta"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM alert_rules 
            WHERE alert_type = ?
        ''', (alert_type,))
        
        rule = cursor.fetchone()
        conn.close()
        
        if rule:
            return dict(rule)
        return None
    
    def should_notify(self, alert_type: str, severity: str) -> Dict:
        """Determina si se debe notificar y por qué canales"""
        rule = self.get_alert_rules(alert_type)
        
        if not rule:
            # Regla por defecto: solo críticas por email
            return {
                'notify': severity in ['critical', 'high'],
                'channels': ['email'] if severity in ['critical', 'high'] else [],
                'batch': False
            }
        
        # Verificar severidad mínima
        severity_order = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
        min_severity = rule['min_severity'] or 'low'
        
        if severity_order.get(severity, 0) < severity_order.get(min_severity, 0):
            return {'notify': False, 'channels': [], 'batch': False}
        
        # Determinar canales
        channels = []
        if rule['channel_email']:
            channels.append('email')
        if rule['channel_telegram']:
            channels.append('telegram')
        if rule['channel_push']:
            channels.append('push')
        
        return {
            'notify': len(channels) > 0,
            'channels': channels,
            'batch': rule['batch_only'] == 1
        }
    
    def get_batched_alerts(self, hours: int = 24) -> List[Dict]:
        """Obtiene alertas agrupadas para resumen"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cutoff = datetime.now() - timedelta(hours=hours)
        
        # Agrupar por tipo y severidad
        cursor.execute('''
            SELECT alert_type, severity, COUNT(*) as count, 
                   MAX(created_at) as last_occurrence,
                   GROUP_CONCAT(title, ', ') as titles
            FROM alerts 
            WHERE created_at > ?
            AND acknowledged = 0
            GROUP BY alert_type, severity
            ORDER BY severity_order DESC, count DESC
        ''', (cutoff,))
        
        grouped = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in grouped]
    
    def get_critical_alerts(self, hours: int = 1) -> List[Dict]:
        """Obtiene solo alertas críticas no acknowledgeadas"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cutoff = datetime.now() - timedelta(hours=hours)
        
        cursor.execute('''
            SELECT * FROM alerts 
            WHERE severity = 'critical' 
            AND acknowledged = 0
            AND created_at > ?
            ORDER BY created_at DESC
        ''', (cutoff,))
        
        alerts = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in alerts]
    
    def acknowledge_alert(self, alert_id: int, user_id: int) -> bool:
        """Marca una alerta como acknowledgeada"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE alerts 
            SET acknowledged = 1, acknowledged_at = CURRENT_TIMESTAMP, acknowledged_by = ?
            WHERE id = ?
        ''', (user_id, alert_id))
        
        conn.commit()
        conn.close()
        
        return True
    
    def get_system_health(self) -> Dict:
        """Calcula la salud general del sistema (Peace of Mind Dashboard)"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        # Alertas críticas no acknowledgeadas en las últimas 24 horas
        cursor.execute('''
            SELECT COUNT(*) FROM alerts 
            WHERE severity = 'critical' 
            AND acknowledged = 0
            AND created_at > datetime('now', '-24 hours')
        ''')
        critical_count = cursor.fetchone()[0]
        
        # Alertas altas no acknowledgeadas en las últimas 24 horas
        cursor.execute('''
            SELECT COUNT(*) FROM alerts 
            WHERE severity = 'high' 
            AND acknowledged = 0
            AND created_at > datetime('now', '-24 hours')
        ''')
        high_count = cursor.fetchone()[0]
        
        # Backups fallados en las últimas 24 horas
        cursor.execute('''
            SELECT COUNT(*) FROM alerts 
            WHERE alert_type = 'backup_failed' 
            AND created_at > datetime('now', '-24 hours')
        ''')
        backup_failed_count = cursor.fetchone()[0]
        
        # Sistemas offline
        cursor.execute('''
            SELECT COUNT(*) FROM systems 
            WHERE status = 'offline'
            AND last_seen > datetime('now', '-1 hour')
        ''')
        offline_count = cursor.fetchone()[0]
        
        conn.close()
        
        # Calcular salud general
        if critical_count > 0:
            health = 'critical'
            health_color = '#e74c3c'
            health_message = f'{critical_count} alerta(s) crítica(s) sin resolver'
        elif high_count > 5:
            health = 'warning'
            health_color = '#f39c12'
            health_message = f'{high_count} alerta(s) alta(s) sin resolver'
        elif backup_failed_count > 0:
            health = 'warning'
            health_color = '#f39c12'
            health_message = f'{backup_failed_count} backup(s) falló'
        elif offline_count > 0:
            health = 'warning'
            health_color = '#f39c12'
            health_message = f'{offline_count} sistema(s) offline'
        else:
            health = 'healthy'
            health_color = '#2ecc71'
            health_message = 'Todo funcionando correctamente'
        
        return {
            'health': health,
            'health_color': health_color,
            'health_message': health_message,
            'critical_count': critical_count,
            'high_count': high_count,
            'backup_failed_count': backup_failed_count,
            'offline_count': offline_count,
            'last_backup_health': self._get_backup_health()
        }
    
    def _get_backup_health(self) -> Dict:
        """Obtiene salud de backups"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        # Sistemas con backup reciente (últimas 24 horas)
        cursor.execute('''
            SELECT COUNT(*) FROM systems 
            WHERE last_backup > datetime('now', '-24 hours')
        ''')
        recent_backups = cursor.fetchone()[0]
        
        # Total de sistemas
        cursor.execute('SELECT COUNT(*) FROM systems')
        total_systems = cursor.fetchone()[0]
        
        conn.close()
        
        if total_systems == 0:
            return {'status': 'unknown', 'message': 'No hay sistemas'}
        
        percentage = (recent_backups / total_systems) * 100
        
        if percentage >= 90:
            return {'status': 'healthy', 'percentage': percentage, 'message': f'{recent_backups}/{total_systems} sistemas con backup reciente'}
        elif percentage >= 70:
            return {'status': 'warning', 'percentage': percentage, 'message': f'{recent_backups}/{total_systems} sistemas con backup reciente'}
        else:
            return {'status': 'critical', 'percentage': percentage, 'message': f'{recent_backups}/{total_systems} sistemas con backup reciente'}

def main():
    """Función principal para pruebas"""
    import os
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "admin_panel.db")
    
    alert_manager = AlertManager(db_path)
    
    print("=== Gestor de Alertas Inteligente ===")
    print()
    
    # Prueba de creación de alerta
    alert_id = alert_manager.create_alert(
        alert_type='backup_failed',
        severity='critical',
        title='Backup falló',
        message='El backup del sistema servidor1 falló por falta de espacio',
        context={'system': 'servidor1', 'error': 'No space left on device'},
        action_url='/systems/1',
        action_label='Ver Sistema',
        system_id=1
    )
    
    print(f"Alerta creada: {alert_id}")
    
    # Prueba de salud del sistema
    health = alert_manager.get_system_health()
    print(f"Salud del sistema: {health}")
    
    # Prueba de reglas de notificación
    should_notify = alert_manager.should_notify('backup_failed', 'critical')
    print(f"Debe notificar: {should_notify}")

if __name__ == "__main__":
    main()
