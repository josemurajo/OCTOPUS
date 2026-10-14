@echo off
rem OCTOPUS - Apaga a la fuerza la maquina cerebro (si se quedo colgada) y lanza las pruebas otra vez
cd /d "%~dp0"
echo == Apagando cerebro a la fuerza...
vagrant halt -f cerebro
echo.
echo == Lanzando las pruebas de nuevo...
call "%~dp0EJECUTAR_PRUEBAS.bat"
