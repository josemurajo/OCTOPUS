#!/usr/bin/env python3
"""
ZeroTouch - Integración con Wazuh SIEM
Consume la API de Wazuh para obtener alertas de seguridad en tiempo real
"""

import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional

class WazuhIntegration:
    """Integración con Wazuh SIEM"""
    
    def __init__(self, config_manager):
        self.config = config_manager
        self.base_url = None
        self.api_key = None
        self.verify_ssl = True
        self._load_config()
    
    def _load_config(self):
        """Carga configuración de Wazuh"""
        config = self.config.get_config()
        
        wazuh_url = config.get('wazuh_url', '')
        wazuh_api_key = config.get('wazuh_api_key', '')
        wazuh_verify_ssl = config.get('wazuh_verify_ssl', True)
        
        if wazuh_url:
            self.base_url = wazuh_url.rstrip('/')
            self.api_key = wazuh_api_key
            self.verify_ssl = wazuh_verify_ssl
    
    def is_configured(self):
        """Verifica si Wazuh está configurado"""
        return bool(self.base_url and self.api_key)
    
    def get_alerts(self, hours=24, level_min=7, level_max=15):
        """Obtiene alertas de Wazuh"""
        if not self.is_configured():
            return {'error': 'Wazuh no está configurado'}
        
        try:
            # Calcular fecha de inicio
            start_time = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
            
            # Endpoint de Wazuh para obtener alertas
            url = f"{self.base_url}/events"
            
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            params = {
                'q': f'time>="{start_time}" AND rule.level>={level_min} AND rule.level<={level_max}',
                'sort': '-time',
                'limit': 100
            }
            
            response = requests.get(url, headers=headers, params=params, verify=self.verify_ssl)
            
            if response.status_code == 200:
                data = response.json()
                alerts = data.get('data', {}).get('items', [])
                
                return {
                    'success': True,
                    'alerts': alerts,
                    'count': len(alerts)
                }
            else:
                return {
                    'success': False,
                    'error': f'Error {response.status_code}: {response.text}'
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_alert_by_id(self, alert_id):
        """Obtiene una alerta específica por ID"""
        if not self.is_configured():
            return {'error': 'Wazuh no está configurado'}
        
        try:
            url = f"{self.base_url}/events/{alert_id}"
            
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(url, headers=headers, verify=self.verify_ssl)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'alert': data.get('data', {})
                }
            else:
                return {
                    'success': False,
                    'error': f'Error {response.status_code}: {response.text}'
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_agent_status(self, agent_id=None):
        """Obtiene estado de agentes Wazuh"""
        if not self.is_configured():
            return {'error': 'Wazuh no está configurado'}
        
        try:
            if agent_id:
                url = f"{self.base_url}/agents/{agent_id}"
            else:
                url = f"{self.base_url}/agents/status"
            
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(url, headers=headers, verify=self.verify_ssl)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'data': data.get('data', {})
                }
            else:
                return {
                    'success': False,
                    'error': f'Error {response.status_code}: {response.text}'
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_vulnerabilities(self, agent_id=None):
        """Obtiene vulnerabilidades detectadas"""
        if not self.is_configured():
            return {'error': 'Wazuh no está configurado'}
        
        try:
            if agent_id:
                url = f"{self.base_url}/vulnerability/{agent_id}"
            else:
                url = f"{self.base_url}/vulnerability"
            
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(url, headers=headers, verify=self.verify_ssl)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'vulnerabilities': data.get('data', {}).get('items', [])
                }
            else:
                return {
                    'success': False,
                    'error': f'Error {response.status_code}: {response.text}'
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def analyze_alert(self, alert):
        """Analiza una alerta de Wazuh y determina la acción"""
        if not alert:
            return {'action': 'ignore', 'reason': 'No hay alerta'}
        
        rule = alert.get('rule', {})
        level = rule.get('level', 0)
        description = rule.get('description', '')
        
        # Categorías de amenazas
        ransomware_keywords = ['ransom', 'encrypt', 'lock', 'crypto', 'ransomware']
        malware_keywords = ['malware', 'virus', 'trojan', 'backdoor', 'rootkit']
        intrusion_keywords = ['intrusion', 'attack', 'breach', 'exploit', 'injection']
        
        description_lower = description.lower()
        
        # Determinar severidad
        if level >= 12:
            severity = 'critical'
        elif level >= 10:
            severity = 'high'
        elif level >= 7:
            severity = 'medium'
        else:
            severity = 'low'
        
        # Determinar acción basada en tipo de amenaza
        if any(keyword in description_lower for keyword in ransomware_keywords):
            return {
                'action': 'isolate',
                'severity': 'critical',
                'reason': 'Posible ransomware detectado',
                'alert_level': level
            }
        elif any(keyword in description_lower for keyword in malware_keywords):
            return {
                'action': 'isolate',
                'severity': 'high',
                'reason': 'Malware detectado',
                'alert_level': level
            }
        elif any(keyword in description_lower for keyword in intrusion_keywords):
            return {
                'action': 'isolate',
                'severity': 'high',
                'reason': 'Posible intrusión detectada',
                'alert_level': level
            }
        elif severity == 'critical':
            return {
                'action': 'isolate',
                'severity': 'critical',
                'reason': f'Alerta crítica: {description}',
                'alert_level': level
            }
        elif severity == 'high':
            return {
                'action': 'restore',
                'severity': 'high',
                'reason': f'Alerta alta: {description}',
                'alert_level': level
            }
        elif severity == 'medium':
            return {
                'action': 'alert',
                'severity': 'medium',
                'reason': f'Alerta media: {description}',
                'alert_level': level
            }
        else:
            return {
                'action': 'monitor',
                'severity': 'low',
                'reason': f'Alerta baja: {description}',
                'alert_level': level
            }
    
    def get_critical_alerts(self, hours=1):
        """Obtiene alertas críticas recientes"""
        result = self.get_alerts(hours=hours, level_min=12, level_max=15)
        
        if result.get('success'):
            alerts = result.get('alerts', [])
            analyzed = [self.analyze_alert(alert) for alert in alerts]
            
            return {
                'success': True,
                'alerts': alerts,
                'analyzed': analyzed,
                'count': len(alerts)
            }
        
        return result
    
    def test_connection(self):
        """Prueba la conexión con Wazuh"""
        if not self.is_configured():
            return {
                'success': False,
                'error': 'Wazuh no está configurado'
            }
        
        try:
            # Intentar obtener el estado de los agentes
            result = self.get_agent_status()
            
            if result.get('success'):
                return {
                    'success': True,
                    'message': 'Conexión exitosa con Wazuh'
                }
            else:
                return result
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

def main():
    """Función principal para pruebas"""
    from config_manager import ConfigManager
    
    config_manager = ConfigManager()
    wazuh = WazuhIntegration(config_manager)
    
    print("=== Integración con Wazuh SIEM ===")
    print()
    
    # Verificar configuración
    if wazuh.is_configured():
        print("Wazuh está configurado")
        print(f"URL: {wazuh.base_url}")
        
        # Probar conexión
        print("\nProbando conexión...")
        result = wazuh.test_connection()
        print(f"Resultado: {result}")
        
        # Obtener alertas críticas
        print("\nObteniendo alertas críticas...")
        alerts = wazuh.get_critical_alerts(hours=1)
        print(f"Alertas críticas: {alerts.get('count', 0)}")
        
    else:
        print("Wazuh no está configurado")
        print("Configura wazuh_url y wazuh_api_key en la configuración")

if __name__ == "__main__":
    main()
