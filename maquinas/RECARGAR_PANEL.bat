@echo off
rem OCTOPUS - Copia los cambios del proyecto a cerebro y reinicia el panel (no borra datos ni copias)
cd /d "%~dp0"
echo == Encendiendo cerebro (si estaba apagado)...
vagrant up cerebro --no-provision
echo.
echo == Copiando el proyecto y actualizando el panel (1-3 minutos)...
vagrant provision cerebro --provision-with sync,install
echo.
echo == Listo. Recarga el panel en el navegador (F5): https://192.168.10.10:8080
pause
