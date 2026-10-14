@echo off
cd /d "%~dp0"
echo ============================================================
echo  OCTOPUS v2 - prueba con un equipo WINDOWS (Windows Server 2022)
echo  1. Apaga cliente1 y cliente2 para dejar memoria libre
echo  2. Enciende el servidor y crea la maquina Windows
echo  3. Instala el agente con el instalador del panel (INSTALAR)
echo  4. Prueba conexion, copia y restauracion. Informe en "reportes"
echo  La primera vez descarga Windows (unos 6 GB): puede tardar 30-60 min.
echo ============================================================
echo.
vagrant halt cliente1 cliente2 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ejecutar_todo.ps1" -Maquinas win2022 %*
echo.
echo Terminado. El informe esta en la carpeta "reportes".
pause
