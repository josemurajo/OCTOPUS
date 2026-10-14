@echo off
rem OCTOPUS - prueba de la instalacion a distancia por SSH en Windows (servidor win11srv -> equipo win2022)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0probar_instalacion_ssh_windows.ps1"
echo.
echo Informe en la carpeta reportes.
pause
