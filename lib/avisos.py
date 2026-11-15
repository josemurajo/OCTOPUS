#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 José Murillo Rajo · OCTOPUS Zero-Touch (ver LICENSE y NOTICE)
"""
OCTOPUS - Catalogo unico de avisos: cada problema tiene un CODIGO, que pasa, por que importa, los pasos
exactos para solucionarlo y, cuando se puede, una accion automatica (boton "Solucionar" del panel).

El mismo codigo aparece en el panel, en los correos/Telegram y en los banderines, asi siempre se sabe de que
se habla. Las acciones del servidor (almacen, certificado, mantenimiento...) estan aqui; las de un equipo
(volver a copiar, repetir la prueba) las ejecuta el panel porque necesitan hablar con el agente.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
DATA = BASE_DIR / "data"
ACTUALIZACION_FILE = DATA / "actualizacion.json"
REINICIAR_FLAG = Path(os.environ.get("OCTOPUS_DATA", "/data")) / "reiniciar_servicios"

_REINICIO_AGENTE = ("Si sigue igual, reinicia el agente en ese equipo: en Windows, Programador de tareas → "
                    "«OCTOPUS Agente» → Ejecutar; en Linux, sudo systemctl restart octopus-agent; en Mac, "
                    "sudo launchctl kickstart -k system/com.octopus.agent.")

# codigo -> datos. En los textos, {equipo} y {detalle} se rellenan con el caso concreto.
CATALOGO: dict[str, dict] = {
    # ---------------------------------------------------------------- equipos
    "OCT-EQ-01": {
        "nivel": "problema", "titulo": "No hay conexión con {equipo}",
        "por_que": "Mientras no haya conexión no se hacen copias de este equipo y no se le puede proteger si le atacan.",
        "pasos": ["Comprueba que el equipo está encendido y conectado a la red (y que no está en suspensión).",
                  "Si se acaba de reiniciar, espera 2 minutos: el agente vuelve a conectar solo.",
                  _REINICIO_AGENTE,
                  "Si nada de eso funciona, vuelve a instalar el agente desde la ficha del equipo (no se pierden copias)."],
        "accion": None},
    "OCT-EQ-02": {
        "nivel": "atencion", "titulo": "{equipo} todavía no tiene ninguna copia",
        "por_que": "Si este equipo se estropea o le atacan hoy, no habría nada que recuperar.",
        "pasos": ["Pulsa «Solucionar» (o «Hacer copia ahora» en la ficha del equipo).",
                  "La primera copia puede tardar un rato; luego son mucho más rápidas."],
        "accion": "copia_equipo", "boton": "Hacer la copia ahora"},
    "OCT-EQ-03": {
        "nivel": "atencion", "titulo": "La última copia de {equipo} es de {detalle}",
        "por_que": "Lo que se haya creado o cambiado desde entonces no está protegido.",
        "pasos": ["Si el equipo estuvo apagado o de viaje, es normal: pulsa «Solucionar» para copiar ahora.",
                  "Si estaba encendido, revisa que tenga conexión; la copia diaria se hace sola cada día.",
                  "Para portátiles que pasan días fuera, puedes ampliar el plazo en su ficha («Aviso si se queda sin copia»)."],
        "accion": "copia_equipo", "boton": "Hacer la copia ahora"},
    "OCT-EQ-04": {
        "nivel": "problema", "titulo": "La última copia de {equipo} falló",
        "por_que": "Este equipo se ha quedado sin copia reciente.",
        "pasos": ["Pulsa «Solucionar» para repetirla (muchas veces es algo puntual: red, equipo en uso...).",
                  "Si vuelve a fallar, comprueba que el equipo tiene espacio libre y conexión con el servidor.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": "copia_equipo", "boton": "Repetir la copia"},
    "OCT-EQ-05": {
        "nivel": "problema", "titulo": "La prueba de recuperación de {equipo} falló",
        "por_que": "No se ha podido comprobar que sus copias se recuperan bien; podría fallar justo cuando haga falta.",
        "pasos": ["Pulsa «Solucionar»: se hace una copia nueva del equipo y se repite la prueba.",
                  "Si vuelve a fallar, revisa el aviso del almacén (si lo hay) y avisa al técnico.",
                  "Detalle: {detalle}"],
        "accion": "prueba_equipo", "boton": "Copiar y volver a probar"},
    "OCT-EQ-06": {
        "nivel": "atencion", "titulo": "La última copia de {equipo} se hizo durante un ataque",
        "por_que": "Esa copia puede contener archivos cifrados o dañados.",
        "pasos": ["Si tienes que recuperar algo, usa una copia limpia (en la ficha del equipo se ve cuál es).",
                  "Cuando el equipo esté limpio, haz una copia nueva."],
        "accion": None},
    # ---------------------------------------------------------------- monitorizacion (solo equipos con la monitorizacion activada)
    "OCT-MON-01": {
        "nivel": "problema", "titulo": "El disco de {equipo} está fallando",
        "por_que": "Un disco que falla puede dejar de funcionar en cualquier momento, y con él todo lo que no tenga copia.",
        "pasos": ["Pulsa «Hacer copia ahora» en la ficha del equipo para tener lo último a salvo.",
                  "Cambia el disco cuanto antes (con la copia completa se puede dejar el equipo como estaba).",
                  "Disco: {detalle}"],
        "accion": "copia_equipo", "boton": "Hacer copia ahora"},
    "OCT-MON-02": {
        "nivel": "atencion", "titulo": "El disco de {equipo} está muy gastado",
        "por_que": "Ha usado casi toda la vida que da el fabricante: puede empezar a fallar.",
        "pasos": ["Planifica cambiarlo en las próximas semanas.", "Mientras, comprueba que sus copias se hacen bien.",
                  "Disco: {detalle}"],
        "accion": None},
    "OCT-MON-03": {
        "nivel": "atencion", "titulo": "El disco de {equipo} está casi lleno",
        "por_que": "Con el disco lleno el equipo va lento, algunos programas fallan y puede que no se puedan hacer copias.",
        "pasos": ["Vacía la papelera y borra lo que no hace falta (descargas, temporales).",
                  "Si siempre está lleno, amplía el disco.", "Dónde: {detalle}"],
        "accion": None},
    "OCT-MON-04": {
        "nivel": "atencion", "titulo": "{equipo} se está calentando mucho",
        "por_que": "El calor mantenido acorta la vida del equipo y puede hacer que se apague solo.",
        "pasos": ["Comprueba que las rejillas de ventilación no estén tapadas.", "Limpia el polvo y comprueba que el ventilador gira.",
                  "Detalle: {detalle}"],
        "accion": None},
    "OCT-MON-05": {
        "nivel": "atencion", "titulo": "La batería de {equipo} está muy gastada",
        "por_que": "Puede durar muy poco o apagarse de golpe sin avisar, perdiendo lo que no esté guardado.",
        "pasos": ["Si el portátil dura poco o se apaga solo, cambia la batería.", "Detalle: {detalle}"],
        "accion": None},
    "OCT-MON-06": {
        "nivel": "atencion", "titulo": "{equipo} va al límite de memoria",
        "por_que": "Con la memoria llena todo va lento y los programas se pueden cerrar solos.",
        "pasos": ["Mira en Monitorización qué procesos gastan más memoria y cierra lo que no se use.",
                  "Si pasa a menudo, añade más memoria al equipo.", "Detalle: {detalle}"],
        "accion": None},
    "OCT-MON-07": {
        "nivel": "atencion", "titulo": "El procesador de {equipo} lleva mucho rato al 100 %",
        "por_que": "El equipo va lento, se calienta y gasta más; a veces es un programa colgado o algo que no debería estar ahí.",
        "pasos": ["Mira en Monitorización qué proceso lo está usando.",
                  "Si no lo conoces o no debería estar funcionando, pide ayuda: puede ser un virus o un minero.",
                  "Detalle: {detalle}"],
        "accion": None},
    "OCT-MON-08": {
        "nivel": "atencion", "titulo": "{equipo} ha dejado de mandar datos de monitorización",
        "por_que": "Lleva más de 30 minutos sin mandar datos: puede estar apagado, sin red o con el agente parado.",
        "pasos": ["Si está encendido y con red, reinicia el agente.", _REINICIO_AGENTE],
        "accion": None},
    "OCT-MON-09": {
        "nivel": "problema", "titulo": "El antivirus de {equipo} está desactivado",
        "por_que": "Sin protección en tiempo real, un virus puede entrar sin que nadie lo pare.",
        "pasos": ["En el equipo: Seguridad de Windows → Protección antivirus → activar «Protección en tiempo real».",
                  "Si lo ha desactivado un programa que no conoces, pide ayuda.", "Antivirus: {detalle}"],
        "accion": None},
    "OCT-SEN-01": {
        "nivel": "problema", "titulo": "Alguien ha tocado un archivo señuelo en {equipo}",
        "por_que": "Los archivos señuelo no los usa nadie: si cambian, casi seguro es un ataque (ransomware).",
        "pasos": ["Abre el incidente en «Incidentes» y sigue los pasos (aislar el equipo, recuperar la última copia limpia).",
                  "No apagues el equipo a la fuerza: OCTOPUS ya ha guardado evidencias.",
                  "Detalle: {detalle}"],
        "accion": None},
    # ---------------------------------------------------------------- almacen y servidor
    "OCT-ALM-01": {
        "nivel": "problema", "titulo": "El almacén de copias se ha quedado bloqueado",
        "por_que": "Suele pasar tras un corte de luz o un reinicio a mitad de una tarea. Mientras siga bloqueado, "
                   "la limpieza y la comprobación del almacén no se hacen.",
        "pasos": ["Pulsa «Solucionar»: se quitan los bloqueos antiguos (no se borra ninguna copia) y se comprueba el almacén.",
                  "Si vuelve a pasar a menudo, revisa que el servidor no se apague de golpe (un SAI ayuda)."],
        "accion": "desbloquear_almacen", "boton": "Quitar el bloqueo"},
    "OCT-ALM-02": {
        "nivel": "problema", "titulo": "La comprobación del almacén de copias ha encontrado errores",
        "por_que": "Alguna copia podría no recuperarse bien.",
        "pasos": ["No borres nada.",
                  "Pulsa «Solucionar»: se repara el índice del almacén y se vuelve a comprobar.",
                  "Si sigue con errores, revisa el disco del servidor y avisa al técnico. Si tienes almacén externo, "
                  "tus copias siguen allí.",
                  "Detalle: {detalle}"],
        "accion": "reparar_almacen", "boton": "Reparar y comprobar"},
    "OCT-ALM-03": {
        "nivel": "atencion", "titulo": "La limpieza de copias antiguas no se pudo hacer",
        "por_que": "Si no se limpian, el disco del servidor se va llenando.",
        "pasos": ["Pulsa «Solucionar» para repetirla ahora.",
                  "Si falla otra vez, comprueba el espacio libre del servidor.",
                  "Detalle: {detalle}"],
        "accion": "limpiar_copias", "boton": "Limpiar ahora"},
    "OCT-DISCO-01": {
        "nivel": "problema", "titulo": "El disco del almacén está casi lleno",
        "por_que": "Si se llena, las copias nuevas dejarán de hacerse.",
        "pasos": ["Pulsa «Solucionar»: se borran las copias que ya no hacen falta según cuántas has elegido guardar.",
                  "Si sigue casi lleno, guarda menos copias (Ajustes → Copias e informes) o amplía el disco del servidor.",
                  "Detalle: {detalle}"],
        "accion": "limpiar_copias", "boton": "Liberar espacio"},
    "OCT-SRV-01": {
        "nivel": "problema", "titulo": "La copia del propio servidor ha fallado",
        "por_que": "Sin ella, si se pierde el servidor sería más difícil recuperarlo todo.",
        "pasos": ["Pulsa «Solucionar» para repetirla ahora.",
                  "Si usas almacén externo, comprueba la conexión a Internet y que sus claves siguen siendo válidas "
                  "(sudo bash octopus.sh ajustes).",
                  "Detalle: {detalle}"],
        "accion": "copia_servidor", "boton": "Repetir la copia del servidor"},
    "OCT-SRV-02": {
        "nivel": "problema", "titulo": "El mantenimiento nocturno no se ha hecho",
        "por_que": "Es el que limpia copias viejas, comprueba el almacén, hace la copia del servidor y prueba recuperaciones.",
        "pasos": ["Pulsa «Solucionar» para hacerlo ahora (tarda unos minutos; el resultado sale en Ajustes).",
                  "Si el servidor estuvo apagado por la noche, es normal; déjalo encendido.",
                  "Detalle: {detalle}"],
        "accion": "mantenimiento_ahora", "boton": "Hacer el mantenimiento ahora"},
    "OCT-SRV-03": {
        "nivel": "atencion", "titulo": "El informe mensual no se pudo enviar",
        "por_que": "No te llegará el resumen del mes por correo (el informe se puede ver igualmente en Ajustes).",
        "pasos": ["Revisa el correo de avisos en Ajustes → Avisos por correo y pulsa «Enviar prueba».",
                  "Detalle: {detalle}"],
        "accion": None},
    "OCT-CERT-01": {
        "nivel": "atencion", "titulo": "El certificado de seguridad del servidor caduca pronto",
        "por_que": "Cuando caduque, los equipos dejarán de conectar con el servidor.",
        "pasos": ["Pulsa «Solucionar»: se emite uno nuevo con la misma autoridad (los equipos lo aceptan sin tocarlos) "
                  "y el panel se reinicia unos segundos.",
                  "Detalle: {detalle}"],
        "accion": "renovar_certificado", "boton": "Renovar el certificado"},
    "OCT-KIT-01": {
        "nivel": "atencion", "titulo": "Todavía no has descargado el kit de recuperación",
        "por_que": "Sin él, si se pierde este servidor nadie podría abrir las copias.",
        "pasos": ["Ve a Ajustes → Kit de recuperación y descárgalo.",
                  "Guárdalo fuera del servidor: pendrive, gestor de contraseñas o en papel en un sitio seguro."],
        "accion": None, "enlace": "ajustes#kit"},
    "OCT-ACT-01": {
        "nivel": "atencion", "titulo": "Hay una versión nueva de OCTOPUS ({detalle})",
        "por_que": "Las versiones nuevas traen arreglos y mejoras de seguridad.",
        "pasos": ["Normalmente se instala sola por la noche. Si ves este aviso es porque las actualizaciones automáticas "
                  "están en pausa, o porque no se pudo instalar sola: ve a Ajustes → Actualizaciones y pulsa «Actualizar ahora» "
                  "(el servidor la descarga, comprueba que está firmada por OCTOPUS y la instala; si algo va mal, vuelve "
                  "solo a la versión actual).",
                  "Si ese botón dice que el actualizador no está activado (servidores Windows), en el servidor: "
                  "sudo bash octopus.sh actualizar (en Windows: octopus.ps1 actualizar). Se conservan los datos y las copias.",
                  "Pulsa «Solucionar» para volver a comprobar si ya estás al día."],
        "accion": "comprobar_actualizacion", "boton": "Volver a comprobar"},
    "OCT-SUG-01": {
        "nivel": "atencion", "titulo": "Hay sugerencias o problemas sin enviar al soporte",
        "por_que": "Se guardaron porque no había a dónde enviarlos o no había conexión.",
        "pasos": ["Pulsa «Solucionar» para intentar enviarlos otra vez.",
                  "Si no hay ningún destino de soporte configurado, se quedan guardados en el servidor."],
        "accion": "reenviar_sugerencias", "boton": "Reintentar el envío"},
}


# ---------------------------------------------------------------- avisos de lo que se añadió después
CATALOGO.update({
    "OCT-COMP-01": {
        "nivel": "problema", "titulo": "La copia completa de {equipo} falló",
        "por_que": "Sin ella no se puede dejar el equipo entero como estaba si se rompe el disco (sus carpetas siguen "
                   "protegidas por la copia normal).",
        "pasos": ["Repítela desde la ficha del equipo («Copia completa del equipo» → «Hacer ahora»).",
                  "Si vuelve a fallar, mira que el servidor tenga sitio libre: la copia completa ocupa mucho.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": "copia_completa_equipo", "boton": "Repetir la copia completa"},
    "OCT-BD-01": {
        "nivel": "problema", "titulo": "La copia de las bases de datos de {equipo} falló",
        "por_que": "Lo que se haya guardado en esas bases de datos desde la última copia buena no está protegido.",
        "pasos": ["Abre la ficha del equipo → «Bases de datos» y revisa el usuario y la contraseña de cada base.",
                  "Si han cambiado, ponlos bien, pulsa «Guardar» y después «Copiar ahora».",
                  "Si el motor de la base de datos estaba parado, arráncalo y vuelve a copiar.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": "copia_bd_equipo", "boton": "Repetir la copia de las bases de datos"},
    "OCT-BD-02": {
        "nivel": "problema", "titulo": "No se pudo recuperar la base de datos de {equipo}",
        "por_que": "La base de datos original NO se ha tocado: sigue como estaba.",
        "pasos": ["Comprueba que el motor de la base de datos está en marcha y que hay sitio libre en el disco.",
                  "Vuelve a intentarlo eligiendo otra hora (otra copia).",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": None},
    "OCT-VM-01": {
        "nivel": "problema", "titulo": "La copia de las máquinas virtuales de {equipo} falló",
        "por_que": "Si una máquina virtual se estropea, no habría una copia reciente de ella entera.",
        "pasos": ["Abre la ficha del equipo → «Máquinas virtuales» para ver cuáles se ven y en qué estado están.",
                  "Si es VirtualBox en Linux o Mac y la máquina estaba encendida: apágala y copia otra vez (en Windows "
                  "se copia encendida).",
                  "Mira que el servidor tenga sitio libre: las máquinas virtuales ocupan mucho.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": "copia_vms_equipo", "boton": "Repetir la copia de las máquinas virtuales"},
    "OCT-VM-02": {
        "nivel": "problema", "titulo": "No se pudo recuperar la máquina virtual de {equipo}",
        "por_que": "La máquina original NO se ha tocado: sigue como estaba.",
        "pasos": ["Mira que el equipo tenga sitio libre para la copia recuperada (ocupa lo mismo que la máquina).",
                  "Vuelve a intentarlo; si falla, prueba con una copia anterior.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": None},
    "OCT-IMG-01": {
        "nivel": "atencion", "titulo": "La imagen de disco de {equipo} no se pudo hacer",
        "por_que": "Si el ordenador deja de arrancar, la última imagen buena será más antigua.",
        "pasos": ["Si pone «se deja para luego»: estaba usando el ordenador a fondo; se hará sola más tarde.",
                  "Mira que el disco USB esté conectado (o que la carpeta de red se vea) y que tenga sitio libre.",
                  "En la ficha del equipo → «Copia imagen de disco» → «Hacer una imagen ahora» para repetirla.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": "imagen_equipo", "boton": "Repetir la imagen de disco"},
    "OCT-REC-01": {
        "nivel": "problema", "titulo": "La recuperación de archivos en {equipo} no se terminó",
        "por_que": "Puede que solo se hayan recuperado algunos archivos. Lo que ya había en el equipo no se borra.",
        "pasos": ["Comprueba que el equipo sigue encendido y con conexión.",
                  "Mira que tenga sitio libre en el disco donde se recupera.",
                  "Vuelve a intentarlo desde la ficha del equipo; si falla, prueba con otra copia.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": None},
    "OCT-PASAR-01": {
        "nivel": "problema", "titulo": "No se pudo pasar todo a {equipo}",
        "por_que": "Algunas carpetas no han llegado al ordenador nuevo. Lo que ya tenía no se sobrescribe nunca.",
        "pasos": ["Comprueba que el ordenador nuevo sigue encendido y conectado.",
                  "Mira que tenga sitio libre en el disco.",
                  "Repite «Pasar a un ordenador nuevo» solo con las carpetas que falten: lo que ya llegó no se duplica.",
                  "Motivo que dio el equipo: {detalle}"],
        "accion": None},
    "OCT-NUBE-01": {
        "nivel": "problema", "titulo": "La copia de Microsoft 365 / Google ha fallado",
        "por_que": "Los correos y archivos de la nube de anoche no se han copiado.",
        "pasos": ["Ve a «Copia de la nube» y vuelve a poner los datos de la cuenta (botón «Actualizar»): los permisos "
                  "de Microsoft 365 y Google caducan cada cierto tiempo.",
                  "Comprueba que el servidor tiene Internet.",
                  "Detalle: {detalle}"],
        "accion": "copia_nube_ahora", "boton": "Repetir la copia de la nube", "enlace": "nube"},
    "OCT-RED-01": {
        "nivel": "problema", "titulo": "El arranque por red no se ha podido encender",
        "por_que": "Los ordenadores no podrán arrancar el rescate por red (con el pendrive sí).",
        "pasos": ["Mira el detalle de abajo y la parte «Qué está haciendo» de Equipos → Arranque por red.",
                  "Si dice que no puede descargar el rescate: el servidor necesita Internet la primera vez.",
                  "Si los ordenadores no lo ven: en el servidor, sudo bash octopus.sh abrir-arranque-red (cortafuegos).",
                  "Pulsa «Apagar» y «Encender» otra vez.",
                  "Detalle: {detalle}"],
        "accion": "reiniciar_arranque_red", "boton": "Apagar y encender el arranque por red", "enlace": "arranque_red"},
    # ---- monitorización (lo nuevo)
    "OCT-MON-10": {
        "nivel": "atencion", "titulo": "La tarjeta gráfica de {equipo} se está calentando mucho",
        "por_que": "El calor mantenido hace que los juegos y programas vayan a tirones y acorta la vida de la tarjeta.",
        "pasos": ["Limpia el polvo de la tarjeta y de los ventiladores de la caja.",
                  "Comprueba que la caja tiene aire: que no esté pegada a la pared ni encerrada en un mueble.",
                  "Si estás jugando, baja un poco los gráficos o limita los FPS en el juego.", "Detalle: {detalle}"],
        "accion": None},
    "OCT-MON-11": {
        "nivel": "atencion", "titulo": "{equipo} se ha apagado de golpe o ha tenido pantallazos",
        "por_que": "Cada apagado de golpe puede dañar archivos abiertos, y suele ser señal de un problema que irá a más.",
        "pasos": ["Si coincide con un corte de luz o con alguien apagándolo del botón, no hay que hacer nada.",
                  "Si no: instala las actualizaciones de Windows y de los controladores (sobre todo los de la gráfica).",
                  "Si sigue pasando, revisa la temperatura (en esta misma pantalla) y la memoria del equipo con un técnico.",
                  "Detalle: {detalle}"],
        "accion": None},
    "OCT-MON-12": {
        "nivel": "atencion", "titulo": "Un programa de {equipo} se cierra o se cuelga muy a menudo",
        "por_que": "Se pierde trabajo cada vez, y a veces es el aviso de que algo está dañado.",
        "pasos": ["Actualiza ese programa a la última versión.", "Si sigue igual, desinstálalo y vuelve a instalarlo.",
                  "Programas: {detalle}"],
        "accion": None},
    "OCT-MON-13": {
        "nivel": "problema", "titulo": "El cortafuegos de {equipo} está apagado",
        "por_que": "El cortafuegos impide que otros equipos de la red entren en este. Apagado, es mucho más fácil atacarlo.",
        "pasos": ["En Windows y Mac: pulsa «Solucionar» y se enciende solo.",
                  "Windows, a mano: Seguridad de Windows → Firewall y protección de red → activa los tres perfiles.",
                  "Mac: Ajustes del Sistema → Red → Cortafuegos → activar.",
                  "Linux: sudo ufw enable (o el cortafuegos que use tu sistema).",
                  "Si lo apagó un programa que no conoces, pide ayuda.", "Apagado en: {detalle}"],
        "accion": "cortafuegos_equipo", "boton": "Encender el cortafuegos"},
    "OCT-MON-14": {
        "nivel": "atencion", "titulo": "El portátil {equipo} no tiene el disco cifrado",
        "por_que": "Si lo pierdes o te lo roban, cualquiera puede sacar el disco y leer todos los archivos.",
        "pasos": ["Windows Pro: busca «BitLocker» → «Activar BitLocker». Guarda la clave de recuperación fuera del portátil.",
                  "Windows Home: Configuración → Privacidad y seguridad → «Cifrado del dispositivo» (si aparece).",
                  "Mac: Ajustes del Sistema → Privacidad y seguridad → FileVault → activar.",
                  "Linux: el cifrado se elige al instalar el sistema; si no lo tiene, pide ayuda."],
        "accion": None},
    "OCT-MON-15": {
        "nivel": "problema", "titulo": "Muchos intentos de contraseña fallidos en {equipo}",
        "por_que": "Puede ser alguien probando contraseñas para entrar (a mano o con un programa).",
        "pasos": ["Pregunta a quien usa el equipo si se ha equivocado muchas veces (o si un programa guarda una contraseña vieja).",
                  "Si no: cambia la contraseña de ese usuario por una larga, y revisa si el equipo está abierto a Internet.",
                  "Detalle: {detalle}"],
        "accion": None},
    "OCT-MON-16": {
        "nivel": "problema", "titulo": "Hay administradores nuevos en {equipo}",
        "por_que": "Un administrador puede hacer de todo en el equipo. Los atacantes crean uno para quedarse dentro.",
        "pasos": ["Si lo has creado tú o alguien de confianza, pulsa «Solucionar: Es correcto».",
                  "Si no sabes quién es: quítale los permisos (Windows: Administración de equipos → Usuarios y grupos) "
                  "y avisa a un técnico.", "Nuevos: {detalle}"],
        "accion": "aceptar_cambios_monitor", "boton": "Es correcto (lo he hecho yo)"},
    "OCT-MON-17": {
        "nivel": "atencion", "titulo": "{equipo} lleva semanas sin reiniciarse",
        "por_que": "Muchas actualizaciones de seguridad no se aplican hasta reiniciar, y el equipo se va volviendo lento.",
        "pasos": ["Reinícialo cuando no moleste (guarda antes lo que tengas abierto), o pulsa «Solucionar»: se "
                  "reinicia dentro de 10 minutos avisando en pantalla.", "Detalle: {detalle}"],
        "accion": "reiniciar_equipo", "boton": "Reiniciarlo (avisando antes)"},
    "OCT-MON-18": {
        "nivel": "atencion", "titulo": "Han cambiado piezas de {equipo}",
        "por_que": "Si nadie lo ha hecho a propósito, puede que alguien haya quitado memoria o un disco (con tus datos).",
        "pasos": ["Si se ha ampliado o reparado el equipo, pulsa «Solucionar: Es correcto».",
                  "Si no: revisa el equipo por dentro y pregunta quién lo ha tocado.", "Cambios: {detalle}"],
        "accion": "aceptar_cambios_monitor", "boton": "Es correcto (lo he hecho yo)"},
    "OCT-MON-19": {
        "nivel": "atencion", "titulo": "Internet va mal en {equipo}",
        "por_que": "Con cortes o lentitud fallan las webs, las videollamadas, los juegos en línea y las copias.",
        "pasos": ["Si va por wifi, prueba más cerca del router o con cable.",
                  "Reinicia el router (apagar, esperar 30 segundos y encender).",
                  "Si pasa en todos los equipos a la vez, llama a tu compañía de Internet con estos datos.",
                  "Detalle: {detalle}"],
        "accion": None},
    # ---- estos los enseña el propio USB de rescate (en el ordenador que se está rescatando)
    "OCT-RES-01": {
        "nivel": "problema", "titulo": "USB de rescate: el código no vale",
        "por_que": "Sin un código bueno, el rescate no puede llegar a las copias (es lo que las protege).",
        "pasos": ["Pide un código nuevo en el panel: ficha del equipo → «USB de rescate» → «Dar código».",
                  "Escríbelo sin prisas: son 12 letras y números (no hay O ni 0, ni I ni 1)."],
        "accion": None, "solo_guia": True},
    "OCT-RES-02": {
        "nivel": "problema", "titulo": "USB de rescate: no llega al servidor",
        "por_que": "El rescate necesita hablar con el servidor de OCTOPUS para traer las copias.",
        "pasos": ["Pon el cable de red (el rescate no usa wifi).",
                  "Escribe la dirección tal cual sale en el panel, junto al código (por ejemplo https://192.168.1.10:8080).",
                  "Comprueba que el servidor de OCTOPUS está encendido (desde otro ordenador se tiene que abrir el panel)."],
        "accion": None, "solo_guia": True},
    "OCT-RES-03": {
        "nivel": "problema", "titulo": "USB de rescate: el disco es pequeño",
        "por_que": "La copia completa no cabe en el disco elegido.",
        "pasos": ["Usa un disco igual o más grande que el del ordenador original.",
                  "O saca solo los archivos a un disco USB («Sacar los archivos»)."],
        "accion": None, "solo_guia": True},
    "OCT-RES-04": {
        "nivel": "problema", "titulo": "USB de rescate: no se puede hacer arrancable",
        "por_que": "El sistema copiado no tiene su programa de arranque (GRUB) o le faltan piezas.",
        "pasos": ["Los archivos SÍ están en el disco: puedes sacarlos con «Sacar los archivos».",
                  "Instala el sistema de cero en ese disco y después usa «Pasar a un ordenador nuevo» para traer tus carpetas."],
        "accion": None, "solo_guia": True},
    "OCT-DESP-01": {
        "nivel": "problema", "titulo": "Despliegue: el código ya no vale",
        "por_que": "La tanda se ha terminado: pasó el tiempo, se llegó al máximo de ordenadores o alguien pulsó «Terminar».",
        "pasos": ["En el panel: Equipos → «Desplegar en varios equipos» → «Dar código del despliegue» para una tanda nueva."],
        "accion": None, "solo_guia": True},
    "OCT-LOGIN-01": {
        "nivel": "problema", "titulo": "No puedo entrar en el panel",
        "por_que": "Sin entrar no se pueden ver los avisos ni recuperar nada (las copias siguen haciéndose solas).",
        "pasos": ["Si has olvidado la contraseña: en la pantalla de entrada, «He olvidado mi contraseña» (llega un correo).",
                  "Si has probado muchas veces, espera 15 minutos: OCTOPUS bloquea un rato a quien falla mucho.",
                  "Si te has quedado fuera (bloqueado, o el panel solo se abre desde la oficina), en el servidor: "
                  "sudo bash octopus.sh acceso-emergencia (en Windows: octopus.ps1 acceso-emergencia)."],
        "accion": None, "solo_guia": True},
    "OCT-2FA-01": {
        "nivel": "problema", "titulo": "He perdido el móvil de la doble autenticación",
        "por_que": "Sin el código del móvil no se puede entrar en el panel.",
        "pasos": ["Usa uno de los 10 códigos de emergencia que te enseñó al activarla.",
                  "Si no los tienes, otro administrador puede quitártela en Usuarios.",
                  "Si eres el único, en el servidor: sudo bash octopus.sh quitar-2fa TU_USUARIO (en Windows: "
                  "octopus.ps1 quitar-2fa TU_USUARIO). Te pedirá el código del kit de recuperación."],
        "accion": None, "solo_guia": True},
})

# Por qué ha pasado (lo más normal), para cada aviso. En el panel, en los correos y en SOLUCIONES.md.
CAUSAS = {
    "OCT-EQ-01": ["El equipo está apagado, en suspensión o sin red.", "Se ha cambiado de red (otra wifi, VPN) y no llega al servidor.",
                  "El agente de OCTOPUS se ha parado o lo ha quitado un antivirus."],
    "OCT-EQ-02": ["El equipo se acaba de añadir y aún no le ha tocado su copia diaria.",
                  "No tiene ninguna carpeta elegida para copiar."],
    "OCT-EQ-03": ["El equipo ha estado apagado o fuera de la oficina.", "Las copias están fallando (mira si hay otro aviso)."],
    "OCT-EQ-04": ["Se cortó la red a mitad de la copia.", "El equipo se apagó o entró en suspensión.",
                  "No hay sitio libre en el servidor o en el equipo.", "Un archivo estaba bloqueado por un programa."],
    "OCT-EQ-05": ["La copia que se probó estaba incompleta.", "El almacén de copias tiene algún error (mira sus avisos).",
                  "El equipo no tenía sitio para la prueba."],
    "OCT-EQ-06": ["Mientras se hacía la copia, OCTOPUS detectó cifrado masivo o tocaron un archivo señuelo."],
    "OCT-MON-01": ["El disco está estropeándose (lo dice el propio disco: SMART)."],
    "OCT-MON-02": ["Los discos SSD tienen una vida de escrituras; este la ha gastado casi entera."],
    "OCT-MON-03": ["Descargas, papelera, programas o archivos grandes acumulados."],
    "OCT-MON-04": ["Polvo, rejillas tapadas, ventilador estropeado o el equipo trabajando a tope mucho rato."],
    "OCT-MON-05": ["Las baterías se gastan con los años y las cargas."],
    "OCT-MON-06": ["Muchos programas o pestañas abiertas a la vez, o un programa que no suelta la memoria."],
    "OCT-MON-07": ["Un programa colgado o trabajando muchísimo, una actualización, o algo malicioso (virus, minero)."],
    "OCT-MON-08": ["El equipo está apagado o sin red.", "El agente se ha parado."],
    "OCT-MON-09": ["Alguien lo ha desactivado a mano, otro antivirus lo ha sustituido o lo ha apagado un virus."],
    "OCT-MON-10": ["Polvo en los ventiladores, poca ventilación en la caja o juegos muy exigentes durante horas."],
    "OCT-MON-11": ["Cortes de luz o apagados del botón.", "Controladores (sobre todo de la gráfica) con fallos.",
                   "Calor, memoria o fuente de alimentación con problemas."],
    "OCT-MON-12": ["Una versión del programa con fallos, un complemento que no va bien o archivos del programa dañados."],
    "OCT-MON-13": ["Alguien lo apagó para que funcionara un programa o un juego en red.", "Otro programa de seguridad lo sustituyó.",
                   "Un virus lo apagó."],
    "OCT-MON-14": ["El cifrado no viene activado de fábrica en muchos portátiles.", "Windows Home no trae BitLocker."],
    "OCT-MON-15": ["Alguien probando contraseñas (a mano o con un programa, sobre todo si el equipo se ve desde Internet).",
                   "Un programa o una unidad de red con una contraseña vieja guardada."],
    "OCT-MON-16": ["Alguien de la empresa dio permisos de administrador a otra persona.",
                   "Un programa de instalación creó una cuenta.", "Un atacante creó una cuenta para quedarse dentro."],
    "OCT-MON-17": ["Se suspende o se bloquea en vez de apagarlo.", "Las actualizaciones pidiendo reinicio se van aplazando."],
    "OCT-MON-18": ["Se amplió la memoria, se cambió un disco o se reparó el equipo.", "Alguien se llevó una pieza."],
    "OCT-MON-19": ["Wifi lejos del router o con interferencias.", "El router necesita reiniciarse.",
                   "Un problema de la compañía de Internet."],
    "OCT-SEN-01": ["Un programa malicioso (ransomware) está cifrando o borrando archivos.",
                  "Muy raramente: alguien abrió y cambió el archivo trampa a mano."],
    "OCT-ALM-01": ["Un corte de luz o un reinicio del servidor a mitad de una tarea dejó el bloqueo puesto."],
    "OCT-ALM-02": ["Un fallo del disco del servidor.", "Un corte de luz mientras se escribía una copia."],
    "OCT-ALM-03": ["El almacén estaba bloqueado o muy ocupado.", "No había sitio libre para hacer la limpieza."],
    "OCT-DISCO-01": ["Se guardan muchas copias o se han añadido equipos o máquinas virtuales grandes."],
    "OCT-SRV-01": ["Sin Internet o con las claves del almacén externo caducadas.", "Sin sitio libre en el destino."],
    "OCT-SRV-02": ["El servidor estuvo apagado por la noche.", "El mantenimiento se quedó colgado (mira sus avisos)."],
    "OCT-SRV-03": ["El correo de avisos no está configurado o su contraseña ha cambiado."],
    "OCT-CERT-01": ["Los certificados duran un tiempo limitado por seguridad; este se acerca a su fecha."],
    "OCT-KIT-01": ["Nadie ha pulsado todavía «Descargar el kit» en Ajustes."],
    "OCT-ACT-01": ["Las actualizaciones automáticas están en pausa o la de esta noche no se pudo instalar."],
    "OCT-SUG-01": ["No había Internet o no hay ningún destino de soporte configurado."],
    "OCT-COMP-01": ["No había sitio libre en el servidor.", "El equipo se apagó o perdió la red a mitad (tarda horas)."],
    "OCT-BD-01": ["Ha cambiado la contraseña del usuario de la base de datos.", "El motor de la base de datos estaba parado.",
                  "No había sitio libre en el equipo para el volcado."],
    "OCT-BD-02": ["El motor de la base de datos estaba parado o sin sitio.", "La copia elegida está dañada."],
    "OCT-VM-01": ["VirtualBox en Linux o Mac con la máquina encendida (hay que apagarla).",
                  "Sin sitio libre en el servidor.", "El hipervisor estaba ocupado o la máquina se movió de sitio."],
    "OCT-VM-02": ["Sin sitio libre en el equipo.", "La copia elegida está incompleta."],
    "OCT-IMG-01": ["El disco USB no estaba conectado o la carpeta de red no se veía.", "No había sitio en el destino.",
                   "Estabas usando el ordenador a fondo y se dejó para luego (es normal)."],
    "OCT-REC-01": ["El equipo se apagó o perdió la red a mitad.", "No había sitio libre.",
                   "Algún archivo estaba abierto y no se pudo poner."],
    "OCT-PASAR-01": ["El ordenador nuevo se apagó o perdió la red a mitad.", "No había sitio libre en el ordenador nuevo."],
    "OCT-NUBE-01": ["El permiso de la cuenta de Microsoft 365 o Google ha caducado o se ha quitado.",
                    "Sin Internet en el servidor."],
    "OCT-RED-01": ["El servidor no tiene Internet para descargar el rescate la primera vez.",
                   "Falta la dirección del servidor (OCTOPUS_IP) o el cortafuegos del servidor lo bloquea.",
                   "El servidor no es Linux (el arranque por red solo funciona en servidores Linux)."],
    "OCT-RES-01": ["El código se ha escrito mal, ya se usó (vale una vez) o ha pasado más de una hora."],
    "OCT-RES-02": ["No hay cable de red, la dirección está mal escrita o el servidor está apagado."],
    "OCT-RES-03": ["El disco nuevo es más pequeño que lo que ocupaba el sistema copiado."],
    "OCT-RES-04": ["La copia es de un sistema sin GRUB (o se borró) o no es una «copia completa»."],
    "OCT-DESP-01": ["Ha pasado el tiempo de la tanda, se llegó al máximo de ordenadores o se terminó a mano."],
    "OCT-LOGIN-01": ["Contraseña olvidada, bloqueo por muchos intentos o el correo de recuperación no está configurado."],
    "OCT-2FA-01": ["Móvil perdido, roto o cambiado sin pasar la aplicación de códigos."],
}
for _c, _l in CAUSAS.items():
    CATALOGO[_c]["causas"] = _l

# Trabajo que ha fallado (tipo + lo que se estaba haciendo) -> aviso
_TRABAJO_CODIGO = {"copia_bd": "OCT-BD-01", "recuperacion_bd": "OCT-BD-02", "copia_vms": "OCT-VM-01",
                   "recuperacion_vm": "OCT-VM-02", "imagen": "OCT-IMG-01", "completa": "OCT-COMP-01",
                   "recuperacion": "OCT-REC-01", "pasar": "OCT-PASAR-01", "copia": "OCT-EQ-04"}


def codigo_trabajo(tipo: str, que: str = "") -> str | None:
    """El aviso de un trabajo (copia, recuperación...) que ha terminado mal. None: no lleva aviso propio (los ajustes
    que se hacen desde «Solucionar» enseñan su resultado debajo del aviso que los pidió)."""
    if tipo == "ajuste":
        return None
    q = (que or "").lower()
    if tipo == "copia" and "completa" in q:
        return "OCT-COMP-01"
    if tipo == "copia" and "imagen de disco" in q:
        return "OCT-IMG-01"
    if tipo == "recuperacion" and "máquina virtual" in q:
        return "OCT-VM-02"
    if tipo == "recuperacion" and q.startswith("pasando"):
        return "OCT-PASAR-01"
    return _TRABAJO_CODIGO.get(tipo, "OCT-EQ-04")


def ficha(codigo: str, **datos) -> dict:
    """El aviso completo y ya rellenado para un caso concreto."""
    c = dict(CATALOGO.get(codigo) or {"nivel": "atencion", "titulo": codigo, "por_que": "", "pasos": [], "accion": None})
    datos = {k: ("" if v is None else v) for k, v in datos.items()}
    datos.setdefault("equipo", "")
    datos.setdefault("detalle", "")

    def rellenar(t: str) -> str:
        try:
            return t.format(**datos)
        except (KeyError, IndexError, ValueError):
            return t
    pasos = [rellenar(p) for p in c.get("pasos", [])]
    if not datos["detalle"]:
        pasos = [p for p in pasos if not p.rstrip().endswith(":")]
    return {"codigo": codigo, "nivel": c["nivel"], "titulo": rellenar(c["titulo"]), "por_que": c.get("por_que", ""),
            "causas": list(c.get("causas", [])), "pasos": pasos, "accion": c.get("accion"),
            "boton": c.get("boton", "Solucionar"), "enlace": c.get("enlace")}


def ficha_guia(codigo: str) -> dict:
    """Un aviso tal como sale en la guía (sin un equipo concreto)."""
    f = ficha(codigo, equipo="[equipo]", detalle="")
    f["titulo"] = CATALOGO[codigo]["titulo"].format(equipo="[equipo]", detalle="[detalle]")
    return f


def guia_markdown() -> str:
    """Todos los avisos, para SOLUCIONES.md (herramientas/generar_soluciones.py) y la guía del panel."""
    grupos = [("OCT-EQ", "Equipos y copias"), ("OCT-COMP", "Copia completa"), ("OCT-BD", "Bases de datos"),
              ("OCT-VM", "Máquinas virtuales"), ("OCT-IMG", "Imagen de disco de Windows"),
              ("OCT-REC", "Recuperar archivos"), ("OCT-PASAR", "Pasar a un ordenador nuevo"),
              ("OCT-NUBE", "Copia de Microsoft 365 y Google"), ("OCT-MON", "Monitorización"),
              ("OCT-SEN", "Ataques"), ("OCT-ALM", "Almacén de copias"), ("OCT-DISCO", "Almacén de copias"),
              ("OCT-SRV", "Servidor"), ("OCT-CERT", "Servidor"), ("OCT-KIT", "Servidor"), ("OCT-ACT", "Servidor"),
              ("OCT-SUG", "Servidor"), ("OCT-RED", "Arranque por red"), ("OCT-RES", "USB de rescate"),
              ("OCT-DESP", "Desplegar en varios equipos"), ("OCT-LOGIN", "Entrar en el panel"),
              ("OCT-2FA", "Entrar en el panel")]
    out = ["# Qué hacer si algo falla", "",
           "Cada problema que OCTOPUS detecta sale en el panel (**Avisos**), en el correo y en Telegram con un **código**",
           "(por ejemplo `OCT-EQ-04`). Aquí están todos: busca el código (Ctrl+F) y verás **qué pasa**, **por qué suele",
           "pasar** y **cómo se arregla**. Muchos se arreglan solos o con el botón «Solucionar» del panel.", "",
           "> Este archivo se genera solo desde `lib/avisos.py` (`python3 herramientas/generar_soluciones.py`): no lo",
           "> edites a mano.", ""]
    hecho = set()
    for pref, nombre in grupos:
        codigos = [c for c in CATALOGO if c.rsplit("-", 1)[0] == pref and c not in hecho]
        if not codigos:
            continue
        if f"## {nombre}" not in out:
            out += [f"## {nombre}", ""]
        for c in codigos:
            hecho.add(c)
            f = ficha_guia(c)
            out += [f"### {c} · {f['titulo']}", "",
                    f"**Qué pasa / por qué importa:** {f['por_que']}", ""]
            if f["causas"]:
                out += ["**Por qué suele pasar:**", ""] + [f"- {x}" for x in f["causas"]] + [""]
            out += ["**Cómo se arregla:**", ""] + [f"{i}. {p}" for i, p in enumerate(f["pasos"], 1)] + [""]
            if f["accion"]:
                out += ["En el panel, este aviso tiene el botón **«Solucionar»**.", ""]
    return "\n".join(out).rstrip() + "\n"


def texto(codigo: str, **datos) -> str:
    """El aviso en texto plano (correo, Telegram, registro)."""
    f = ficha(codigo, **datos)
    lineas = [f"[{codigo}] {f['titulo']}", f"Por qué importa: {f['por_que']}"]
    if f["causas"]:
        lineas.append("Por qué suele pasar: " + " / ".join(f["causas"]))
    lineas.append("Qué hacer:")
    lineas += [f"  {i}. {p}" for i, p in enumerate(f["pasos"], 1)]
    if f["accion"]:
        try:
            import autoarreglo as _aa
            auto, riesgo = _aa.es_automatica(f["accion"]), _aa.riesgo(f["accion"])
        except Exception:
            auto, riesgo = False, None
        if auto:
            lineas.append("  (No tiene riesgo: OCTOPUS lo está arreglando solo. Si tienes prisa, en el panel, Avisos, "
                          "pulsa «Solucionar».)")
        elif riesgo:
            lineas.append(f"  (Necesita tu permiso porque puede borrar datos: {riesgo} Para hacerlo, en el panel, "
                          f"Avisos, pulsa «Solucionar» y confírmalo.)")
        else:
            lineas.append("  (En el panel, en Avisos, hay un botón «Solucionar» que lo hace solo.)")
    return "\n".join(lineas)


# ---------------------------------------------------------------- comprobaciones del servidor
def codigo_mantenimiento(tarea: str, resultado: dict) -> str | None:
    """Codigo del aviso para una tarea del mantenimiento que ha fallado."""
    det = str(resultado.get("detalle") or "").lower()
    if tarea == "verificar":
        return "OCT-ALM-01" if "lock" in det else "OCT-ALM-02"
    if tarea == "retencion":
        return "OCT-ALM-01" if "lock" in det else "OCT-ALM-03"
    if tarea == "vigilar":
        return "OCT-DISCO-01" if resultado.get("disco_lleno") else None
    return {"autocopia": "OCT-SRV-01", "informe": "OCT-SRV-03", "copia_nube": "OCT-NUBE-01"}.get(tarea)


def caducidad_certificado() -> int | None:
    """Dias que le quedan al certificado del servidor (None si no se puede saber)."""
    crt = DATA / "tls" / "panel.crt"
    if not crt.is_file():
        return None
    try:
        import configuracion
        return configuracion.caducidad(crt)
    except Exception:
        return None


def mantenimiento_atrasado(estado: dict, db_file: Path | None = None) -> str | None:
    """Texto si el mantenimiento nocturno lleva mas de 36 h sin hacerse; None si va bien."""
    fecha = estado.get("fecha")
    if fecha:
        try:
            t = datetime.fromisoformat(fecha)
            horas = (datetime.now(t.tzinfo or timezone.utc) - t).total_seconds() / 3600
            return f"el último fue hace {int(horas)} horas" if horas > 36 else None
        except ValueError:
            return None
    # nunca se ha hecho: solo se avisa si el servidor ya lleva mas de 36 h instalado
    try:
        if db_file and db_file.is_file() and time.time() - db_file.stat().st_mtime > 0:
            creado = min(db_file.stat().st_ctime, db_file.stat().st_mtime)
            if time.time() - creado > 36 * 3600 and not (DATA / "mantenimiento.json").exists():
                return "todavía no se ha hecho ninguno"
    except OSError:
        pass
    return None


def version_local() -> str:
    for f in (BASE_DIR / "VERSION",):
        try:
            return f.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return os.environ.get("OCTOPUS_VERSION", "")


def _num(v: str) -> tuple:
    partes = []
    for p in str(v).strip().lstrip("vV").split("."):
        try:
            partes.append(int("".join(ch for ch in p if ch.isdigit()) or 0))
        except ValueError:
            partes.append(0)
    return tuple(partes)


def comprobar_actualizacion(timeout: float = 15) -> dict:
    """Mira la ultima version publicada (archivo VERSION del repositorio). Se guarda para el panel.
    Se puede desactivar con OCTOPUS_COMPROBAR_ACTUALIZACIONES=no o cambiar la URL con OCTOPUS_URL_VERSION."""
    import urllib.request
    cfg = dict(os.environ)
    try:
        import mantenimiento as _m
        cfg.update(_m.leer_env())
    except Exception:
        pass
    if cfg.get("OCTOPUS_COMPROBAR_ACTUALIZACIONES", "si").lower() in ("no", "0", "false"):
        return {"ok": True, "hay_nueva": False, "detalle": "comprobación desactivada"}
    url = cfg.get("OCTOPUS_URL_VERSION") or "https://raw.githubusercontent.com/josemurajo/OCTOPUS/publicado/VERSION"
    local = version_local()
    res = {"fecha": datetime.now().astimezone().isoformat(timespec="seconds"), "local": local}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "octopus"}),
                                    timeout=timeout) as r:
            remota = r.read(64).decode("utf-8", "replace").strip()
        res.update(remota=remota, hay_nueva=bool(local and remota and _num(remota) > _num(local)))
        res["ok"] = True
        res["detalle"] = f"versión nueva {remota}" if res["hay_nueva"] else f"al día ({local})"
    except Exception as exc:  # sin Internet no es un fallo del servidor
        res.update(ok=True, hay_nueva=False, detalle=f"no se pudo comprobar ({exc.__class__.__name__})")
    try:
        ACTUALIZACION_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTUALIZACION_FILE.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return res


def leer_actualizacion() -> dict:
    try:
        act = json.loads(ACTUALIZACION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # si ya se ha actualizado desde la ultima comprobacion, deja de haber version nueva
    local = version_local()
    if act.get("hay_nueva") and local and _num(local) >= _num(act.get("remota", "")):
        act.update(hay_nueva=False, local=local, detalle=f"al día ({local})")
    return act


# ---------------------------------------------------------------- acciones automaticas del servidor
def _env_mant():
    import mantenimiento as m
    return m, m.leer_env()


def _comprobar(m, e, timeout: int, intentos: int = 10) -> tuple[bool, str]:
    """restic check. Si el almacen esta ocupado por una copia en curso (bloqueo vivo), espera y lo reintenta:
    eso no es un error del almacen, y antes se contaba como «sigue con errores»."""
    for i in range(intentos):
        r = m.run([m.restic_bin(), "check"], env=e, timeout=timeout)
        if r.returncode == 0:
            return True, "correcto"
        salida = (r.stderr or "") + (r.stdout or "")
        if "locked" not in salida.lower():
            return False, "sigue con errores: " + salida.strip()[-200:]
        time.sleep(30)
    return False, "ocupado por una copia en curso; se volvera a intentar"


def desbloquear_almacen() -> dict:
    m, env = _env_mant()
    partes, ok = [], True
    for cuarentena in (False, True):
        repo, pwd = m.repo_local(env, cuarentena)
        if not repo or not os.path.isdir(repo):
            continue
        e = m.restic_env(repo, pwd)
        m.run([m.restic_bin(), "unlock"], env=e, timeout=300)
        bien, texto = _comprobar(m, e, 3600)
        ok = ok and bien
        partes.append(f"{os.path.basename(repo)}: {texto}")
    if not partes:
        return {"ok": False, "detalle": "No se encuentra el almacén en disco"}
    return {"ok": ok, "detalle": "Bloqueos quitados. " + "; ".join(partes)}


def reparar_almacen() -> dict:
    m, env = _env_mant()
    partes, ok = [], True
    for cuarentena in (False, True):
        repo, pwd = m.repo_local(env, cuarentena)
        if not repo or not os.path.isdir(repo):
            continue
        e = m.restic_env(repo, pwd)
        m.run([m.restic_bin(), "unlock"], env=e, timeout=300)
        rep = m.run([m.restic_bin(), "repair", "index"], env=e, timeout=6 * 3600)
        if rep.returncode != 0 and "unknown command" in (rep.stderr or "").lower():
            m.run([m.restic_bin(), "rebuild-index"], env=e, timeout=6 * 3600)
        bien, texto = _comprobar(m, e, 6 * 3600)
        ok = ok and bien
        partes.append(f"{os.path.basename(repo)}: {texto}")
    if not partes:
        return {"ok": False, "detalle": "No se encuentra el almacén en disco"}
    return {"ok": ok, "detalle": "; ".join(partes)}


def limpiar_copias() -> dict:
    m, env = _env_mant()
    return m.retencion(env)


def copia_servidor() -> dict:
    m, env = _env_mant()
    return m.autocopia(env)


def mantenimiento_ahora() -> dict:
    log = DATA / "logs"
    log.mkdir(parents=True, exist_ok=True)
    with open(log / "mantenimiento.log", "a", encoding="utf-8") as fh:
        subprocess.Popen([sys.executable, str(BASE_DIR / "lib" / "mantenimiento.py"), "todo"],
                         cwd=str(BASE_DIR), stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    return {"ok": True, "detalle": "Mantenimiento en marcha. En unos minutos verás el resultado en Ajustes.",
            "en_marcha": True}


def renovar_certificado() -> dict:
    import configuracion
    tls = DATA / "tls"
    try:
        (tls / "nombres.txt").unlink(missing_ok=True)   # obliga a emitir uno nuevo (misma autoridad)
        configuracion.certificado_tls()
        configuracion.config_agentes()
    except Exception as exc:
        return {"ok": False, "detalle": f"No se pudo emitir el certificado: {exc}"}
    dias = caducidad_certificado()
    try:  # el arranque del contenedor reinicia el panel y el almacen para que usen el certificado nuevo
        REINICIAR_FLAG.write_text(str(time.time() + 3), encoding="utf-8")
    except OSError:
        pass
    return {"ok": bool(dias and dias > 30), "detalle": f"Certificado nuevo, válido {dias} días. El panel se reinicia "
                                                     f"en unos segundos: si no carga, recarga la página."}


def comprobar_actualizacion_ahora() -> dict:
    r = comprobar_actualizacion()
    return {"ok": not r.get("hay_nueva"), "detalle": "Sigue habiendo una versión nueva: actualiza siguiendo los pasos."
            if r.get("hay_nueva") else f"Comprobado: {r.get('detalle')}"}


ACCIONES_SERVIDOR = {
    "desbloquear_almacen": desbloquear_almacen,
    "reparar_almacen": reparar_almacen,
    "limpiar_copias": limpiar_copias,
    "copia_servidor": copia_servidor,
    "mantenimiento_ahora": mantenimiento_ahora,
    "renovar_certificado": renovar_certificado,
    "comprobar_actualizacion": comprobar_actualizacion_ahora,
}
