@echo off
rem OCTOPUS - instala (o actualiza) el servidor OCTOPUS en este Windows. Sin WSL2 ni Docker.
rem Windows pide permiso de administrador una vez; lo demas lo hace solo.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_servidor_windows.ps1"
