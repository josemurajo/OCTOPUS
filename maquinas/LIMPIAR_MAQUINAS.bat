@echo off
cd /d "%~dp0"
echo ============================================================
echo  OCTOPUS - borrar maquinas virtuales que sobran
echo  Las maquinas de tus laboratorios (v1 y v2) NO se tocan.
echo  Antes de borrar nada te ensena la lista y te pregunta.
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0limpiar_maquinas.ps1"
echo.
pause
