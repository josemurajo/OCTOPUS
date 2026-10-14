@echo off
cd /d "%~dp0"
echo ============================================================
echo  Borra las maquinas virtuales del laboratorio v2 (ZT2-*).
echo  La carpeta "proyecto" NO se toca. El laboratorio v1 NO se toca.
echo ============================================================
choice /M "Seguro que quieres borrarlas"
if errorlevel 2 exit /b
vagrant destroy -f
rmdir /s /q .runtime 2>nul
echo Hecho.
pause
