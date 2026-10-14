@echo off
cd /d "%~dp0"
echo ============================================================
echo  OCTOPUS - DEMO: ataque de ransomware SIMULADO en cliente1
echo  (inofensivo: solo crea archivos con datos aleatorios y una
echo   nota de rescate de texto DENTRO de la maquina virtual)
echo ============================================================
echo.
echo Abre el panel: https://192.168.10.10:8080  y mira "Incidentes".
echo.
vagrant ssh cerebro -c "sudo bash /vagrant_host/scripts/pruebas_cerebro.sh simular cliente1"
echo.
echo En 10-60 segundos veras el incidente en el panel.
pause
