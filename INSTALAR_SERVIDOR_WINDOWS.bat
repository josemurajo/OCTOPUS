@echo off
rem OCTOPUS - instala (o actualiza) el servidor OCTOPUS en este Windows. Pide permiso de administrador.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_servidor_windows.ps1"
