@echo off
rem OCTOPUS - prueba del SERVIDOR OCTOPUS NATIVO en Windows 11 (sin WSL2 ni Docker). Apaga antes las demas maquinas.
rem Para probarlo en Windows Server 2022: PROBAR_SERVIDOR_WINDOWS.bat win2022
cd /d "%~dp0"
if "%1"=="" (set VM=win11srv) else (set VM=%1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0probar_servidor_windows.ps1" -VM %VM%
echo.
echo Informe en la carpeta reportes.
pause
