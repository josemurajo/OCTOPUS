@echo off
rem OCTOPUS - prueba de Windows con la COPIA COMPLETA del disco C:. Apaga antes las otras maquinas.
cd /d "%~dp0"
echo == Apagando las maquinas Linux para liberar memoria...
vagrant halt cliente1 cliente2 debian12 rocky9
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ejecutar_todo.ps1" -Maquinas win2022 -CopiaCompleta
echo.
echo Informe en la carpeta reportes.
pause
