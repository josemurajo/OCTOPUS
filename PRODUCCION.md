# OCTOPUS Zero-Touch en una empresa

Guía para instalar OCTOPUS de verdad, dejarlo bien protegido y saber qué hacer si algo va mal.
Todas las órdenes se ejecutan en el servidor, dentro de la carpeta de OCTOPUS.

## 1. Lo que hace falta

- **Un servidor Linux** recién instalado (Ubuntu 22.04/24.04, Debian 12, Rocky/Alma 9 o Fedora), con 2 GB de RAM
  y disco suficiente para las copias (como orientación, el doble de lo que ocupan los datos que se van a copiar).
- **Una IP fija** en la red de la empresa (o un nombre DNS). Los equipos se conectan siempre a esa dirección.
- Desde los equipos tienen que llegar al servidor **dos puertos TCP**: **8080** (panel y órdenes) y **8000** (copias).
  Los dos van cifrados. En los equipos no hay que abrir nada.
- **Muy recomendado:** un almacén externo (otro servidor por SFTP, o S3/Backblaze/Wasabi). Ver el apartado 5.

## 2. Instalar

```bash
sudo bash instalar_servidor.sh
```

Si el servidor tiene varias IP o los equipos van a entrar por un nombre, indícalo:

```bash
sudo OCTOPUS_IP=192.168.1.10 bash instalar_servidor.sh
sudo OCTOPUS_IP=192.168.1.10 OCTOPUS_NOMBRES_EXTRA=octopus.empresa.local bash instalar_servidor.sh
```

El instalador pone Docker si falta, arranca OCTOPUS, abre los puertos en el cortafuegos del servidor y muestra
la dirección del panel y la **contraseña inicial** (de un solo uso). Si la pierdes: `sudo bash octopus.sh credenciales`.

**Linux es lo recomendado** para el servidor. También se puede instalar en:

- **Windows 10 (22H2) / 11 / Server:** doble clic en `INSTALAR_SERVIDOR_WINDOWS.bat`. Activa WSL2 (la primera vez
  puede pedir reiniciar y volver a ejecutarlo), instala Rancher Desktop (gratis, de código abierto) si no hay Docker,
  arranca OCTOPUS, abre los puertos en el Firewall de Windows y comprueba que se llega desde la red.
  Gestión: `octopus.ps1` (lo mismo que `octopus.sh`). *Probado solo en la sintaxis: falta probarlo en un Windows real.*
- **Mac (macOS 13 o posterior):** `bash instalar_servidor_mac.sh` con tu usuario (sin sudo). Instala con Homebrew
  Colima + Docker (gratis, sin Docker Desktop) y arranca OCTOPUS. Gestión: `bash octopus.sh ...` (sin sudo).
  *Probado en un Mac real de GitHub.*

En Windows y Mac el equipo tiene que quedarse **encendido y con la sesión iniciada** (Rancher Desktop / Colima
arrancan al iniciar sesión) y sin entrar en reposo.

## 3. Primeros pasos en el panel

1. Entra en `https://<ip-del-servidor>:8080` con el usuario **admin** y la contraseña inicial. El navegador
   avisa de que el certificado no es de confianza: es normal, lo crea el propio OCTOPUS. Elige una contraseña nueva.
2. **Ajustes → Kit de recuperación → Descargar kit.** Guárdalo **fuera del servidor**: un pendrive en un cajón con
   llave, un gestor de contraseñas o impreso. Sin el kit, si se pierde el servidor nadie puede abrir las copias.
   Si lo vas a guardar en un pendrive, puedes protegerlo con una contraseña (zip cifrado AES-256), pero si
   olvidas esa contraseña el kit no sirve.
3. **Avisos → Correo** (o Telegram): pon el correo al que deben llegar los avisos y pulsa "Probar".
4. **Ajustes → Copias e informes:** cuántas copias se guardan, límite de velocidad (para no saturar la red en
   horario de trabajo) e informe mensual por correo.

## 4. Añadir los equipos

**Lo más cómodo: Equipos → «Buscar equipos en la red»** (también sale en el inicio mientras no hay equipos):
1. Elige la red (el panel propone la del servidor) y pulsa Buscar: encuentra los equipos encendidos, dice qué sistema
   tienen (Windows, Linux, Mac) y cuáles ya tienen OCTOPUS.
2. Marca los que quieras, revisa su nombre y ponlos en grupos («Oficina», «Servidores»...).
3. Escribe usuario y contraseña de administrador **una vez por grupo** (se usan para instalar y no se guardan).
4. Se instala en todos a la vez y ves cómo va cada uno. Linux y Mac necesitan SSH; Windows, el «Servidor OpenSSH»
   activado (si no, el panel lo dice y queda el instalador de doble clic en la ficha del equipo).

También se puede añadir uno a uno:

**Equipos → Añadir equipo.**

- **Linux y Mac — "Desde aquí":** escribe la IP, un usuario administrador del equipo y su contraseña. Se pide
  confirmación y el servidor entra por SSH, instala el agente y deja su propia clave para no volver a necesitar
  la contraseña (que no se guarda). En los servidores se puede marcar "entrar solo con la clave del servidor",
  que desactiva el acceso SSH con contraseña. En el Mac tiene que estar activado *Ajustes → General → Compartir →
  Sesión remota*.
- **Windows (y también Linux/Mac si lo prefieres) — "Con un instalador":** se descarga un `.zip`; en el equipo se
  descomprime y se ejecuta: en Windows, clic derecho en `INSTALAR.bat` → "Ejecutar como administrador"; en Linux,
  `sudo bash instalar_linux.sh`; en Mac, clic derecho en `INSTALAR.command` → Abrir.
  **Borra después el zip:** lleva la clave de ese equipo.
- **Muchos equipos Linux a la vez:** rellena `ansible/equipos.ini` (copia `equipos.ini.ejemplo`) y ejecuta
  `sudo bash octopus.sh desplegar -k -K`.

Cada equipo hace una copia al día a las **20:00** (y cuando se pulsa "Hacer copia ahora"). En Mac, para que entren
Documentos, Escritorio y Descargas hay que dar "Acceso total al disco" a Python (lo explica el instalador).

### Copia completa del equipo (opcional)

En la ficha de cada equipo → Opciones → **Copia completa del equipo**. Si se activa, además de las carpetas
protegidas se copia **todo el disco** (programas, ajustes, todo, sin temporales ni papelera) una vez por semana.
Ocupa bastante más espacio en el servidor, por eso está desactivada por defecto: actívala solo en los equipos
que haría falta reconstruir enteros (servidores, el PC de contabilidad...). Se guardan las 2 últimas y una al mes
durante 3 meses.

- Para **recuperar archivos sueltos** de cualquier sitio del disco: Recuperar archivos → elige la copia marcada
  como *Completa*. Lo que no sea de las carpetas protegidas se deja siempre **al lado** (`.restaurado-fecha`),
  nunca encima de un archivo del sistema.
- Para **reconstruir un equipo entero**: instala de nuevo el sistema (Windows, Linux o macOS), instala el agente
  con el mismo nombre de equipo desde el panel y recupera de la última copia completa las carpetas que hagan
  falta (programas, configuración, datos). No es una imagen de disco que se "vuelca" de una vez: es una copia de
  todos los archivos.

## 5. Almacén externo (copia fuera del servidor)

Si se estropea el disco del servidor o hay un incendio, las copias que solo están en el servidor se pierden.
Con un almacén externo, cada noche se envía allí **todo**: la copia del propio servidor y las copias de todos los
equipos (solo lo nuevo, así que tras la primera vez tarda poco).

```bash
sudo bash octopus.sh ajustes
```

Se abre el archivo de ajustes. Rellena:

```
OFFSITE_RESTIC_REPOSITORY=sftp:copias@otro-servidor:/copias/octopus
OFFSITE_RESTIC_PASSWORD=<una contraseña larga, distinta de las demás>
```

Para S3 / Backblaze / Wasabi: `OFFSITE_RESTIC_REPOSITORY=s3:https://s3.eu-west-1.amazonaws.com/mi-bucket/octopus`
más `OFFSITE_AWS_ACCESS_KEY_ID=` y `OFFSITE_AWS_SECRET_ACCESS_KEY=`. Al guardar, OCTOPUS se reinicia; la primera
copia al externo se hace esa noche (o ya mismo con `sudo bash octopus.sh mantenimiento autocopia`).

La contraseña del almacén externo aparece en el kit de recuperación: **descarga el kit otra vez** después de
configurarlo. **Muy recomendado: bloqueo por tiempo (Object Lock).** Al crear el bucket en S3, Backblaze B2 o Wasabi, activa el
"bloqueo de objetos" con una retención por defecto (por ejemplo, modo *Governance* o *Compliance*, 30 días). Así,
aunque alguien robe las claves del almacén, no puede destruir las copias durante ese tiempo. OCTOPUS funciona con
él sin cambiar nada (probado con un almacén compatible S3: un "atacante" con las claves intentó borrarlo todo y
no pudo borrar ni un archivo).

Si alguien borra el almacén externo bloqueado, lo que deja son "marcas de borrado": en la web del proveedor
(*Mostrar versiones*) o con `aws s3api`, borra esas marcas y las copias vuelven a aparecer. Después ya se puede
recuperar con normalidad (`octopus.sh recuperar-servidor <almacén>` o `restic ... restore --no-lock`).

## 6. Qué hace OCTOPUS solo cada noche (03:30)

- Borra las copias antiguas según lo elegido en Ajustes.
- Comprueba que el almacén está sano (los domingos lee además una muestra de los datos).
- Hace una copia del propio servidor (y lo envía todo al almacén externo, si hay).
- Avisa si un equipo lleva demasiado sin copia (se puede cambiar por equipo en su ficha) o si el disco se llena.
- **Prueba de recuperación:** una vez por semana recupera de verdad unos archivos de la última copia de cada equipo
  y comprueba que salen bien. También se puede lanzar desde la ficha del equipo ("Probar recuperación").
- El día 1, el informe del mes anterior por correo (si está activado). También se puede ver e imprimir en
  **Ajustes → Copias e informes → Ver el informe**.

El resultado se ve en **Ajustes → Mantenimiento del servidor** y, si algo falla, en **Avisos** y por correo, siempre
con lo que hay que hacer. Cada noche también se comprueba si hay una **versión nueva** de OCTOPUS (se puede desactivar
con `OCTOPUS_COMPROBAR_ACTUALIZACIONES=no` en `octopus.sh ajustes`).

### Avisos que explican y se solucionan solos

Cada aviso tiene un **código** (por ejemplo `OCT-ALM-01`), dice **qué pasa**, **por qué importa** y los **pasos**
exactos para arreglarlo. Si se puede arreglar solo, tiene un botón **«Solucionar»**: volver a copiar un equipo,
repetir la prueba de recuperación, quitar el bloqueo del almacén tras un apagón, reparar el almacén, liberar
espacio, repetir la copia del servidor, hacer el mantenimiento ahora o renovar el certificado. El mismo código sale
en el correo/Telegram y en los **banderines** (los pasos de cada proceso), así el soporte sabe de qué se habla.

- **Ficha de cada equipo → Últimos pasos**: lo último que ha pasado con ese equipo, paso a paso.
- **Ajustes → Mantenimiento → Descargar diagnóstico**: un .zip para el soporte, sin contraseñas, claves ni nombres
  de archivos (los equipos salen como equipo-1, equipo-2...).
- **Ajustes → Avisos por correo**: se puede elegir quién recibe cada tipo de aviso (ataques, copias, servidor, informe).
- Los instaladores dejan también sus banderines: `C:\ProgramData\OCTOPUS\instalacion_*progreso.txt` en Windows,
  `/var/log/octopus/instalacion*_progreso.txt` en Linux y `~/Library/Logs/OCTOPUS/` en Mac.

## 7. Si atacan un equipo (ransomware)

Cada equipo tiene además un **archivo señuelo** oculto en sus carpetas protegidas (`.octopus_no_tocar.docx` o
`~octopus_no_tocar.docx` en Windows). Nadie lo usa: si cambia o desaparece, es casi seguro un ransomware y se actúa al
momento, sin esperar a que cifre más archivos. Se puede desactivar en Ajustes → Respuesta a ataques.

Si un equipo empieza a cifrar archivos en masa, OCTOPUS (si está activado en Ajustes → Respuesta a ataques):
lo **aísla de la red**, guarda una **copia forense** del estado del equipo, **restaura la última copia limpia** y
avisa. Las copias hechas durante el ataque se marcan como **Sospechosa** y al recuperar archivos se propone siempre
la última copia limpia. Todo se sigue en **Incidentes**; el equipo queda aislado hasta que alguien de seguridad lo
revise y pulse "Liberar equipo". También se puede declarar a mano: ficha del equipo → Opciones → Declarar incidencia.

## 8. Gestión diaria del servidor

```bash
sudo bash octopus.sh estado          # cómo está todo
sudo bash octopus.sh logs            # registro en directo
sudo bash octopus.sh kit             # kit de recuperación por pantalla
sudo bash octopus.sh mantenimiento   # el mantenimiento de la noche, ahora
sudo bash octopus.sh ajustes         # ajustes del servidor (almacén externo, avisos de disco...)
sudo bash octopus.sh actualizar      # instala la versión de esta carpeta (conserva datos y copias)
sudo bash octopus.sh volver          # vuelve a la versión anterior si la actualización da problemas
```

Para **actualizar**: copia la carpeta nueva de OCTOPUS al servidor y ejecuta `sudo bash instalar_servidor.sh`
(o `octopus.sh actualizar`). Los equipos se actualizan solos. **Si la versión nueva no arranca bien, el instalador
vuelve solo a la anterior** (y lo dice), así una actualización nunca deja las copias paradas.

Cortes de luz: si un equipo estaba apagado a la hora de su copia diaria, la hace sola en cuanto vuelve a encenderse;
si una copia se cortó a medias, el bloqueo que deja se quita solo. El informe mensual se reintenta cada noche
(hasta el día 7) si no se pudo enviar el día 1.

## 9. Si se pierde el servidor

Hace falta: **el kit de recuperación** y **el almacén** — o el disco del servidor antiguo (carpeta
`octopus-backups` del volumen `octopus_boveda`) o el almacén externo.

1. Prepara un servidor nuevo, **con la misma IP** que el antiguo si es posible (si no, los equipos no lo
   encontrarán hasta reinstalarles el agente), e instala OCTOPUS: `sudo bash instalar_servidor.sh`.
2. Recupera la configuración y las copias:
   - **Con el disco antiguo** (montado en el servidor nuevo, por ejemplo en `/mnt/viejo`):
     ```bash
     sudo bash octopus.sh recuperar-servidor /mnt/viejo/var/lib/docker/volumes/octopus_boveda/_data/octopus-backups
     ```
   - **Con el almacén externo:** antes, pon en `sudo bash octopus.sh ajustes` las claves de acceso del externo
     (`OFFSITE_AWS_...` si es S3) y después:
     ```bash
     sudo bash octopus.sh recuperar-servidor s3:https://s3.eu-west-1.amazonaws.com/mi-bucket/octopus
     ```
   Pide la clave: la **"Clave de las copias"** del kit (o la **"Clave del almacén externo"** si recuperas del
   externo). Lo que tuviera el servidor nuevo se guarda aparte en `/data/antes_de_recuperar_<fecha>`.
3. OCTOPUS se reinicia con la configuración antigua: entra con tu usuario y contraseña de siempre. Los equipos se
   vuelven a conectar solos en uno o dos minutos y sus copias siguen ahí.

Si se recupera desde el almacén externo, las copias de los equipos están en el externo: para restaurar archivos
mientras tanto se pueden sacar con restic desde cualquier equipo (`restic -r <almacén> snapshots`, con la clave
del kit), y el servidor nuevo empieza a guardar las copias nuevas en su propio disco.

**Sin el servidor y sin OCTOPUS** también se pueden recuperar archivos, desde cualquier ordenador con
[restic](https://restic.net) y la clave del kit:

```bash
restic -r <ruta-o-direccion-del-almacen> snapshots
restic -r <ruta-o-direccion-del-almacen> restore latest --host <equipo> --target <carpeta>
```

## 10. Seguridad, en resumen

- Las copias se cifran en el equipo antes de salir; el servidor guarda datos cifrados.
- El almacén funciona en modo **solo añadir**: un equipo comprometido no puede borrar sus copias.
- Cada equipo tiene su propia clave; quitar un equipo del panel la invalida.
- Panel: bloqueo de la cuenta tras 5 intentos fallidos, la sesión se cierra tras 30 minutos sin uso, registro
  de todo lo que se hace (Ajustes → Opciones avanzadas → Registro de actividad).
- El **registro de actividad va firmado**: cada línea se encadena con la anterior (SHA-256). Si alguien con acceso al
  servidor borra o cambia una línea, el panel lo avisa en Ajustes → Registro de actividad.
- Las contraseñas y tokens de correo/Telegram ya no se vuelven a enseñar en las páginas de ajustes.
- Pendiente para una próxima versión: doble autenticación (código de una app) al entrar en el panel.

## 11. Sugerencias y problemas (soporte)

Lo que se escribe en «Enviar sugerencia o problema» va al **buzón de OCTOPUS** (un servicio gratuito en Cloudflare que lo
reenvía al Telegram del soporte; ver `soporte/buzon/LEEME.md`). Una empresa que no quiera que salga nada puede poner
`SOPORTE_BUZON_URL=no`. Para comprobarlo: botón «Enviar una prueba al soporte» en esa misma página.

En el pie de cada página del panel hay **«Enviar sugerencia o problema»**. Lo que se escribe se guarda en el servidor y
se envía al soporte por los destinos que se configuren en `sudo bash octopus.sh ajustes`:

```
SOPORTE_CORREO=soporte@tudominio.com        # se envía con el correo de avisos configurado en el panel
SOPORTE_TELEGRAM_TOKEN=...                   # bot de Telegram del soporte
SOPORTE_TELEGRAM_CHAT=...                    # chat al que avisa
SOPORTE_GITHUB_REPO=usuario/repositorio      # solo las sugerencias (nunca problemas ni diagnósticos)
SOPORTE_GITHUB_TOKEN=...                     # se publican como incidencia pública
```

Si no hay ninguno configurado o no hay Internet, se queda guardado y se reintenta cada noche. El diagnóstico solo se
adjunta si el usuario marca la casilla. **No pongas estos valores en el código del repositorio** (es público): van en
el `.env` del servidor.
