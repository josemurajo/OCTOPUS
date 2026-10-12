@echo off
rem OCTOPUS Zero-Touch - quita el agente de este equipo (las copias del servidor NO se borran)
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_windows.ps1" -Desinstalar
echo.
pause
