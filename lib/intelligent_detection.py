#!/usr/bin/env python3
"""
ZeroTouch - Detección Inteligente de Cambios
Analiza patrones de cambios y distingue entre cambios legítimos y sospechosos
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict
import re

class IntelligentDetection:
    """Sistema de detección inteligente de cambios"""
    
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base_dir, "data", "admin_panel.db")
        
        self.db_path = db_path
        self._init_whitelist_table()
        self._init_patterns_table()
    
    def get_db_connection(self):
        """Obtiene conexión a la base de datos"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_whitelist_table(self):
        """Inicializa tabla de whitelist de cambios permitidos"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS change_whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                pattern TEXT,
                user TEXT,
                process TEXT,
                reason TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _init_patterns_table(self):
        """Inicializa tabla de patrones sospechosos"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS suspicious_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT NOT NULL,
                severity TEXT DEFAULT 'medium',
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Insertar patrones por defecto si no existen
        cursor.execute('SELECT COUNT(*) FROM suspicious_patterns')
        if cursor.fetchone()[0] == 0:
            default_patterns = [
                (r'\.ransom', 'critical', 'Archivos con extensión ransomware'),
                (r'\.locky', 'critical', 'Archivos con extensión Locky'),
                (r'\.encrypted', 'critical', 'Archivos encriptados'),
                (r'\.crypto', 'critical', 'Archivos con extensión crypto'),
                (r'readme.*decrypt', 'high', 'Archivos de ransomware típicos'),
                (r'recover.*files', 'high', 'Archivos de recuperación sospechosos'),
                (r'how.*restore', 'high', 'Archivos de instrucciones de ransomware'),
                (r'bitcoin.*wallet', 'medium', 'Referencias a wallets de Bitcoin'),
                (r'payment.*instruction', 'medium', 'Instrucciones de pago sospechosas'),
                (r'\.tmp$.*\.exe', 'high', 'Archivos temporales ejecutables'),
                (r'\.vbs$', 'medium', 'Scripts VBScript'),
                (r'\.js$', 'low', 'Archivos JavaScript'),
                (r'\.ps1$', 'medium', 'Scripts PowerShell'),
            ]
            
            for pattern, severity, description in default_patterns:
                cursor.execute('''
                    INSERT INTO suspicious_patterns (pattern, severity, description)
                    VALUES (?, ?, ?)
                ''', (pattern, severity, description))
        
        conn.commit()
        conn.close()
    
    def is_whitelisted(self, file_path, user=None, process=None):
        """Verifica si un cambio está en whitelist"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        # Verificar whitelist exacta
        cursor.execute('''
            SELECT * FROM change_whitelist 
            WHERE file_path = ? 
            AND (expires_at IS NULL OR expires_at > ?)
        ''', (file_path, datetime.now()))
        
        if cursor.fetchone():
            conn.close()
            return True, "Whitelist exacta"
        
        # Verificar whitelist por patrón
        cursor.execute('''
            SELECT * FROM change_whitelist 
            WHERE pattern IS NOT NULL 
            AND ? LIKE pattern
            AND (expires_at IS NULL OR expires_at > ?)
        ''', (file_path, datetime.now()))
        
        if cursor.fetchone():
            conn.close()
            return True, "Whitelist por patrón"
        
        # Verificar whitelist por usuario
        if user:
            cursor.execute('''
                SELECT * FROM change_whitelist 
                WHERE user = ? 
                AND (expires_at IS NULL OR expires_at > ?)
            ''', (user, datetime.now()))
            
            if cursor.fetchone():
                conn.close()
                return True, "Whitelist por usuario"
        
        conn.close()
        return False, "No está en whitelist"
    
    def add_to_whitelist(self, file_path, pattern=None, user=None, process=None, reason="", expires_days=None, created_by=None):
        """Agrega un cambio a la whitelist"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        expires_at = None
        if expires_days:
            expires_at = datetime.now() + timedelta(days=expires_days)
        
        cursor.execute('''
            INSERT INTO change_whitelist (file_path, pattern, user, process, reason, expires_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (file_path, pattern, user, process, reason, expires_at, created_by))
        
        conn.commit()
        conn.close()
        
        return True, "Agregado a whitelist"
    
    def remove_from_whitelist(self, whitelist_id):
        """Elimina de la whitelist"""
        conn = self.get_db_connection()
        conn.execute('DELETE FROM change_whitelist WHERE id = ?', (whitelist_id,))
        conn.commit()
        conn.close()
        
        return True, "Eliminado de whitelist"
    
    def analyze_change(self, file_path, change_type, user=None, process=None, content_hash=None):
        """Analiza un cambio y determina si es sospechoso"""
        score = 0
        reasons = []
        
        # 1. Verificar whitelist
        is_whitelisted, whitelist_reason = self.is_whitelisted(file_path, user, process)
        if is_whitelisted:
            return {
                'suspicious': False,
                'score': 0,
                'reasons': [f"Whitelist: {whitelist_reason}"],
                'action': 'allow'
            }
        
        # 2. Verificar patrones sospechosos en el nombre de archivo
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT pattern, severity, description FROM suspicious_patterns')
        suspicious_patterns = cursor.fetchall()
        
        for pattern_row in suspicious_patterns:
            pattern = pattern_row['pattern']
            severity = pattern_row['severity']
            description = pattern_row['description']
            
            if re.search(pattern, file_path, re.IGNORECASE):
                if severity == 'critical':
                    score += 50
                elif severity == 'high':
                    score += 30
                elif severity == 'medium':
                    score += 20
                else:
                    score += 10
                
                reasons.append(f"Patrón sospechoso: {description}")
        
        conn.close()
        
        # 3. Analizar tipo de cambio
        if change_type == 'delete':
            score += 15
            reasons.append("Eliminación de archivo")
        elif change_type == 'modify':
            score += 10
            reasons.append("Modificación de archivo")
        elif change_type == 'create':
            score += 5
            reasons.append("Creación de archivo")
        
        # 4. Analizar ubicación del archivo
        sensitive_paths = ['/etc', '/bin', '/sbin', '/usr/bin', '/usr/sbin', 'C:\\Windows', 'C:\\Program Files']
        for sensitive_path in sensitive_paths:
            if file_path.startswith(sensitive_path):
                score += 25
                reasons.append(f"Archivo en ruta sensible: {sensitive_path}")
                break
        
        # 5. Analizar usuario
        suspicious_users = ['root', 'Administrator', 'SYSTEM']
        if user in suspicious_users:
            score += 10
            reasons.append(f"Usuario privilegiado: {user}")
        
        # 6. Analizar proceso
        suspicious_processes = ['powershell.exe', 'cmd.exe', 'bash', 'sh', 'python.exe']
        if process and any(p in process.lower() for p in suspicious_processes):
            score += 15
            reasons.append(f"Proceso potencialmente sospechoso: {process}")
        
        # Determinar acción basada en score
        if score >= 50:
            action = 'isolate'
            suspicious = True
        elif score >= 30:
            action = 'restore'
            suspicious = True
        elif score >= 15:
            action = 'alert'
            suspicious = True
        else:
            action = 'allow'
            suspicious = False
        
        return {
            'suspicious': suspicious,
            'score': score,
            'reasons': reasons,
            'action': action,
            'file_path': file_path,
            'change_type': change_type,
            'user': user,
            'process': process
        }
    
    def get_whitelist(self):
        """Obtiene toda la whitelist"""
        conn = self.get_db_connection()
        whitelist = conn.execute('SELECT * FROM change_whitelist ORDER BY created_at DESC').fetchall()
        conn.close()
        
        return whitelist
    
    def get_suspicious_patterns(self):
        """Obtiene patrones sospechosos configurados"""
        conn = self.get_db_connection()
        patterns = conn.execute('SELECT * FROM suspicious_patterns ORDER BY severity DESC').fetchall()
        conn.close()
        
        return patterns
    
    def add_suspicious_pattern(self, pattern, severity='medium', description=''):
        """Agrega un patrón sospechoso"""
        conn = self.get_db_connection()
        conn.execute('''
            INSERT INTO suspicious_patterns (pattern, severity, description)
            VALUES (?, ?, ?)
        ''', (pattern, severity, description))
        conn.commit()
        conn.close()
        
        return True, "Patrón agregado"
    
    def remove_suspicious_pattern(self, pattern_id):
        """Elimina un patrón sospechoso"""
        conn = self.get_db_connection()
        conn.execute('DELETE FROM suspicious_patterns WHERE id = ?', (pattern_id,))
        conn.commit()
        conn.close()
        
        return True, "Patrón eliminado"

def main():
    """Función principal para pruebas"""
    detector = IntelligentDetection()
    
    print("=== Detección Inteligente de Cambios ===")
    print()
    
    # Prueba de análisis
    test_cases = [
        ('/etc/passwd', 'modify', 'root', 'vim'),
        ('/home/user/document.txt', 'modify', 'user', 'nano'),
        ('/tmp/file.ransom', 'create', 'unknown', 'unknown'),
        ('C:\\Windows\\system32\\config.exe', 'create', 'SYSTEM', 'powershell.exe'),
        ('/home/user/readme_decrypt.txt', 'create', 'user', 'python'),
    ]
    
    for file_path, change_type, user, process in test_cases:
        result = detector.analyze_change(file_path, change_type, user, process)
        print(f"Archivo: {file_path}")
        print(f"  Sospechoso: {result['suspicious']}")
        print(f"  Score: {result['score']}")
        print(f"  Acción: {result['action']}")
        print(f"  Razones: {', '.join(result['reasons'])}")
        print()

if __name__ == "__main__":
    main()
