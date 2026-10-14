@echo off
cd /d "%~dp0"
echo ============================================================
echo  OCTOPUS v2 - laboratorio completo y pruebas
echo  1. Crea el servidor en un Ubuntu 24.04 vacio e instala OCTOPUS
echo  2. Crea cliente1 (Ubuntu) y cliente2 (Rocky) e instala los agentes
echo  3. Hace todas las pruebas y guarda el informe en "reportes"
echo  La primera vez tarda 30-45 minutos (descarga las maquinas).
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ejecutar_todo.ps1" %*
echo.
echo Terminado. El informe esta en la carpeta "reportes".
echo Panel: https://192.168.10.10:8080  (usuario admin; contrasena en .runtime\CREDENCIALES_INICIALES.txt)
pause
