@echo off
cd /d "%~dp0"
echo ============================================================
echo  OCTOPUS v2 - prueba "Anadir equipo con IP, usuario y contrasena"
echo  1. Apaga la maquina Windows (deja memoria libre)
echo  2. Borra cliente1 y lo crea de nuevo, sin la clave del servidor
echo  3. Pruebas completas: el panel entra en cliente1 con la contrasena
echo ============================================================
vagrant halt win2022 2>nul
vagrant destroy -f cliente1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ejecutar_todo.ps1"
echo.
echo Terminado. El informe esta en la carpeta "reportes".
pause
