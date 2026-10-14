@echo off
rem OCTOPUS - prueba con Debian 12 y Rocky Linux 9. Apaga antes las otras maquinas para que haya RAM.
cd /d "%~dp0"
echo == Apagando cliente1, cliente2 y win2022 para liberar memoria...
vagrant halt cliente1 cliente2 win2022
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ejecutar_todo.ps1" -Maquinas debian12,rocky9
echo.
echo Informe en la carpeta reportes.
pause
