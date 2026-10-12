#!/usr/bin/env python3
"""
ZeroTouch - Presets de Configuración
Configuraciones predefinidas para diferentes escenarios
"""

from typing import Dict

class ConfigPresets:
    """Presets de configuración para simplificar la UX"""
    
    PRESETS = {
        'home': {
            'name': 'Hogar / Personal',
            'description': 'Configuración ideal para uso personal en casa',
            'icon': '🏠',
            'config': {
                'backup_frequency': 'daily',
                'backup_time': '02:00',
                'backup_retention': 'daily_30',
                'backup_compression': True,
                'backup_encryption': True,
                'response_level': 'balanced',
                'isolation_time': 0,
                'auto_restore': True,
                'restore_approval': False,
                'watchdog_enabled': True,
                'email_notifications': True,
                'telegram_enabled': True,
                'notification_levels': ['critical', 'high'],
                'protected_paths': {
                    'windows': ['C:\\Users', 'C:\\Documents'],
                    'linux': ['/home', '/Documents'],
                    'macos': ['/Users', '/Documents']
                }
            }
        },
        'small_business': {
            'name': 'Pequeña Empresa',
            'description': 'Configuración para negocios pequeños (1-10 empleados)',
            'icon': '🏢',
            'config': {
                'backup_frequency': 'daily',
                'backup_time': '01:00',
                'backup_retention': 'daily_90',
                'backup_compression': True,
                'backup_encryption': True,
                'response_level': 'conservative',
                'isolation_time': 5,
                'auto_restore': True,
                'restore_approval': True,
                'watchdog_enabled': True,
                'email_notifications': True,
                'telegram_enabled': True,
                'notification_levels': ['critical', 'high', 'medium'],
                'protected_paths': {
                    'windows': ['C:\\Users', 'C:\\Program Files', 'C:\\Business'],
                    'linux': ['/home', '/etc', '/var/www', '/opt/business'],
                    'macos': ['/Users', '/Applications', '/Business']
                }
            }
        },
        'enterprise': {
            'name': 'Empresa Grande',
            'description': 'Configuración completa para empresas con compliance',
            'icon': '🏛️',
            'config': {
                'backup_frequency': 'daily',
                'backup_time': '00:00',
                'backup_retention': 'daily_90',
                'backup_compression': True,
                'backup_encryption': True,
                'response_level': 'paranoid',
                'isolation_time': 0,
                'auto_restore': False,
                'restore_approval': True,
                'watchdog_enabled': True,
                'email_notifications': True,
                'telegram_enabled': True,
                'notification_levels': ['critical', 'high', 'medium', 'low'],
                'protected_paths': {
                    'windows': ['C:\\Users', 'C:\\Program Files', 'C:\\Windows', 'C:\\Business'],
                    'linux': ['/home', '/etc', '/var/www', '/opt', '/usr/local'],
                    'macos': ['/Users', '/Applications', '/Library', '/Business']
                }
            }
        },
        'developer': {
            'name': 'Desarrollador',
            'description': 'Configuración para desarrolladores con código y proyectos',
            'icon': '💻',
            'config': {
                'backup_frequency': 'hourly',
                'backup_time': '00:00',
                'backup_retention': 'daily_7',
                'backup_compression': True,
                'backup_encryption': True,
                'response_level': 'balanced',
                'isolation_time': 10,
                'auto_restore': True,
                'restore_approval': False,
                'watchdog_enabled': True,
                'email_notifications': True,
                'telegram_enabled': False,
                'notification_levels': ['critical', 'high'],
                'protected_paths': {
                    'windows': ['C:\\Users', 'C:\\Projects', 'C:\\Repositories'],
                    'linux': ['/home', '/projects', '/repos', '/var/www'],
                    'macos': ['/Users', '/Projects', '/Repositories']
                }
            }
        },
        'minimal': {
            'name': 'Mínimo / Silencioso',
            'description': 'Configuración mínima, notificaciones solo para críticas',
            'icon': '🔇',
            'config': {
                'backup_frequency': 'weekly',
                'backup_time': '03:00',
                'backup_retention': 'weekly_4',
                'backup_compression': True,
                'backup_encryption': True,
                'response_level': 'conservative',
                'isolation_time': 15,
                'auto_restore': False,
                'restore_approval': True,
                'watchdog_enabled': False,
                'email_notifications': True,
                'telegram_enabled': False,
                'notification_levels': ['critical'],
                'protected_paths': {
                    'windows': ['C:\\Users'],
                    'linux': ['/home'],
                    'macos': ['/Users']
                }
            }
        }
    }
    
    @classmethod
    def get_preset(cls, preset_name: str) -> Dict:
        """Obtiene un preset específico"""
        return cls.PRESETS.get(preset_name)
    
    @classmethod
    def get_all_presets(cls) -> Dict:
        """Obtiene todos los presets"""
        return cls.PRESETS
    
    @classmethod
    def apply_preset(cls, config_manager, preset_name: str, user_id: int = None) -> tuple:
        """Aplica un preset a la configuración"""
        preset = cls.get_preset(preset_name)
        
        if not preset:
            return False, f"Preset '{preset_name}' no encontrado"
        
        config = preset['config']
        
        # Aplicar cada valor de configuración
        for key, value in config.items():
            success, message = config_manager.set_config(key, value, user_id)
            if not success:
                return False, f"Error aplicando {key}: {message}"
        
        return True, f"Preset '{preset['name']}' aplicado correctamente"
    
    @classmethod
    def get_recommended_preset(cls, system_info: Dict) -> str:
        """Recomienda un preset basado en información del sistema"""
        # Lógica simple de recomendación
        if system_info.get('is_enterprise', False):
            return 'enterprise'
        elif system_info.get('is_business', False):
            return 'small_business'
        elif system_info.get('is_developer', False):
            return 'developer'
        elif system_info.get('wants_minimal', False):
            return 'minimal'
        else:
            return 'home'

def main():
    """Función principal para pruebas"""
    print("=== Presets de Configuración ===")
    print()
    
    for preset_name, preset in ConfigPresets.get_all_presets().items():
        print(f"{preset['icon']} {preset['name']}")
        print(f"  {preset['description']}")
        print()

if __name__ == "__main__":
    main()
