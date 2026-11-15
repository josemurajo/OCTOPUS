# Qué hacer si algo falla

Cada problema que OCTOPUS detecta sale en el panel (**Avisos**), en el correo y en Telegram con un **código**
(por ejemplo `OCT-EQ-04`). Aquí están todos: busca el código (Ctrl+F) y verás **qué pasa**, **por qué suele
pasar** y **cómo se arregla**. Muchos se arreglan solos o con el botón «Solucionar» del panel.

> Este archivo se genera solo desde `lib/avisos.py` (`python3 herramientas/generar_soluciones.py`): no lo
> edites a mano.

## Equipos y copias

### OCT-EQ-01 · No hay conexión con [equipo]

**Qué pasa / por qué importa:** Mientras no haya conexión no se hacen copias de este equipo y no se le puede proteger si le atacan.

**Por qué suele pasar:**

- El equipo está apagado, en suspensión o sin red.
- Se ha cambiado de red (otra wifi, VPN) y no llega al servidor.
- El agente de OCTOPUS se ha parado o lo ha quitado un antivirus.

**Cómo se arregla:**

1. Comprueba que el equipo está encendido y conectado a la red (y que no está en suspensión).
2. Si se acaba de reiniciar, espera 2 minutos: el agente vuelve a conectar solo.
3. Si sigue igual, reinicia el agente en ese equipo: en Windows, Programador de tareas → «OCTOPUS Agente» → Ejecutar; en Linux, sudo systemctl restart octopus-agent; en Mac, sudo launchctl kickstart -k system/com.octopus.agent.
4. Si nada de eso funciona, vuelve a instalar el agente desde la ficha del equipo (no se pierden copias).

### OCT-EQ-02 · [equipo] todavía no tiene ninguna copia

**Qué pasa / por qué importa:** Si este equipo se estropea o le atacan hoy, no habría nada que recuperar.

**Por qué suele pasar:**

- El equipo se acaba de añadir y aún no le ha tocado su copia diaria.
- No tiene ninguna carpeta elegida para copiar.

**Cómo se arregla:**

1. Pulsa «Solucionar» (o «Hacer copia ahora» en la ficha del equipo).
2. La primera copia puede tardar un rato; luego son mucho más rápidas.

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-EQ-03 · La última copia de [equipo] es de [detalle]

**Qué pasa / por qué importa:** Lo que se haya creado o cambiado desde entonces no está protegido.

**Por qué suele pasar:**

- El equipo ha estado apagado o fuera de la oficina.
- Las copias están fallando (mira si hay otro aviso).

**Cómo se arregla:**

1. Si el equipo estuvo apagado o de viaje, es normal: pulsa «Solucionar» para copiar ahora.
2. Si estaba encendido, revisa que tenga conexión; la copia diaria se hace sola cada día.
3. Para portátiles que pasan días fuera, puedes ampliar el plazo en su ficha («Aviso si se queda sin copia»).

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-EQ-04 · La última copia de [equipo] falló

**Qué pasa / por qué importa:** Este equipo se ha quedado sin copia reciente.

**Por qué suele pasar:**

- Se cortó la red a mitad de la copia.
- El equipo se apagó o entró en suspensión.
- No hay sitio libre en el servidor o en el equipo.
- Un archivo estaba bloqueado por un programa.

**Cómo se arregla:**

1. Pulsa «Solucionar» para repetirla (muchas veces es algo puntual: red, equipo en uso...).
2. Si vuelve a fallar, comprueba que el equipo tiene espacio libre y conexión con el servidor.

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-EQ-05 · La prueba de recuperación de [equipo] falló

**Qué pasa / por qué importa:** No se ha podido comprobar que sus copias se recuperan bien; podría fallar justo cuando haga falta.

**Por qué suele pasar:**

- La copia que se probó estaba incompleta.
- El almacén de copias tiene algún error (mira sus avisos).
- El equipo no tenía sitio para la prueba.

**Cómo se arregla:**

1. Pulsa «Solucionar»: se hace una copia nueva del equipo y se repite la prueba.
2. Si vuelve a fallar, revisa el aviso del almacén (si lo hay) y avisa al técnico.

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-EQ-06 · La última copia de [equipo] se hizo durante un ataque

**Qué pasa / por qué importa:** Esa copia puede contener archivos cifrados o dañados.

**Por qué suele pasar:**

- Mientras se hacía la copia, OCTOPUS detectó cifrado masivo o tocaron un archivo señuelo.

**Cómo se arregla:**

1. Si tienes que recuperar algo, usa una copia limpia (en la ficha del equipo se ve cuál es).
2. Cuando el equipo esté limpio, haz una copia nueva.

## Copia completa

### OCT-COMP-01 · La copia completa de [equipo] falló

**Qué pasa / por qué importa:** Sin ella no se puede dejar el equipo entero como estaba si se rompe el disco (sus carpetas siguen protegidas por la copia normal).

**Por qué suele pasar:**

- No había sitio libre en el servidor.
- El equipo se apagó o perdió la red a mitad (tarda horas).

**Cómo se arregla:**

1. Repítela desde la ficha del equipo («Copia completa del equipo» → «Hacer ahora»).
2. Si vuelve a fallar, mira que el servidor tenga sitio libre: la copia completa ocupa mucho.

## Bases de datos

### OCT-BD-01 · La copia de las bases de datos de [equipo] falló

**Qué pasa / por qué importa:** Lo que se haya guardado en esas bases de datos desde la última copia buena no está protegido.

**Por qué suele pasar:**

- Ha cambiado la contraseña del usuario de la base de datos.
- El motor de la base de datos estaba parado.
- No había sitio libre en el equipo para el volcado.

**Cómo se arregla:**

1. Abre la ficha del equipo → «Bases de datos» y revisa el usuario y la contraseña de cada base.
2. Si han cambiado, ponlos bien, pulsa «Guardar» y después «Copiar ahora».
3. Si el motor de la base de datos estaba parado, arráncalo y vuelve a copiar.

### OCT-BD-02 · No se pudo recuperar la base de datos de [equipo]

**Qué pasa / por qué importa:** La base de datos original NO se ha tocado: sigue como estaba.

**Por qué suele pasar:**

- El motor de la base de datos estaba parado o sin sitio.
- La copia elegida está dañada.

**Cómo se arregla:**

1. Comprueba que el motor de la base de datos está en marcha y que hay sitio libre en el disco.
2. Vuelve a intentarlo eligiendo otra hora (otra copia).

## Máquinas virtuales

### OCT-VM-01 · La copia de las máquinas virtuales de [equipo] falló

**Qué pasa / por qué importa:** Si una máquina virtual se estropea, no habría una copia reciente de ella entera.

**Por qué suele pasar:**

- VirtualBox en Linux o Mac con la máquina encendida (hay que apagarla).
- Sin sitio libre en el servidor.
- El hipervisor estaba ocupado o la máquina se movió de sitio.

**Cómo se arregla:**

1. Abre la ficha del equipo → «Máquinas virtuales» para ver cuáles se ven y en qué estado están.
2. Si es VirtualBox en Linux o Mac y la máquina estaba encendida: apágala y copia otra vez (en Windows se copia encendida).
3. Mira que el servidor tenga sitio libre: las máquinas virtuales ocupan mucho.

### OCT-VM-02 · No se pudo recuperar la máquina virtual de [equipo]

**Qué pasa / por qué importa:** La máquina original NO se ha tocado: sigue como estaba.

**Por qué suele pasar:**

- Sin sitio libre en el equipo.
- La copia elegida está incompleta.

**Cómo se arregla:**

1. Mira que el equipo tenga sitio libre para la copia recuperada (ocupa lo mismo que la máquina).
2. Vuelve a intentarlo; si falla, prueba con una copia anterior.

## Imagen de disco de Windows

### OCT-IMG-01 · La imagen de disco de [equipo] no se pudo hacer

**Qué pasa / por qué importa:** Si el ordenador deja de arrancar, la última imagen buena será más antigua.

**Por qué suele pasar:**

- El disco USB no estaba conectado o la carpeta de red no se veía.
- No había sitio en el destino.
- Estabas usando el ordenador a fondo y se dejó para luego (es normal).

**Cómo se arregla:**

1. Si pone «se deja para luego»: estaba usando el ordenador a fondo; se hará sola más tarde.
2. Mira que el disco USB esté conectado (o que la carpeta de red se vea) y que tenga sitio libre.
3. En la ficha del equipo → «Copia imagen de disco» → «Hacer una imagen ahora» para repetirla.

## Recuperar archivos

### OCT-REC-01 · La recuperación de archivos en [equipo] no se terminó

**Qué pasa / por qué importa:** Puede que solo se hayan recuperado algunos archivos. Lo que ya había en el equipo no se borra.

**Por qué suele pasar:**

- El equipo se apagó o perdió la red a mitad.
- No había sitio libre.
- Algún archivo estaba abierto y no se pudo poner.

**Cómo se arregla:**

1. Comprueba que el equipo sigue encendido y con conexión.
2. Mira que tenga sitio libre en el disco donde se recupera.
3. Vuelve a intentarlo desde la ficha del equipo; si falla, prueba con otra copia.

## Pasar a un ordenador nuevo

### OCT-PASAR-01 · No se pudo pasar todo a [equipo]

**Qué pasa / por qué importa:** Algunas carpetas no han llegado al ordenador nuevo. Lo que ya tenía no se sobrescribe nunca.

**Por qué suele pasar:**

- El ordenador nuevo se apagó o perdió la red a mitad.
- No había sitio libre en el ordenador nuevo.

**Cómo se arregla:**

1. Comprueba que el ordenador nuevo sigue encendido y conectado.
2. Mira que tenga sitio libre en el disco.
3. Repite «Pasar a un ordenador nuevo» solo con las carpetas que falten: lo que ya llegó no se duplica.

## Copia de Microsoft 365 y Google

### OCT-NUBE-01 · La copia de Microsoft 365 / Google ha fallado

**Qué pasa / por qué importa:** Los correos y archivos de la nube de anoche no se han copiado.

**Por qué suele pasar:**

- El permiso de la cuenta de Microsoft 365 o Google ha caducado o se ha quitado.
- Sin Internet en el servidor.

**Cómo se arregla:**

1. Ve a «Copia de la nube» y vuelve a poner los datos de la cuenta (botón «Actualizar»): los permisos de Microsoft 365 y Google caducan cada cierto tiempo.
2. Comprueba que el servidor tiene Internet.

## Monitorización

### OCT-MON-01 · El disco de [equipo] está fallando

**Qué pasa / por qué importa:** Un disco que falla puede dejar de funcionar en cualquier momento, y con él todo lo que no tenga copia.

**Por qué suele pasar:**

- El disco está estropeándose (lo dice el propio disco: SMART).

**Cómo se arregla:**

1. Pulsa «Hacer copia ahora» en la ficha del equipo para tener lo último a salvo.
2. Cambia el disco cuanto antes (con la copia completa se puede dejar el equipo como estaba).

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-MON-02 · El disco de [equipo] está muy gastado

**Qué pasa / por qué importa:** Ha usado casi toda la vida que da el fabricante: puede empezar a fallar.

**Por qué suele pasar:**

- Los discos SSD tienen una vida de escrituras; este la ha gastado casi entera.

**Cómo se arregla:**

1. Planifica cambiarlo en las próximas semanas.
2. Mientras, comprueba que sus copias se hacen bien.

### OCT-MON-03 · El disco de [equipo] está casi lleno

**Qué pasa / por qué importa:** Con el disco lleno el equipo va lento, algunos programas fallan y puede que no se puedan hacer copias.

**Por qué suele pasar:**

- Descargas, papelera, programas o archivos grandes acumulados.

**Cómo se arregla:**

1. Vacía la papelera y borra lo que no hace falta (descargas, temporales).
2. Si siempre está lleno, amplía el disco.

### OCT-MON-04 · [equipo] se está calentando mucho

**Qué pasa / por qué importa:** El calor mantenido acorta la vida del equipo y puede hacer que se apague solo.

**Por qué suele pasar:**

- Polvo, rejillas tapadas, ventilador estropeado o el equipo trabajando a tope mucho rato.

**Cómo se arregla:**

1. Comprueba que las rejillas de ventilación no estén tapadas.
2. Limpia el polvo y comprueba que el ventilador gira.

### OCT-MON-05 · La batería de [equipo] está muy gastada

**Qué pasa / por qué importa:** Puede durar muy poco o apagarse de golpe sin avisar, perdiendo lo que no esté guardado.

**Por qué suele pasar:**

- Las baterías se gastan con los años y las cargas.

**Cómo se arregla:**

1. Si el portátil dura poco o se apaga solo, cambia la batería.

### OCT-MON-06 · [equipo] va al límite de memoria

**Qué pasa / por qué importa:** Con la memoria llena todo va lento y los programas se pueden cerrar solos.

**Por qué suele pasar:**

- Muchos programas o pestañas abiertas a la vez, o un programa que no suelta la memoria.

**Cómo se arregla:**

1. Mira en Monitorización qué procesos gastan más memoria y cierra lo que no se use.
2. Si pasa a menudo, añade más memoria al equipo.

### OCT-MON-07 · El procesador de [equipo] lleva mucho rato al 100 %

**Qué pasa / por qué importa:** El equipo va lento, se calienta y gasta más; a veces es un programa colgado o algo que no debería estar ahí.

**Por qué suele pasar:**

- Un programa colgado o trabajando muchísimo, una actualización, o algo malicioso (virus, minero).

**Cómo se arregla:**

1. Mira en Monitorización qué proceso lo está usando.
2. Si no lo conoces o no debería estar funcionando, pide ayuda: puede ser un virus o un minero.

### OCT-MON-08 · [equipo] ha dejado de mandar datos de monitorización

**Qué pasa / por qué importa:** Lleva más de 30 minutos sin mandar datos: puede estar apagado, sin red o con el agente parado.

**Por qué suele pasar:**

- El equipo está apagado o sin red.
- El agente se ha parado.

**Cómo se arregla:**

1. Si está encendido y con red, reinicia el agente.
2. Si sigue igual, reinicia el agente en ese equipo: en Windows, Programador de tareas → «OCTOPUS Agente» → Ejecutar; en Linux, sudo systemctl restart octopus-agent; en Mac, sudo launchctl kickstart -k system/com.octopus.agent.

### OCT-MON-09 · El antivirus de [equipo] está desactivado

**Qué pasa / por qué importa:** Sin protección en tiempo real, un virus puede entrar sin que nadie lo pare.

**Por qué suele pasar:**

- Alguien lo ha desactivado a mano, otro antivirus lo ha sustituido o lo ha apagado un virus.

**Cómo se arregla:**

1. En el equipo: Seguridad de Windows → Protección antivirus → activar «Protección en tiempo real».
2. Si lo ha desactivado un programa que no conoces, pide ayuda.

### OCT-MON-10 · La tarjeta gráfica de [equipo] se está calentando mucho

**Qué pasa / por qué importa:** El calor mantenido hace que los juegos y programas vayan a tirones y acorta la vida de la tarjeta.

**Por qué suele pasar:**

- Polvo en los ventiladores, poca ventilación en la caja o juegos muy exigentes durante horas.

**Cómo se arregla:**

1. Limpia el polvo de la tarjeta y de los ventiladores de la caja.
2. Comprueba que la caja tiene aire: que no esté pegada a la pared ni encerrada en un mueble.
3. Si estás jugando, baja un poco los gráficos o limita los FPS en el juego.

### OCT-MON-11 · [equipo] se ha apagado de golpe o ha tenido pantallazos

**Qué pasa / por qué importa:** Cada apagado de golpe puede dañar archivos abiertos, y suele ser señal de un problema que irá a más.

**Por qué suele pasar:**

- Cortes de luz o apagados del botón.
- Controladores (sobre todo de la gráfica) con fallos.
- Calor, memoria o fuente de alimentación con problemas.

**Cómo se arregla:**

1. Si coincide con un corte de luz o con alguien apagándolo del botón, no hay que hacer nada.
2. Si no: instala las actualizaciones de Windows y de los controladores (sobre todo los de la gráfica).
3. Si sigue pasando, revisa la temperatura (en esta misma pantalla) y la memoria del equipo con un técnico.

### OCT-MON-12 · Un programa de [equipo] se cierra o se cuelga muy a menudo

**Qué pasa / por qué importa:** Se pierde trabajo cada vez, y a veces es el aviso de que algo está dañado.

**Por qué suele pasar:**

- Una versión del programa con fallos, un complemento que no va bien o archivos del programa dañados.

**Cómo se arregla:**

1. Actualiza ese programa a la última versión.
2. Si sigue igual, desinstálalo y vuelve a instalarlo.

### OCT-MON-13 · El cortafuegos de [equipo] está apagado

**Qué pasa / por qué importa:** El cortafuegos impide que otros equipos de la red entren en este. Apagado, es mucho más fácil atacarlo.

**Por qué suele pasar:**

- Alguien lo apagó para que funcionara un programa o un juego en red.
- Otro programa de seguridad lo sustituyó.
- Un virus lo apagó.

**Cómo se arregla:**

1. Windows: Seguridad de Windows → Firewall y protección de red → activa los tres perfiles.
2. Mac: Ajustes del Sistema → Red → Cortafuegos → activar.
3. Linux: sudo ufw enable (o el cortafuegos que use tu sistema).
4. Si lo apagó un programa que no conoces, pide ayuda.

### OCT-MON-14 · El portátil [equipo] no tiene el disco cifrado

**Qué pasa / por qué importa:** Si lo pierdes o te lo roban, cualquiera puede sacar el disco y leer todos los archivos.

**Por qué suele pasar:**

- El cifrado no viene activado de fábrica en muchos portátiles.
- Windows Home no trae BitLocker.

**Cómo se arregla:**

1. Windows Pro: busca «BitLocker» → «Activar BitLocker». Guarda la clave de recuperación fuera del portátil.
2. Windows Home: Configuración → Privacidad y seguridad → «Cifrado del dispositivo» (si aparece).
3. Mac: Ajustes del Sistema → Privacidad y seguridad → FileVault → activar.
4. Linux: el cifrado se elige al instalar el sistema; si no lo tiene, pide ayuda.

### OCT-MON-15 · Muchos intentos de contraseña fallidos en [equipo]

**Qué pasa / por qué importa:** Puede ser alguien probando contraseñas para entrar (a mano o con un programa).

**Por qué suele pasar:**

- Alguien probando contraseñas (a mano o con un programa, sobre todo si el equipo se ve desde Internet).
- Un programa o una unidad de red con una contraseña vieja guardada.

**Cómo se arregla:**

1. Pregunta a quien usa el equipo si se ha equivocado muchas veces (o si un programa guarda una contraseña vieja).
2. Si no: cambia la contraseña de ese usuario por una larga, y revisa si el equipo está abierto a Internet.

### OCT-MON-16 · Hay administradores nuevos en [equipo]

**Qué pasa / por qué importa:** Un administrador puede hacer de todo en el equipo. Los atacantes crean uno para quedarse dentro.

**Por qué suele pasar:**

- Alguien de la empresa dio permisos de administrador a otra persona.
- Un programa de instalación creó una cuenta.
- Un atacante creó una cuenta para quedarse dentro.

**Cómo se arregla:**

1. Si lo has creado tú o alguien de confianza, pulsa «Es correcto» en la monitorización de ese equipo.
2. Si no sabes quién es: quítale los permisos (Windows: Administración de equipos → Usuarios y grupos) y avisa a un técnico.

### OCT-MON-17 · [equipo] lleva semanas sin reiniciarse

**Qué pasa / por qué importa:** Muchas actualizaciones de seguridad no se aplican hasta reiniciar, y el equipo se va volviendo lento.

**Por qué suele pasar:**

- Se suspende o se bloquea en vez de apagarlo.
- Las actualizaciones pidiendo reinicio se van aplazando.

**Cómo se arregla:**

1. Reinícialo cuando no moleste (guarda antes lo que tengas abierto).

### OCT-MON-18 · Han cambiado piezas de [equipo]

**Qué pasa / por qué importa:** Si nadie lo ha hecho a propósito, puede que alguien haya quitado memoria o un disco (con tus datos).

**Por qué suele pasar:**

- Se amplió la memoria, se cambió un disco o se reparó el equipo.
- Alguien se llevó una pieza.

**Cómo se arregla:**

1. Si se ha ampliado o reparado el equipo, pulsa «Es correcto» en la monitorización de ese equipo.
2. Si no: revisa el equipo por dentro y pregunta quién lo ha tocado.

### OCT-MON-19 · Internet va mal en [equipo]

**Qué pasa / por qué importa:** Con cortes o lentitud fallan las webs, las videollamadas, los juegos en línea y las copias.

**Por qué suele pasar:**

- Wifi lejos del router o con interferencias.
- El router necesita reiniciarse.
- Un problema de la compañía de Internet.

**Cómo se arregla:**

1. Si va por wifi, prueba más cerca del router o con cable.
2. Reinicia el router (apagar, esperar 30 segundos y encender).
3. Si pasa en todos los equipos a la vez, llama a tu compañía de Internet con estos datos.

## Ataques

### OCT-SEN-01 · Alguien ha tocado un archivo señuelo en [equipo]

**Qué pasa / por qué importa:** Los archivos señuelo no los usa nadie: si cambian, casi seguro es un ataque (ransomware).

**Por qué suele pasar:**

- Un programa malicioso (ransomware) está cifrando o borrando archivos.
- Muy raramente: alguien abrió y cambió el archivo trampa a mano.

**Cómo se arregla:**

1. Abre el incidente en «Incidentes» y sigue los pasos (aislar el equipo, recuperar la última copia limpia).
2. No apagues el equipo a la fuerza: OCTOPUS ya ha guardado evidencias.

## Almacén de copias

### OCT-ALM-01 · El almacén de copias se ha quedado bloqueado

**Qué pasa / por qué importa:** Suele pasar tras un corte de luz o un reinicio a mitad de una tarea. Mientras siga bloqueado, la limpieza y la comprobación del almacén no se hacen.

**Por qué suele pasar:**

- Un corte de luz o un reinicio del servidor a mitad de una tarea dejó el bloqueo puesto.

**Cómo se arregla:**

1. Pulsa «Solucionar»: se quitan los bloqueos antiguos (no se borra ninguna copia) y se comprueba el almacén.
2. Si vuelve a pasar a menudo, revisa que el servidor no se apague de golpe (un SAI ayuda).

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-ALM-02 · La comprobación del almacén de copias ha encontrado errores

**Qué pasa / por qué importa:** Alguna copia podría no recuperarse bien.

**Por qué suele pasar:**

- Un fallo del disco del servidor.
- Un corte de luz mientras se escribía una copia.

**Cómo se arregla:**

1. No borres nada.
2. Pulsa «Solucionar»: se repara el índice del almacén y se vuelve a comprobar.
3. Si sigue con errores, revisa el disco del servidor y avisa al técnico. Si tienes almacén externo, tus copias siguen allí.

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-ALM-03 · La limpieza de copias antiguas no se pudo hacer

**Qué pasa / por qué importa:** Si no se limpian, el disco del servidor se va llenando.

**Por qué suele pasar:**

- El almacén estaba bloqueado o muy ocupado.
- No había sitio libre para hacer la limpieza.

**Cómo se arregla:**

1. Pulsa «Solucionar» para repetirla ahora.
2. Si falla otra vez, comprueba el espacio libre del servidor.

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-DISCO-01 · El disco del almacén está casi lleno

**Qué pasa / por qué importa:** Si se llena, las copias nuevas dejarán de hacerse.

**Por qué suele pasar:**

- Se guardan muchas copias o se han añadido equipos o máquinas virtuales grandes.

**Cómo se arregla:**

1. Pulsa «Solucionar»: se borran las copias que ya no hacen falta según cuántas has elegido guardar.
2. Si sigue casi lleno, guarda menos copias (Ajustes → Copias e informes) o amplía el disco del servidor.

En el panel, este aviso tiene el botón **«Solucionar»**.

## Servidor

### OCT-SRV-01 · La copia del propio servidor ha fallado

**Qué pasa / por qué importa:** Sin ella, si se pierde el servidor sería más difícil recuperarlo todo.

**Por qué suele pasar:**

- Sin Internet o con las claves del almacén externo caducadas.
- Sin sitio libre en el destino.

**Cómo se arregla:**

1. Pulsa «Solucionar» para repetirla ahora.
2. Si usas almacén externo, comprueba la conexión a Internet y que sus claves siguen siendo válidas (sudo bash octopus.sh ajustes).

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-SRV-02 · El mantenimiento nocturno no se ha hecho

**Qué pasa / por qué importa:** Es el que limpia copias viejas, comprueba el almacén, hace la copia del servidor y prueba recuperaciones.

**Por qué suele pasar:**

- El servidor estuvo apagado por la noche.
- El mantenimiento se quedó colgado (mira sus avisos).

**Cómo se arregla:**

1. Pulsa «Solucionar» para hacerlo ahora (tarda unos minutos; el resultado sale en Ajustes).
2. Si el servidor estuvo apagado por la noche, es normal; déjalo encendido.

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-SRV-03 · El informe mensual no se pudo enviar

**Qué pasa / por qué importa:** No te llegará el resumen del mes por correo (el informe se puede ver igualmente en Ajustes).

**Por qué suele pasar:**

- El correo de avisos no está configurado o su contraseña ha cambiado.

**Cómo se arregla:**

1. Revisa el correo de avisos en Ajustes → Avisos por correo y pulsa «Enviar prueba».

### OCT-CERT-01 · El certificado de seguridad del servidor caduca pronto

**Qué pasa / por qué importa:** Cuando caduque, los equipos dejarán de conectar con el servidor.

**Por qué suele pasar:**

- Los certificados duran un tiempo limitado por seguridad; este se acerca a su fecha.

**Cómo se arregla:**

1. Pulsa «Solucionar»: se emite uno nuevo con la misma autoridad (los equipos lo aceptan sin tocarlos) y el panel se reinicia unos segundos.

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-KIT-01 · Todavía no has descargado el kit de recuperación

**Qué pasa / por qué importa:** Sin él, si se pierde este servidor nadie podría abrir las copias.

**Por qué suele pasar:**

- Nadie ha pulsado todavía «Descargar el kit» en Ajustes.

**Cómo se arregla:**

1. Ve a Ajustes → Kit de recuperación y descárgalo.
2. Guárdalo fuera del servidor: pendrive, gestor de contraseñas o en papel en un sitio seguro.

### OCT-ACT-01 · Hay una versión nueva de OCTOPUS ([detalle])

**Qué pasa / por qué importa:** Las versiones nuevas traen arreglos y mejoras de seguridad.

**Por qué suele pasar:**

- Las actualizaciones automáticas están en pausa o la de esta noche no se pudo instalar.

**Cómo se arregla:**

1. Normalmente se instala sola por la noche. Si ves este aviso es porque las actualizaciones automáticas están en pausa, o porque no se pudo instalar sola: ve a Ajustes → Actualizaciones y pulsa «Actualizar ahora» (el servidor la descarga, comprueba que está firmada por OCTOPUS y la instala; si algo va mal, vuelve solo a la versión actual).
2. Si ese botón dice que el actualizador no está activado (servidores Windows), en el servidor: sudo bash octopus.sh actualizar (en Windows: octopus.ps1 actualizar). Se conservan los datos y las copias.
3. Pulsa «Solucionar» para volver a comprobar si ya estás al día.

En el panel, este aviso tiene el botón **«Solucionar»**.

### OCT-SUG-01 · Hay sugerencias o problemas sin enviar al soporte

**Qué pasa / por qué importa:** Se guardaron porque no había a dónde enviarlos o no había conexión.

**Por qué suele pasar:**

- No había Internet o no hay ningún destino de soporte configurado.

**Cómo se arregla:**

1. Pulsa «Solucionar» para intentar enviarlos otra vez.
2. Si no hay ningún destino de soporte configurado, se quedan guardados en el servidor.

En el panel, este aviso tiene el botón **«Solucionar»**.

## Arranque por red

### OCT-RED-01 · El arranque por red no se ha podido encender

**Qué pasa / por qué importa:** Los ordenadores no podrán arrancar el rescate por red (con el pendrive sí).

**Por qué suele pasar:**

- El servidor no tiene Internet para descargar el rescate la primera vez.
- Falta la dirección del servidor (OCTOPUS_IP) o el cortafuegos del servidor lo bloquea.
- El servidor no es Linux (el arranque por red solo funciona en servidores Linux).

**Cómo se arregla:**

1. Mira el detalle de abajo y la parte «Qué está haciendo» de Equipos → Arranque por red.
2. Si dice que no puede descargar el rescate: el servidor necesita Internet la primera vez.
3. Si los ordenadores no lo ven: en el servidor, sudo bash octopus.sh abrir-arranque-red (cortafuegos).
4. Pulsa «Apagar» y «Encender» otra vez.

## USB de rescate

### OCT-RES-01 · USB de rescate: el código no vale

**Qué pasa / por qué importa:** Sin un código bueno, el rescate no puede llegar a las copias (es lo que las protege).

**Por qué suele pasar:**

- El código se ha escrito mal, ya se usó (vale una vez) o ha pasado más de una hora.

**Cómo se arregla:**

1. Pide un código nuevo en el panel: ficha del equipo → «USB de rescate» → «Dar código».
2. Escríbelo sin prisas: son 12 letras y números (no hay O ni 0, ni I ni 1).

### OCT-RES-02 · USB de rescate: no llega al servidor

**Qué pasa / por qué importa:** El rescate necesita hablar con el servidor de OCTOPUS para traer las copias.

**Por qué suele pasar:**

- No hay cable de red, la dirección está mal escrita o el servidor está apagado.

**Cómo se arregla:**

1. Pon el cable de red (el rescate no usa wifi).
2. Escribe la dirección tal cual sale en el panel, junto al código (por ejemplo https://192.168.1.10:8080).
3. Comprueba que el servidor de OCTOPUS está encendido (desde otro ordenador se tiene que abrir el panel).

### OCT-RES-03 · USB de rescate: el disco es pequeño

**Qué pasa / por qué importa:** La copia completa no cabe en el disco elegido.

**Por qué suele pasar:**

- El disco nuevo es más pequeño que lo que ocupaba el sistema copiado.

**Cómo se arregla:**

1. Usa un disco igual o más grande que el del ordenador original.
2. O saca solo los archivos a un disco USB («Sacar los archivos»).

### OCT-RES-04 · USB de rescate: no se puede hacer arrancable

**Qué pasa / por qué importa:** El sistema copiado no tiene su programa de arranque (GRUB) o le faltan piezas.

**Por qué suele pasar:**

- La copia es de un sistema sin GRUB (o se borró) o no es una «copia completa».

**Cómo se arregla:**

1. Los archivos SÍ están en el disco: puedes sacarlos con «Sacar los archivos».
2. Instala el sistema de cero en ese disco y después usa «Pasar a un ordenador nuevo» para traer tus carpetas.

## Desplegar en varios equipos

### OCT-DESP-01 · Despliegue: el código ya no vale

**Qué pasa / por qué importa:** La tanda se ha terminado: pasó el tiempo, se llegó al máximo de ordenadores o alguien pulsó «Terminar».

**Por qué suele pasar:**

- Ha pasado el tiempo de la tanda, se llegó al máximo de ordenadores o se terminó a mano.

**Cómo se arregla:**

1. En el panel: Equipos → «Desplegar en varios equipos» → «Dar código del despliegue» para una tanda nueva.

## Entrar en el panel

### OCT-LOGIN-01 · No puedo entrar en el panel

**Qué pasa / por qué importa:** Sin entrar no se pueden ver los avisos ni recuperar nada (las copias siguen haciéndose solas).

**Por qué suele pasar:**

- Contraseña olvidada, bloqueo por muchos intentos o el correo de recuperación no está configurado.

**Cómo se arregla:**

1. Si has olvidado la contraseña: en la pantalla de entrada, «He olvidado mi contraseña» (llega un correo).
2. Si has probado muchas veces, espera 15 minutos: OCTOPUS bloquea un rato a quien falla mucho.
3. Si te has quedado fuera (bloqueado, o el panel solo se abre desde la oficina), en el servidor: sudo bash octopus.sh acceso-emergencia (en Windows: octopus.ps1 acceso-emergencia).

### OCT-2FA-01 · He perdido el móvil de la doble autenticación

**Qué pasa / por qué importa:** Sin el código del móvil no se puede entrar en el panel.

**Por qué suele pasar:**

- Móvil perdido, roto o cambiado sin pasar la aplicación de códigos.

**Cómo se arregla:**

1. Usa uno de los 10 códigos de emergencia que te enseñó al activarla.
2. Si no los tienes, otro administrador puede quitártela en Usuarios.
3. Si eres el único, en el servidor: sudo bash octopus.sh quitar-2fa TU_USUARIO (en Windows: octopus.ps1 quitar-2fa TU_USUARIO). Te pedirá el código del kit de recuperación.
