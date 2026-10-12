@echo off
rem OCTOPUS Zero-Touch - instala el agente en este equipo (pide permisos de administrador)
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Pidiendo permisos de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_windows.ps1"
echo.
pause
