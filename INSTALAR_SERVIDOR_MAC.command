#!/bin/bash
# OCTOPUS - doble clic para instalar (o actualizar) el servidor OCTOPUS en este Mac. Sin Docker ni Homebrew.
# El Mac pide tu contrasena una vez; lo demas lo hace solo.
cd "$(dirname "$0")" || exit 1
clear
echo "OCTOPUS - instalacion del servidor"
echo "Escribe la contrasena de este Mac (no se ve mientras escribes) y pulsa Intro."
echo
sudo bash ./instalar_servidor_mac.sh
rc=$?
echo
read -r -p "Pulsa Intro para cerrar esta ventana" _
exit $rc
