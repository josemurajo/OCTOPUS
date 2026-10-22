# OCTOPUS Zero-Touch v2 - PENDIENTES

Lista de cosas por hacer. `[ ]` = pendiente, `[x]` = hecho.
Actualizado: 22/10/2026 (versión 3.0.0 lista para firmar)

## ✅ PARA SALIR A PRODUCCIÓN (22/10/2026) — el programa está listo; solo faltan cosas tuyas

Lo tuyo, en orden. Todo es gratis.

1. ✅ Correo de OCTOPUS puesto (octopuszerotouch@gmail.com) en `DATOS_DEL_AUTOR.txt` (22/10).
2. ⚪ Token de Telegram: **José decide seguir con el actual** (22/10), aunque se vio en el chat. Riesgo asumido:
   quien lo tenga podría mandar mensajes con el bot. Se cambia cuando quieras (@BotFather → `/revoke`).
3. 🔴 **Haz pública la imagen** (1 min): abre https://github.com/users/josemurajo/packages/container/octopus/settings,
   baja hasta el final, pulsa *Change visibility* → **Public**, escribe `octopus` y confirma.
4. 🔴 **Firma la versión 3.0.0** cuando te avise (1 min): doble clic en `FIRMAR_VERSION.bat`, frase de paso, y pegas
   en el chat lo que te copia. Ver [PUBLICAR_VERSION.md](PUBLICAR_VERSION.md).
5. 🟠 **Descripción y temas del repositorio** (1 min): rueda ⚙ junto a «About» en GitHub.
6. 🟠 **Antes de vender o anunciarlo**:
   - que un asesor revise `legal/` (privacidad y licencia);
   - comprobar que la marca «OCTOPUS» está libre en la OEPM (https://www.oepm.es, consulta gratis).
7. 🟢 **Cuando puedas**: la prueba en tu PC **sin dejar rastro**, con el Espacio aislado de Windows (tu Windows es Pro).
   Doble clic en `PROBAR_OCTOPUS.wsb`; se prueba solo en 10 minutos. Ver `herramientas/sandbox/LEEME.md`.
   (No hay Mac: el Mac se prueba solo en GitHub en cada cambio.)

**Prueba grande en las máquinas virtuales** (cuando José esté en su PC y avise): todo, incluido lo nuevo.
- El modo casa y el modo discreto (jugar mientras copia).
- Los destinos de copia.
- El servidor en cada sistema operativo: Linux en Docker, Windows nativo, Mac y NAS.
- Las nuevas formas de uso: casa y empresa con máquina aparte.
- Para las pruebas en el PC de José: el Espacio aislado de Windows (`PROBAR_OCTOPUS.wsb`), sin dejar rastro.

**Qué viene «en pruebas»** (está hecho, pero viene apagado hasta probarlo en algo real; se puede encender en Ajustes
→ Funciones, modo experto):

| Función | Para quitarle el «en pruebas» necesito |
|---|---|
| Copias de máquinas virtuales | un Hyper-V o un Proxmox de verdad (Proxmox es gratis) |
| Copia de Microsoft 365 / Google | una cuenta gratis del Microsoft 365 Developer Program y una cuenta de Google |
| Active Directory/LDAP, OIDC, RADIUS | el servidor de usuarios de una empresa de verdad (o uno de prueba) |
| USB de rescate, imagen de disco, arranque por red, despliegue | un PC físico viejo |

Lo demás (copias de equipos y de bases de datos, avisos, recuperación, doble autenticación, multiempresa, paquetes
para NAS…) viene listo y probado.

**Para después** (no impide salir): imagen ISO todo en uno, VMware ESXi, llaves de acceso (passkeys), caja fuerte de
claves y optimización con medidas reales (8.8).

---

## 1. Doble autenticación (2FA) en el panel  — HECHO (14/10)

- [x] Código de 6 cifras de Google/Microsoft Authenticator al entrar (TOTP estándar, comprobado con los valores
      oficiales de la norma). Obligatoria para administradores por defecto (Ajustes → Funciones: administradores,
      todos u opcional). Activación con código QR y **guía paso a paso para cualquiera** (`/ayuda/doble-autenticacion`,
      también desde la pantalla del código, se puede imprimir).
- [x] 10 códigos de emergencia de un solo uso, «recordar este navegador 30 días», un código no vale dos veces,
      5 códigos mal = cuenta bloqueada un rato.
- [x] Kit, cambiar contraseña y quitar la 2FA de otro usuario piden el código siempre.
- [x] Móvil perdido: otro administrador la quita (con su propio código); si eres el único, `octopus.sh quitar-2fa
      <usuario>` en la consola del servidor **con el código de recuperación que va solo en el kit** (avisa a todos los
      administradores y cierra sesiones). Secreto cifrado; códigos de emergencia solo como huella.
- [x] Probado: 35/35 en local y en la batería del laboratorio (111/0, 14/10 00:46).

### (lo que se pedía, para referencia)

Motivo: quien entre en el panel con la contraseña puede descargar el kit de recuperación, y con el kit
puede leer todas las copias de seguridad. Una contraseña sola no basta.
No se hace hasta que José lo diga (al revisar el panel cada dos por tres sería molesta).

- [ ] **2FA obligatoria al entrar** en el panel, con una app de autenticación (Google Authenticator,
      Microsoft Authenticator, Authy...): código de 6 dígitos que cambia cada 30 segundos (estándar TOTP).
- [ ] **Primer acceso**: después de cambiar la contraseña de un solo uso, obligar a activar la 2FA
      (mostrar el código QR para escanearlo con la app y pedir un código para comprobar que funciona).
      No se puede usar el panel hasta que esté activada.
- [ ] **Cambiar la contraseña** pide también el código de la app, además de la contraseña actual.
- [ ] **Descargar el kit de recuperación** pide también el código de la app.
- [ ] Códigos de emergencia de un solo uso (por si se pierde el móvil), que se enseñan una sola vez al activar la 2FA.
- [ ] Forma de recuperar el acceso si se pierde el móvil y los códigos (desde la consola del servidor, por ejemplo
      `octopus.sh`, con acceso físico o SSH al servidor).
- [ ] "¿Olvidaste tu contraseña?" (enlace por correo): al crear la contraseña nueva, pedir también el código
      de la app. Si no, quien entre en el correo del admin se salta la 2FA.
- [ ] Añadir las pruebas de la 2FA a `maquinas/scripts/pruebas_cerebro.sh`.

## 2. Monitorización de equipos — HECHO (14/10)

- [x] Apartado **«Monitorizacion»** en la barra: lista de equipos con lo principal en directo y «Instalar en un equipo».
- [x] Pantalla de cada equipo: procesador (total y por núcleo, carga, GHz), memoria y swap, disco (lectura/escritura y
      espacio), red (bajada/subida por tarjeta), temperaturas y ventiladores, batería (carga, salud, ciclos, tiempo),
      **lo que más gasta** (procesos), **salud de los discos** (vida restante, horas, temperatura, sectores dañados,
      datos escritos), inventario (fabricante, modelo, serie, BIOS, gráfica, sistema), actualizaciones pendientes,
      antivirus, servicios parados, reinicio pendiente, e **historial** de 1 h, 24 h, 7 y 30 días.
- [x] Clara y sin saltos: solo cambian números y barras en su sitio con transiciones suaves (**0 saltos medidos**
      con Chrome en 30 s de actualizaciones), lista de procesos suavizada para que no baile, se para si la pestaña no
      se ve. Datos cada 3 s mientras alguien mira y cada minuto si no; se activa en 1-2 s.
- [x] Tarjeta «Monitorizacion» en la ficha de cada equipo (activar / ver en directo / quitar).
- [x] Avisos con código y qué hacer (OCT-MON-01..09): disco fallando o muy gastado, disco casi lleno, calor mantenido,
      batería gastada, memoria/procesador al límite 30 min, sin datos, antivirus apagado. Van por correo/Telegram como
      los demás.
- [x] Sin instalar nada: lo hace el agente (Python puro). En Linux se instala smartmontools para la salud de discos.
- [x] Probado: 19/19 en local con un agente de verdad; el recolector en Linux, Windows Server 2025 y Mac (M1) reales de
      GitHub. Aviso legal en pantalla: si es el equipo de un trabajador, hay que informarle.
- [ ] Temperaturas en Windows: muchos PC no las dan sin un programa del fabricante (se muestra «no la da a conocer»).
      En Mac, macOS no las deja leer sin herramientas extra.

### (lo que se pedía, para referencia)

Idea: poder ver el estado de un equipo desde el panel, pero solo en los equipos donde se active.
Si no se instala, ese equipo no se monitoriza.

- [ ] **Nuevo apartado en la barra de arriba que se llame exactamente "Monitorizacion"** (junto a Inicio, Equipos, Recuperar archivos...).
- [ ] Desde ese apartado, opción **"Instalar en un equipo"**: elegir el equipo y activarle la monitorización.
- [ ] En ese apartado, lista de los equipos monitorizados; **al pinchar en uno se abre su monitorización**.
- [ ] **En la ficha de cada equipo**, en el hueco libre a la derecha de "Datos del equipo", una tarjeta/pestaña
      **"Monitorizacion"** para acceder a ese PC. Si el equipo no la tiene, botón "Activar monitorizacion".
- [ ] Que sea opcional y se pueda quitar: nada se monitoriza si no se activa en ese equipo.
- [ ] Por decidir: qué se muestra y si se puede acceder al equipo a distancia desde ahí. Lo que se suele esperar
      (herramientas tipo RMM): avisos cuando la CPU, la memoria o el disco pasan de un límite, si el equipo está
      encendido, estado de servicios, inventario (hardware, programas, versión del sistema), antivirus y actualizaciones.

## 0. Lo que necesito de ti para terminar y probar (TODO GRATIS, nada de pago)
- **Microsoft 365 de prueba**: una cuenta gratuita del «Microsoft 365 Developer Program» (tenant de pruebas con
  25 licencias, gratis y renovable). Hace falta para probar de verdad la copia de 365. Yo la dejo montada con una
  simulación; la prueba real la haremos con esa cuenta.
- **Google de prueba**: una cuenta normal de Google (gratis) para probar la copia de Gmail/Drive.
- **Un hipervisor de verdad** cuando puedas (Hyper-V en un Windows, o Proxmox/KVM): para quitarle el «en pruebas» a
  las copias de máquinas virtuales. Proxmox se instala gratis.
- **Un PC físico** (aunque sea viejo) para probar el USB de rescate y la imagen de disco.
- Nada de esto cuesta dinero. Cuando tengas cada cosa, me avisas y hacemos la prueba real.

- 🔴 **José, 1 minuto (gratis), cuando termine la primera publicación de la imagen**: GitHub → tu perfil →
  *Packages* → **octopus** → *Package settings* → *Change visibility* → **Public**. Sin esto, los NAS no pueden
  descargar la imagen. (Lo verás en la pestaña Actions: «Imagen del servidor»).

### Ya hecho (no hay que rehacerlo)
- ✅ **Paquetes fáciles de instalar** (20/10): NAS Synology/QNAP, Portainer, CasaOS, TrueNAS SCALE (pegar
  `install/nas/docker-compose.yml`), plantilla de **Unraid**, y **Proxmox** en un solo comando (crea el LXC y lo
  deja funcionando). Guía `INSTALAR_EN_NAS.md`. La imagen se publica sola en GitHub (gratis) cuando pasan las
  pruebas. La primera contraseña sale en el Registro del contenedor y se borra al cambiarla. Probado: paquete NAS
  con la imagen real en GitHub (`tests/ci/prueba_nas.sh`) y Proxmox simulado (`tests/ci/prueba_proxmox.sh`).
  Arreglado de paso: en una instalación nueva con doble autenticación obligatoria, el primer acceso se quedaba
  dando vueltas entre «cambia la contraseña» y «activa el móvil». Pendiente: imagen ISO «todo en uno» (necesita
  probar arrancando un PC o una VM real).
- ✅ Copias de **máquinas virtuales** (Hyper-V, KVM/libvirt, Proxmox), completas y en caliente.
- ✅ Copias de **bases de datos** (SQL Server, MySQL/MariaDB, PostgreSQL): volcado consciente, recuperar como base
  nueva y descargar. (Las VM vienen «en pruebas» hasta probarlas en un hipervisor real; las bases de datos ya
  vienen disponibles: se prueban con los motores de verdad en GitHub).
- ✅ Copia de la **nube (Microsoft 365 y Google)**: correo (.eml) y archivos (OneDrive/Drive) al almacén del
  servidor, incremental, con asistente paso a paso en Ajustes → Copia de la nube, credenciales cifradas, recuperación.
  Motor probado de punta a punta con API simulada (`tests/ci/prueba_nube.py`). Viene «en pruebas»: la prueba real
  necesita tu Microsoft 365 Developer (gratis) y una cuenta de Google (ver punto 0).

## 2b. Prueba de seguridad (14/10) — HECHA, en el servidor de pruebas
1. **Como atacante, desde fuera:** ninguna de las 85 páginas responde sin entrar. Formularios sin token, claves de
   equipo falsas, leer archivos del sistema por la dirección, HTTP sin cifrar y almacén sin contraseña: todo
   rechazado. Probar contraseñas bloquea la cuenta. Cabeceras y cookie seguras. **17/17.**
2. **Seguridad encendida (como un usuario):** bloqueo de atacantes, solo redes de la oficina, doble aprobación,
   aviso de acceso nuevo, 2FA y papeles de usuario. **26 + 35 + 29, sin fallos.**
3. **Seguridad apagada:** Funciones, monitorización (19/19 + 350 lecturas seguidas del directo sin cortes) y la
   parte del servidor de la batería del laboratorio. La 2FA apagada deja de ser obligatoria, pero quien ya la tenía
   activada la sigue usando, a propósito (ahora lo dice en Funciones).
- **Fallo encontrado y arreglado:** el límite de peticiones (que el laboratorio no tenía instalado) habría cortado
  la monitorización en directo a la hora (más de 300 peticiones) y también al recargar el login 5 veces. Ahora solo
  cuentan los envíos del login (10 por minuto) y las visitas sin sesión. No se aplica al propio servidor ni a las
  direcciones de confianza, y el mensaje sale en castellano. Hay prueba nueva en GitHub (`prueba_limite.py`).

## 2c. Código abierto, legal y privacidad (14/10) — HECHO en el programa
OCTOPUS pasa a **software libre y gratuito, licencia AGPL-3.0**:
- `LICENSE` (AGPL-3.0), `NOTICE` y `AUTHORS` con tu nombre (**José Murillo Rajo**); cada archivo de código lleva su
  cabecera de autoría, y el agente la lleva también en base64 (se lee con `base64 -d` o pidiéndoselo a una IA).
- `SECURITY.md` (cómo avisar de un fallo), `CONTRIBUTING.md` (con DCO), `MARCA.md` (el nombre no es libre).
- `TERCEROS.md` con todas las licencias, **generado solo** (`herramientas/terceros.py`); GitHub comprueba en cada
  cambio que todas son compatibles con la AGPL.
- Página **«Legal y privacidad»** en el panel (se ve también sin entrar, desde el pie): licencia, autoría, privacidad,
  seguridad, marca y las plantillas para la empresa (nota para los trabajadores, registro de tratamientos, evaluación
  de impacto), con descargar e imprimir. Enlace al código fuente.
- La monitorización pide **confirmar que se ha informado al trabajador** antes de activarla, y deja elegir qué se
  recoge (los programas abiertos y el usuario con sesión se pueden apagar; vienen apagados los segundos).
- `MAPA_DEL_CODIGO.md`: guía para saber qué tocar para cambiar cada cosa; cabeceras explicativas en el código.
- 🔴 **Queda para ti/un abogado:** revisar los textos de `legal/` y rellenar los [corchetes]; buscar la marca
  «OCTOPUS» en la OEPM/EUIPO (hay un programa que ya se llama Octopus Deploy); valorar un seguro al salir a producción.

## 2d. Monitorización con activar/desactivar/desinstalar (14/10) — HECHO
- **Viene apagada** (desinstalada). En cada equipo: **Activar** (instala), luego **Desactivar** (pausa, guarda el
  historial) y, en pausa, **Activar** o **Desinstalar** (borra el historial; pide escribir el nombre del equipo = seguro).
- Se maneja desde el panel y **desde la consola del servidor**: `octopus.sh monitorizacion estado|activar|pausar|desinstalar <equipo|todos>`.

## 2e. Funciones que pasaron sus pruebas (14/10) — ya vienen disponibles
Dejan de estar «En pruebas»: bloquear atacantes (encendida de serie), panel solo desde la red de la oficina, doble
aprobación, LDAP/Active Directory, OIDC y RADIUS. **Siguen en pruebas** (necesitan equipos físicos): USB de rescate,
imagen de disco, arranque por red (PXE) y despliegue en masa; cada una con su botón de activar/desactivar.

## 2h. Copias de bases de datos (20/10) — HECHO
- `agentes/octopus_bd.py`: **SQL Server** (BACKUP … COPY_ONLY con PowerShell/.NET, sin instalar nada; no interfiere
  con las copias que ya haga la empresa), **MySQL/MariaDB** (mysqldump sin bloquear) y **PostgreSQL** (pg_dump),
  directo al almacén. Entra solo si puede (socket de root, debian.cnf, usuario postgres, cuenta del sistema) y si no,
  el panel explica cómo dar permiso (orden para copiar) o deja escribir usuario y contraseña (se guardan cifrados).
- Cada día, cada 4 horas o cada hora (el agente lo vigila con su propio hilo y candado). **Volver a una hora
  concreta**: se recupera como base NUEVA `<nombre>_recuperada_<fecha>`, la original no se toca; o **descargar** el
  volcado/.bak desde el almacén del servidor (aunque el equipo esté apagado).
- Retención: todas las del último día, 14 diarias, 8 semanales, 12 mensuales (por base de datos).
- Pruebas: `tests/ci/prueba_bd.py` (22, MySQL 8 y PostgreSQL 16 reales; en GitHub en Linux),
  `tests/ci/prueba_bd_sqlserver.py` (SQL Server LocalDB en el Windows de GitHub) y de punta a punta por el panel con un
  agente con MySQL y PostgreSQL de verdad (21, incluida la copia automática sin pulsar nada).

## 2f. Copias de máquinas virtuales (20/10) — HECHO, «en pruebas» hasta probarlo en un hipervisor real
- Nuevo `agentes/octopus_vms.py`: detecta las máquinas virtuales del equipo y copia **cada una entera** (discos +
  configuración), aunque esté encendida: **Hyper-V** (instantánea VSS, con toda la cadena de discos), **KVM/libvirt**
  (instantánea externa temporal + blockcommit; congela el sistema de archivos si tiene qemu-guest-agent) y
  **Proxmox** (vzdump directo al almacén). Cada copia es completa; solo ocupa lo que cambia.
- **Recuperar aparte**: nunca toca la original; comprueba que hay sitio; en libvirt deja un XML listo con otro nombre
  y otra MAC (`virsh define`), en Hyper-V explica la importación, en Proxmox `qmrestore`.
- Panel: ficha del equipo → **Máquinas virtuales**: activar, cada día o cada semana, elegir cuáles, «Copiar ahora»,
  copias hechas y «Recuperar aparte». Función «Copias de máquinas virtuales» en Ajustes → Funciones (en pruebas).
- Retención propia (ocupan mucho): por máquina, 3 últimas + 4 semanales + 3 mensuales. La copia completa del disco ya
  no duplica los discos de las máquinas virtuales.
- Pruebas: `tests/ci/prueba_vms.py` (24, hipervisores simulados, copias y recuperación reales; en GitHub en Linux y
  Mac) y de punta a punta por el panel con el agente del laboratorio (18).
- 🔴 **Para quitarle «en pruebas»**: probarlo en un Hyper-V, un KVM y un Proxmox de verdad.

## 2g. Imagen del servidor más ligera (20/10) — HECHO
- `ansible-core` (~100 MB) ya no va en la imagen: `octopus.sh desplegar` lo instala solo la primera vez que se usa
  (en /data/ansible/venv, se conserva al actualizar).
- 🔴 **José, 1 minuto**: en la página del repositorio en GitHub, rueda dentada ⚙ junto a «About» → pega la
  descripción y los temas (yo no puedo cambiar los ajustes del repo desde aquí).

## 3. Pruebas en Mac, Windows y Linux con GitHub (gratis)  — HECHO

- [x] Repositorio público **josemurajo/OCTOPUS** con las pruebas automáticas (se lanzan solas en cada cambio).
- [x] **Agente en Linux, Windows y Mac: funciona** en máquinas reales de GitHub (copia, comprobación en el almacén,
      recuperar un archivo y una carpeta).
- [x] **Instalador del servidor en Mac: funciona** en un Mac real de GitHub (Colima + Docker + OCTOPUS, panel sano).
- [x] Revisión automática de la sintaxis de todos los scripts de Windows y de bash.
- [x] Fallos encontrados gracias a GitHub y arreglados: el instalador del agente de Windows fallaba si el equipo ya
      tenía otro Python (error 1603 del instalador de Python): ahora usa el Python del sistema si hay, e instala sin
      "lanzador"; una línea del instalador del servidor de Windows que PowerShell no aceptaba.

## 4. Laboratorio  — HECHO

- [x] **Linux (cliente1 Ubuntu + cliente2 Rocky): 96 correctas, 0 fallos** (12/10 18:53).
- [x] **Windows Server 2022: 46 correctas, 0 fallos** (12/10 20:08), con el instalador del agente nuevo.
- [x] **Debian 12 + Rocky Linux 9: 93 correctas, 0 fallos** (12/10 20:19), incluida la copia completa de todo el disco.
      (La prueba `-Todo` necesita ~12 GB de RAM libres: se hace por partes. Para Debian/Rocky: PROBAR_DEBIAN_ROCKY.bat)
- [x] Si cerebro se queda colgado, las pruebas lo apagan a la fuerza y lo arrancan otra vez solas.
- [x] El panel ya no se reenvía al puerto 8080 del PC: siempre https://192.168.10.10:8080.
- [x] RECARGAR_PANEL.bat para ver cambios del panel sin pasar todas las pruebas.

## 5. Instaladores del servidor

- [x] Las versiones con WSL2 + Rancher (Windows) y Colima (Mac) se **quitaron** el 13/10: ya no hacen falta (servidor
      nativo, abajo) y la aplicación aún no ha salido al mercado. Apartadas en `obsoletos\limpieza_20261013`.
- [x] **Servidor nativo de Windows probado en una VM de verdad (win11srv, 13/10 23:37): todo correcto**: instalar en
      46 s, panel y almacén accesibles desde otro equipo, **reinicio real sin que nadie inicie sesión → vuelve solo**,
      matarlo de golpe → vuelve solo en 10 s, y un agente haciendo copia y restauración contra él.
      Fallo encontrado y arreglado: Windows marca muchas redes de oficina como «públicas» (y al reiniciar volvía a
      hacerlo) y el firewall solo estaba abierto en redes privadas/dominio → **los equipos dejaban de llegar sin que
      nadie tocara nada**. Ahora se abre en cualquier tipo de red (el panel y el almacén ya se protegen solos).

- [x] **Servidor en Windows y Mac 0 touch, SIN WSL2, Docker, Colima ni Homebrew** (13/10, pedido por José: «el usuario
      tiene que hacer 0 touch al instalar, con Mac lo mismo»). Doble clic en `INSTALAR_SERVIDOR_WINDOWS.bat` /
      `INSTALAR_SERVIDOR_MAC.command`, el sistema pide la contraseña de administrador una vez y ya está:
      - Descarga Python portátil, restic y rest-server con versión fija y **huella SHA-256 comprobada** (si no coincide,
        no instala nada). Todo dentro de `C:\ProgramData\OCTOPUS-Servidor` o `/usr/local/octopus-servidor`.
      - **Servicio del sistema**: arranca solo al encender el equipo **sin iniciar sesión** (tarea SYSTEM en Windows,
        LaunchDaemon en Mac) y si se para se vuelve a levantar solo. Firewall abierto y sin reposo enchufado.
      - Panel en Windows con cheroot (HTTPS, de producción; gunicorn no existe en Windows); en Mac, gunicorn.
      - `octopus.ps1` / `octopus.sh` con modo nativo (estado, logs, parar, arrancar, mantenimiento, ajustes, volver,
        desinstalar sin perder las copias). Reinstalar = actualizar sin perder nada, y si no arranca vuelve sola.
      - **Actualización a distancia firmada también en Windows** (`actualizador.ps1` + `lib/firma.py`, que comprueba la
        firma con el Python ya instalado, sin depender de ssh-keygen) y en Mac nativo.
      - Por el camino: certificados con `cryptography` (ya no hace falta openssl), instalación remota por SSH con
        paramiko (ya no hace falta sshpass/ssh; probada contra un OpenSSH real) y arreglado un fallo que impedía arrancar
        el servidor si el archivo de usuario del almacén estaba en formato antiguo.
      - Pruebas de GitHub nuevas en un Windows y un Mac reales: instalar como un usuario, caída y vuelta sola,
        gestión, copia y restauración de un agente, reinstalar sin perder nada, actualización firmada y manipulada.
- [ ] Probarlo también en un Windows y un Mac físicos de la oficina (en GitHub son máquinas reales pero de pruebas).
- [x] ~~Migrar sola una instalación antigua con Docker a la nativa~~: no hace falta, no hay instalaciones en el mercado.

## 6. Hecho en la versión 2.1 (12/10/2026)

Kit de recuperación
- [x] Opción "Proteger el kit con contraseña": se descarga como zip cifrado AES-256 (avisa de que si se olvida
      esa contraseña el kit no sirve). Sin contraseña se sigue descargando como texto.
- [x] Aviso en el panel mientras no se haya descargado nunca el kit.
- [x] Quitado del kit el "token común de los agentes" (solo sirve para equipos antiguos y no hace falta para recuperar).

Ideas que pide la gente (buscado en internet)
- [x] **Prueba de recuperación automática** cada semana: recupera de verdad unos archivos de la última copia de
      cada equipo y comprueba que salen bien. Botón "Probar recuperación" en la ficha del equipo; resultado en
      la ficha, en Avisos y en el informe.
- [x] **Avisos con "qué hacer"** (también los del mantenimiento nocturno, por correo/Telegram).
- [x] **Aviso sin copia configurable por equipo** (1 día, 2, 3 o una semana para portátiles).
- [x] **Aviso al terminar una recuperación** (correo/Telegram), también si falla.
- [x] **Informe mensual**: página para imprimir/guardar en PDF (Ajustes) y por correo el día 1 (activable).
- [x] **Copias sospechosas**: las hechas durante un ataque se marcan y al recuperar se propone la última limpia.
- [x] **Límite de velocidad** de las copias, con opción de aplicarlo solo en horario de trabajo.
- [x] **Almacén externo completo**: ahora se envían allí también las copias de los equipos (antes solo la
      configuración del servidor). Probado: si se pierde el servidor, el historial sigue en el externo.
- [x] **Recuperar el servidor en una máquina nueva** con una orden: `sudo bash octopus.sh recuperar-servidor <almacén>`.
      Probado de principio a fin: el equipo de prueba se reconecta solo y sus copias siguen ahí.
- [x] `sudo bash octopus.sh ajustes` para cambiar los ajustes del servidor sin tocar Docker.

Fallos arreglados
- [x] **Los ajustes de texto se guardaban con comillas de más** (p. ej. `"tu@correo.com"`): el correo de los
      avisos no habría llegado nunca. Arreglado al leerlos.
- [x] La sesión del panel ya se cerraba tras 30 minutos sin uso (las 8 horas eran el máximo absoluto). Además,
      ahora las recargas automáticas de las pantallas no cuentan como actividad.
- [x] Ficha del equipo: las opciones van abajo en lista ("Probar recuperación", "Aviso si se queda sin copia",
      "Declarar incidencia", "Quitar este equipo"). Ajustes: "Opciones avanzadas" también en lista.

Limpieza
- [x] Pantallas de la v1 que guardaban ajustes que nadie usaba retiradas (Perfiles rápidos, Programación de copias,
      Carpetas protegidas, Respuesta ante ataques repetida, Detección, Aprobaciones, Resumen técnico). Lo único
      útil ("cuántas copias se guardan") está ahora en Ajustes → Copias e informes. Se quedan: Wazuh, Red y puertos
      y Registro de actividad.
- [x] Unos 55 archivos y carpetas antiguos apartados a la carpeta `obsoletos` (no se ha borrado nada).
- [x] Un único `README.md` y un único `PRODUCCION.md` (instalación, almacén externo, qué hacer si se pierde el servidor).

## 7. Más ideas para después

- [x] **Bloqueo por tiempo en el almacén externo** (Object Lock): probado en GitHub con un almacén compatible S3
      (MinIO). OCTOPUS envía sus copias, un "atacante" con las claves intenta borrarlo todo y no puede borrar nada,
      y las copias se recuperan. Explicado en PRODUCCION.md cómo activarlo en S3 / Backblaze / Wasabi.
- [x] El kit cifrado (7-Zip) comprobado en el laboratorio: solo se abre con su contraseña.
- [x] **Copia completa del equipo, opcional por equipo** (ficha del equipo → Opciones). Desactivada por defecto
      para no ocupar espacio. Copia todo el disco una vez por semana (sin temporales ni papelera); se guardan las 2
      últimas y una al mes durante 3 meses. Se pueden recuperar archivos de cualquier sitio del disco (lo del sistema
      se deja siempre al lado, nunca encima). Probado en Linux local y en Debian 12 del laboratorio.
- [x] **Copia completa en Windows Server 2022: 49 correctas, 0 fallos** (12/10 21:50). Todo C:\ en 18 min con
      instantánea VSS; `hosts` del sistema recuperado al lado (`hosts.restaurado-...`) sin tocar el original.
- [x] **Copia completa en un Mac real** (13/10, Mac de GitHub): copia completa y recuperar un archivo desde ella, en verde.

## 8. Ideas nuevas (13/10/2026) — en marcha: versión 2.2 hecha el 13/10 (1 a 10 de la lista)

### 8.1 Avisos que expliquen y solucionen — HECHO en v2.2 (probado en local y en el laboratorio)
- [x] **Catálogo único de avisos** (`lib/avisos.py`): cada aviso tiene código (OCT-EQ-01, OCT-ALM-01...), qué pasa,
      por qué importa y pasos exactos. El mismo texto va al panel, al correo/Telegram y a los banderines.
- [x] Avisos nuevos que antes no existían: mantenimiento que no se hace (36 h), certificado a punto de caducar
      (30 días), almacén bloqueado tras un apagón, disco casi lleno con su propio código, versión nueva.
- [x] **Botón «Solucionar»** que lo hace solo: repetir la copia, copiar y repetir la prueba de recuperación, quitar
      el bloqueo del almacén, reparar el almacén (`restic repair index` + comprobación), liberar espacio, repetir
      la copia del servidor, mantenimiento ahora, renovar el certificado (y reiniciar el panel solo), volver a
      comprobar la versión, reenviar sugerencias. Debajo del aviso se ve el último intento y si funcionó.
- [x] Lo que no se puede arreglar solo (equipo apagado, robado...) explica paso a paso qué hacer, incluido cómo
      reiniciar el agente en Windows, Linux y Mac.
- [ ] «Agente que no responde → pedirle que se reinicie»: no se puede, porque si no responde tampoco recibe
      órdenes; el aviso explica cómo reiniciarlo a mano.
- [x] **Fallo silencioso grave encontrado y arreglado**: en Ajustes → Avisos por correo y en Telegram, la casilla
      «Habilitar» nunca se guardaba (el navegador manda «on» y el panel esperaba «true») y guardar un formulario
      borraba el otro: **los avisos por correo y Telegram no se podían activar desde el panel**. Además, los
      ajustes nuevos que no estaban en la lista se ignoraban sin decir nada (ahora se avisa en el registro).
- [x] Las contraseñas SMTP y el token de Telegram ya no se enseñan en la página.
- [x] Laboratorio (13/10 07:15): **107 correctas, 0 fallos** con cliente1 (Ubuntu) y cliente2 (Rocky), incluidas las
      pruebas nuevas: avisos con código, botón Solucionar, últimos pasos, buscador, diagnóstico sin nombres,
      registro firmado, semáforo 3-2-1 y señuelo → incidente.
- [x] **Se arregla solo lo que no tiene riesgo** (13/10, idea de José): cada 10 minutos OCTOPUS mira los avisos y
      arregla por su cuenta repetir una copia que falló o es antigua (si el equipo está conectado), repetir la prueba
      de recuperación, quitar un bloqueo antiguo del almacén, repetir la copia del servidor, hacer el mantenimiento
      que no se hizo, reenviar sugerencias y renovar el certificado (este solo de madrugada, porque el panel se
      reinicia). En el aviso pone «🔧 Se arregla solo».
- [x] **Lo gordo o lo que puede borrar datos pide permiso con el botón**: borrar copias antiguas (liberar espacio)
      y reparar el almacén. En el aviso pone «✋ Necesita tu permiso» con el riesgo explicado, y hay que marcar
      «Entiendo lo que se va a hacer» y confirmar. Queda en el registro quién dio permiso.
- [x] Frenos: con un incidente abierto (posible ataque) no se arregla nada solo; tras un fallo espera (2 h para
      copias) antes de reintentar; si falla 3 veces seguidas, o se arregla y vuelve a pasar 6 veces en un día, deja
      de intentarlo y el aviso dice «OCTOPUS no ha podido arreglarlo solo». Se puede apagar en Ajustes → Respuesta a ataques
      («Arreglar solo lo que no tiene riesgo»). Correo y Telegram dicen si se está arreglando solo o necesita permiso.
- [x] Probado en el servidor de pruebas provocando los fallos: almacén bloqueado, copia del servidor fallida y
      copia de un equipo fallida se arreglan solos en ~1 min; la limpieza NO se hace sola y con permiso sí; con un
      incidente abierto no se toca nada (14/14). Arreglado por el camino: quitar el bloqueo daba por hecha también
      una limpieza que había fallado por otra cosa (el aviso desaparecía sin limpiar).
- [x] **Aviso al momento, con la solución** (13/10, idea de José): además de mirar cada 10 minutos, en cuanto falla
      una copia, una prueba de recuperación o el mantenimiento, el vigilante lo mira ya (en unos 5-10 segundos) y
      manda **un mensaje por correo y Telegram** con qué ha pasado, por qué importa y cómo se arregla:
      «🔧 Se arregla solo: lo está arreglando ahora (cómo)», «✋ Necesita tu permiso» (con el riesgo, el enlace al
      panel y el botón) o los pasos a mano. Cuando termina un arreglo solo, **segundo mensaje**: «✅ Arreglado solo:
      qué ha hecho y el resultado» o «❌ No se ha podido: qué ha intentado, qué ha pasado y cuándo reintenta».
- [x] Sin mensajes repetidos: uno por problema hasta que se arregla (y como mucho 4 al día aunque vaya y venga);
      «sin conexión» solo si dura más de 24 h (un portátil apagado por la noche no es un problema); si hay más
      de 3 a la vez, van juntos en un solo mensaje; al instalar o actualizar no se reenvía lo que ya había. Copia
      de todo lo enviado en `data/logs/avisos_enviados.log`. Probado: 9/9 (mensaje a los 4-9 s del fallo).
- [x] **Probado en el laboratorio** (13/10): batería completa **111 correctas, 0 fallos**, incluida la copia del servidor
      que se arregla sola y la limpieza que espera permiso.
- [x] **Certificado caducando de madrugada** (13/10): provocado con la hora a las 03:47 → se renovó solo (válido 824
      días), reinició el panel y el almacén, y llegó el mensaje «✅ Arreglado solo».

### 8.2 Ideas sacadas de otros programas (UrBackup, BackupAssist, Veeam, Kopia...)
- [x] **Archivos señuelo** (v2.2): un archivo trampa oculto en cada carpeta protegida (`.octopus_no_tocar.docx`,
      `~octopus_no_tocar.docx` en Windows). Si cambia o desaparece → incidente al momento (probado en local:
      aisló el equipo y restauró la copia limpia). Se acepta solo tras una recuperación legítima. No sale en el
      explorador ni en el buscador del panel. Se desactiva en Ajustes → Respuesta a ataques.
- [ ] **Recuperar el equipo entero desde un USB** cuando no arranca: ver 8.10 (fase 1).
- [x] **Periodo de aprendizaje en equipos nuevos** (13/10, Ajustes → Funciones, encendido): los primeros 7 días
      (configurable en modo experto) la detección solo deja un incidente amarillo «Revísalo», sin aislar ni restaurar.
      Los archivos trampa actúan siempre.
- [x] **Semáforo 3-2-1** en el inicio (v2.2), con lo que falta y cómo conseguirlo.
- [ ] **Modo para técnicos con varias empresas** (varios clientes en un panel, cada uno ve solo lo suyo).
- [ ] **Copia del correo y la nube** (Microsoft 365 / Google Workspace).

### 8.3 Usuarios guardados en otro sitio (lo que José describe: "acreditar gente", usuario/contraseña fuera de OCTOPUS)
Se llama **servidor de identidad / inicio de sesión único (SSO)**, o **directorio de usuarios (LDAP / Active
Directory)**. La contraseña no está en la base de datos de OCTOPUS: OCTOPUS pregunta a ese otro servidor "¿este
usuario es quien dice ser?" y solo recibe un sí/no y su rol. Si roban el servidor de OCTOPUS, no hay contraseñas.
**HECHO el 13/10 (en pruebas, apagado)** — `lib/identidad.py`, Ajustes → Funciones → Usuarios de la empresa (modo experto):
- [x] **Opción A — Active Directory / LDAP** (ldap3): busca al usuario (sin dejar colar filtros con `*`), comprueba su
      contraseña con el servidor y lee sus grupos. **Probado contra un OpenLDAP real**: entra, papel por grupo, sin
      grupo no entra, contraseña vacía no entra (nada de acceso anónimo), servidor caído → mensaje claro.
- [x] **Opción B — OIDC** (Microsoft 365/Entra, Google, Authentik, Keycloak): botón «Entrar con...», flujo con código
      + PKCE, comprueba firma, emisor, destinatario, caducidad, nonce y estado. Probado con un proveedor simulado (16
      pruebas, también en GitHub): token falso, caducado, de otra app o repetido no entran.
- [x] **Opción C — RADIUS** (cliente propio, con Message-Authenticator contra BlastRADIUS). **Probado contra un
      FreeRADIUS real**: acepta, rechaza, contraseñas largas y secreto equivocado.
- [x] Papel por grupo: «OCTOPUS-Admin» = todo; «OCTOPUS-Recuperar» = solo recuperar; «OCTOPUS-Lectura» = solo ver
      (nombres configurables). Con RADIUS, el papel se elige en el ajuste.
- [x] **Los usuarios locales siempre entran con lo suyo y no se pueden suplantar**: un usuario de la empresa con el
      mismo nombre que uno local NO entra (probado). Los de la empresa no tienen contraseña local ni «olvidé mi contraseña».
- [x] Desactivado por defecto: quien no tenga nada de esto sigue entrando como ahora.
- [ ] Falta: 2FA para el usuario local de emergencia (cuando José avise de la sección 1).
- Nota (13/10): las contraseñas locales de OCTOPUS ya se guardan solo como **hash bcrypt** (nunca en claro).
  El siguiente paso "sin secreto en la base de datos" son las **passkeys (WebAuthn)**: desafío-respuesta con
  clave pública; el servidor solo guarda el "candado" público (ver 8.4).

- Investigado (13/10) — para qué sirve y cómo hacerlo bien:
  - Sirve para que la gente entre con el usuario que ya tiene en la empresa: al dar de baja a un empleado pierde
    también el acceso a OCTOPUS, una contraseña menos, permisos por grupos. Útil con varios usuarios o técnicos;
    poco útil si solo entra una persona.
  - Lo usan los grandes: Veeam (SAML + doble autenticación), Proxmox Backup Server (LDAP + OpenID Connect).
    En el foro de Veeam lo más pedido es la doble autenticación, antes que el SSO. RADIUS se usa sobre todo para
    wifi/VPN, no tanto para paneles web.
  - **Aviso de seguridad (caso real del foro de Veeam)**: robaron la cuenta de administrador del dominio y llegaron
    a todo, pero el servidor de copias se salvó por tener usuarios propios fuera del dominio. Por eso:
  - [x] El **administrador principal de OCTOPUS es siempre local**; nadie más puede cambiarle el papel, la contraseña
        ni borrarlo (arreglado el 13/10: un administrador normal podía ponerle una contraseña nueva y quedarse su cuenta).
  - [x] Recomendado en la ayuda: dar a los usuarios externos permisos limitados (recuperar, solo ver).
  - [x] Compatible con OpenID Connect, LDAP y RADIUS (ver arriba).
  - Prioridad: después de la 2FA y las passkeys.

### 8.6 Botón "Enviar sugerencia o problema" — HECHO y LISTO; 🔴 <span style="color:red">**solo falta que José cree el bot y publique el buzón (15 min, guía en `proyecto/soporte/buzon/LEEME.md`)**</span> 🔴
- [x] (13/10) **Buzón de OCTOPUS** (`proyecto/soporte/buzon/worker.js`, Cloudflare Workers gratis): todos los
      servidores envían ahí y el buzón lo reenvía al Telegram de José. El token del bot está solo en la cuenta de
      Cloudflare de José (no en los servidores de los clientes ni en GitHub). Limita tamaño y número de mensajes.
      Probado con pruebas (envío, mensaje vacío, demasiado grande, límite por hora, sin configurar).
- [x] Los servidores ya envían al buzón (probado en local con un buzón de prueba: «Prueba enviada: enviada (buzón)»).
      Cada servidor manda un identificador anónimo (srv-xxxx) para saber si dos mensajes vienen del mismo.
- [x] Botón **«Enviar una prueba al soporte»** (solo administradores) en la página de sugerencias.
- [x] Una empresa que no quiera que salga nada: `SOPORTE_BUZON_URL=no`.
- [ ] 🔴 <span style="color:red">**José: crear el bot con @BotFather, publicar el buzón en Cloudflare y darle a Claude la
      dirección del buzón** (no es secreta) para ponerla en `BUZON_POR_DEFECTO`. Pasos exactos en
      `proyecto/soporte/buzon/LEEME.md`.</span>
- [x] Enlace en el pie de todas las páginas y en Ajustes: formulario (qué es, qué pasa, correo para responder).
- [x] Casilla "adjuntar diagnóstico" (sin contraseñas, claves ni nombres de archivos; equipos como equipo-1...).
- [x] Se guarda siempre en el servidor; si no se puede enviar, se reintenta cada noche y con el botón Solucionar
      del aviso OCT-SUG-01. El usuario ve en la misma página si llegó.
- [ ] (Opcional) correo de soporte además de Telegram (`SOPORTE_CORREO` en cada servidor) y sugerencias en GitHub
      (secretos `GITHUB_REPO`/`GITHUB_TOKEN` en el buzón).
- Importante: esos valores van en el `.env` de cada servidor (`sudo bash octopus.sh ajustes`), **nunca en el código**
  (el repositorio es público). Para que lleguen desde los servidores de los clientes sin repartir el token del bot,
  lo ideal más adelante es un pequeño "buzón" propio de OCTOPUS en internet que reciba y reenvíe.

### 8.7 Banderines en todo OCTOPUS (idea de José, 13/10)
Ya puestos en el instalador del servidor en Windows (`C:\ProgramData\OCTOPUS\instalacion_progreso.txt`).
Extenderlo a todo, que es lo que en informática se llama "registro estructurado" y "códigos de error":
- [x] (v2.2) Banderines en todos los instaladores (servidor Linux/Mac/Windows y agentes), en las copias (incluidos
      los pasos que hace el propio equipo), recuperaciones, pruebas, incidentes, mantenimiento y botón Solucionar
      (`/data/banderines/*.jsonl`, se recortan solos y se limpian de contraseñas).
- [x] Código para cada fallo en un catálogo único (enlaza con 8.1).
- [x] Botón **"Descargar diagnóstico"** (Ajustes → Mantenimiento): zip sin contraseñas ni nombres.
- [x] En la ficha de cada equipo, **"Últimos pasos"**.

### 8.4 Más capas de seguridad ("búnker", pero cómodo y sin ralentizar)
Ya hay: cifrado HTTPS, almacén solo-añadir, CSRF, cabeceras de seguridad, sesión de 30 min, bloqueo tras intentos
fallidos y límite por IP, API interna cerrada, kit cifrado.
- [ ] **Llaves de acceso (passkeys)**: entrar con la huella / Face ID / Windows Hello o una llave USB. Más
      seguro que contraseña + código y más cómodo (un toque). Encaja con la 2FA de la sección 1.
**HECHO el 13/10** — `lib/seguridad.py`, Ajustes → Funciones → Seguridad del panel (probado 26/26):
- [x] **Bloqueo automático de atacantes** (en pruebas): quien falla la contraseña o prueba páginas que no existen se
      bloquea un rato en todo el panel (intentos y minutos configurables), con aviso por correo/Telegram. Nunca bloquea
      al propio servidor ni a las direcciones de confianza; los equipos siguen haciendo copias. Lista de bloqueados y
      «Desbloquear» en modo experto.
- [x] **Aviso de acceso desde un navegador nuevo** (encendido): correo/Telegram con navegador, dirección y hora. Solo se
      guarda una huella del navegador. Falta el botón «No he sido yo» (de momento el aviso dice qué hacer).
- [x] **Doble aprobación para lo peligroso** (en pruebas): quitar un equipo, borrar un usuario, cambiar cuántas copias se
      guardan o apagar señuelos, respuesta a ataques, avisos o la propia doble aprobación lo tiene que aprobar otro
      administrador (Ajustes → Pendiente de aprobar). Caduca en 24 h. Nadie puede aprobar lo suyo. Si solo hay un
      administrador no se bloquea a nadie.
- [x] **Panel solo desde la red de la oficina o VPN** (en pruebas): fuera de esas redes el panel no responde, los equipos
      sí. Al encenderlo se añade sola la dirección desde la que estás, para no quedarte fuera.
- [x] **Si alguien se queda fuera**: `octopus.sh acceso-emergencia` (o `octopus.ps1`) en la consola del servidor quita
      bloqueos, «solo red de la oficina» y la doble aprobación.
- [x] **Usuarios y papeles** (Ajustes → Usuarios): crear usuarios con contraseña temporal que se ve una vez, papeles
      Administrador / Solo recuperar / Solo ver que se aplican al momento, poner contraseña nueva (cierra sus sesiones)
      y borrar. Cambiar la contraseña cierra las demás sesiones abiertas. Probado 27/27.
- [ ] **Claves del servidor en caja fuerte** (tipo Vault/OpenBao o al menos cifradas con una clave aparte), para
      que copiar el disco del servidor no dé las contraseñas de los almacenes.
- [x] (v2.2) **Registro de actividad firmado**: cada línea encadenada con la anterior (SHA-256); si alguien borra o
      cambia una línea, Ajustes → Registro de actividad lo dice (probado: cambiar una línea en la base de datos lo detecta).
- [x] (v2.2) **Aviso de versión nueva** cada noche (archivo VERSION del repositorio de GitHub) con los pasos para
      actualizar. El botón no puede actualizar solo desde dentro del contenedor: explica el comando y vuelve a comprobar.
- [ ] Revisar también las versiones de restic, Python y la imagen base (de momento solo la de OCTOPUS).

### 8.5 Lo que más valora la gente en los programas de copias (opiniones de usuarios)
- [x] (v2.2) **Asistente «Buscar y recuperar»** (Recuperar archivos): escribes el nombre o parte, eliges cuál, de
      cuándo y dónde dejarlo. Busca en el servidor, sin respetar mayúsculas.
- [x] (v2.2) **Quién recibe cada aviso**: ataques, copias, servidor e informe mensual, cada uno a sus correos.
- [x] (13/10) **Informes que llegan siempre**: si el día 1 no se puede enviar el informe (correo caído, sin
      Internet), se reintenta cada noche hasta el día 7 y sale el aviso OCT-SRV-03 mientras tanto.
- [x] (13/10) **Copias aunque haya cortes de luz**: si el equipo estaba apagado a la hora de su copia, la hace sola
      al encenderse (en Linux, Mac y Windows, sin esperar al día siguiente); si una copia se cortó a medias, el
      agente quita el bloqueo que dejó y la repite.
- [x] Panel central de todo y buen soporte de Linux (ya lo tenía).
- [x] (13/10) **Que una actualización nunca rompa las copias**: pruebas automáticas de GitHub en cada cambio +
      batería del laboratorio antes de cambiar la versión (explicado en el README), y **si al actualizar el servidor
      la versión nueva no arranca, el instalador vuelve solo a la anterior** (Linux, Mac y Windows).

### 8.8 Refinar, limpiar, optimizar y acelerar (pedido por José, 13/10) — PENDIENTE
- [ ] **Refinar y optimizar el código**: repasar módulo a módulo, simplificar lo enrevesado, quitar duplicados
      (p. ej. funciones repetidas entre panel, mantenimiento y agentes), nombres claros.
- [x] **Borrar código inservible** (13/10): quitados `intelligent_detection`, `alert_manager`, `config_presets`, la API
      interna 8081, `migrar.py`, n8n, 16 pantallas retiradas, ajustes y funciones que no usaba nadie, y las versiones
      Docker de Windows/Mac (apartado en `obsoletos\limpieza_20261013`). Encontrados y arreglados por el camino: en
      una instalación nueva el vigilante fallaba en cada vuelta (orden de creación de tablas), avisos falsos de
      «almacén con errores» mientras había copias en marcha, y una redirección a una página que ya no existía (error
      500 para quien no era administrador).
- [x] **Velocidad del panel medida** (13/10): con 300 equipos, todas las páginas tardan menos de 80 ms (Inicio, Equipos,
      Avisos, Recuperar, Ajustes, Funciones, Incidentes). No hace falta tocar nada por ahora.
- [ ] **Velocidad de las copias**: medir con equipos reales; ajustar compresión y paralelismo de restic
      (`--compression auto`, `--read-concurrency`, tamaño de paquete), primera copia más rápida, que no se copie dos
      veces lo mismo (ya deduplica), y que el límite de velocidad solo frene cuando haga falta.
- [ ] **Velocidad de recuperación y de búsqueda** (asistente): caché de la lista de archivos de la última copia.
- [ ] Mantenimiento nocturno más corto (limpieza y comprobación en paralelo cuando haya muchos equipos).
- [ ] Probar el antes y el después con números (tiempos en el laboratorio) para no empeorar nada.

### 8.9 Buscar los equipos de la red y darlos de alta en grupo (la idea original) — HECHO en el panel (13/10); falta el modo consola bonito
- [x] (13/10) **Equipos → «Buscar equipos en la red»** (y en el inicio mientras no hay equipos): 1) elegir redes (propone
      la del servidor; acepta otras como 192.168.2.0/24 o 10.0.5.*, máx. /22); 2) barrido en segundo plano con barra
      de progreso (puertos 22/445/135/139/3389/5985/548, sin nmap ni permisos); reconoce Windows / Linux (y la
      distribución por el saludo SSH) / Mac, saca el nombre (NetBIOS o DNS) y marca los que **ya están protegidos**;
      3) casillas, nombre, sistema y **grupo** de cada uno; 4) **usuario y contraseña por grupo** (no se guardan);
      5) instala en todos a la vez y enseña el progreso de cada uno con ✓/✗ y el motivo si falla.
- [x] **Windows también a distancia** por SSH (Servidor OpenSSH de Windows 10/11/Server), comprobando que el usuario es
      administrador; si no tiene SSH, lo explica y deja el instalador de doble clic. También en «Instalar» de la ficha.
- [x] El grupo se guarda en el equipo y se ve en su ficha.
- [x] Probado en local (equipos simulados Linux/Windows) y añadido a la batería del laboratorio.
- [x] **Instalación de Windows por SSH probada en el laboratorio** (13/10 23:47, `maquinas\PROBAR_INSTALACION_SSH_WINDOWS.bat`):
      en win2022 se activa el «Servidor OpenSSH» y desde el
      servidor, con el mismo código que el botón del panel, se instala en **20 s**, se conecta y responde a las órdenes.
      La contraseña no sale en ningún mensaje ni en el registro, y una contraseña mala se explica claro.
**Código original encontrado**: `obsoletos/install/instalar.sh` (instalador de la v1, por consola con ventanitas de
texto `dialog`): «Radar de redes» (elige subredes y las barre con `nmap`), lista con casillas de los equipos
encontrados, y contraseñas **por red** (la misma para toda la red), **por grupos** (marcas varios con la misma) o
**una a una**. Se apartó al rehacer la v2 porque desplegaba con el sistema antiguo; la idea se recupera así:
- Recomendado: hacerlo **desde el panel, con un botón**, una vez instalado (se puede repetir cuando haya equipos
  nuevos, vale para Windows/Linux/Mac y se ve el progreso de cada uno). Al terminar la instalación del servidor, el
  panel abre directamente el asistente «Buscar equipos en la red» la primera vez.
- Opcional: mantener el modo consola con ventanitas `dialog` en el instalador Linux para quien quiera hacerlo ahí
  mismo (reutilizando la misma función del servidor, para no tener dos códigos distintos).
- [x] **HECHO (13/10)**: `sudo bash octopus.sh buscar-equipos` (Linux y Mac) / `octopus.ps1 buscar-equipos` (Windows),
      con Textual: ventanas, colores, ratón y teclado, los mismos 4 pasos que el panel y el mismo código. Sin consola
      interactiva o sin la librería, preguntas en texto (`--sencillo`). Probado con el piloto de Textual (19/19, también
      en GitHub), en una terminal de verdad y contra equipos reales del laboratorio local.
- [x] **Al terminar de instalar el servidor** (Linux, Mac y Windows) pregunta «¿Busco ahora los equipos de la red?» y abre
      el buscador ahí mismo; si no, queda el botón grande del panel.
- [x] Lo que se pedía (para referencia): que no parezca que estás
      metiendo código, sino un programa con ventanas:
      - Pantallas con colores, recuadros y el logo de OCTOPUS; menús que se manejan con flechas, Enter, **y también con
        el ratón** (funciona en la consola de un servidor sin escritorio y por SSH).
      - Cada paso dice en una frase qué hace y qué hay que pulsar, con la tecla de ayuda siempre visible abajo
        («Espacio: marcar · Enter: seguir · Esc: atrás»). Nada de comandos que escribir.
      - Barras de progreso por equipo al instalar, con ✓ verde / ✗ rojo, y el aviso con código y solución si falla.
      - Resumen final claro: «12 equipos protegidos, 1 no se pudo (por qué y qué hacer)» y la dirección del panel.
      - Cómo hacerlo: con la librería **Textual** de Python (pantallas modernas en la consola, con ratón) dentro del
        propio contenedor de OCTOPUS (`sudo bash octopus.sh buscar-equipos`), así no hay que instalar nada más en el
        servidor y usa exactamente la misma función que el botón del panel. Si la consola no admite colores, cae
        a las ventanitas sencillas de siempre.
Hoy: en la ficha de cada equipo hay «Instalar desde aquí» (IP + usuario + contraseña, solo Linux y Mac, de uno en
uno); en Windows, el instalador de doble clic; y para muchos Linux a la vez, `octopus.sh desplegar` (Ansible, por
consola). La idea original (ya hecha el 13/10, ver arriba):
- [x] **«Buscar equipos en la red»** en el panel: escanea la red de la oficina y lista lo que encuentra (nombre,
      IP, sistema si se puede saber: Windows / Linux / Mac), marcando los que ya tienen OCTOPUS.
- [x] Elegir varios con casillas y **agruparlos** (p. ej. «Oficina», «Servidores», «Portátiles»).
- [x] **Usuario y contraseña por grupo** en una ventanita del panel (no por consola): se usan una vez para instalar
      y se olvidan (como ahora). Progreso de cada equipo en la misma ventana, con banderines y avisos si alguno falla.
- [x] Windows también a distancia (SSH de Windows 10/11 o WinRM, si está activado; si no, el aviso explica cómo
      activarlo o deja el instalador de doble clic).
- [x] La ventana va en el **panel web**, que se abre desde cualquier PC con navegador: los servidores sin entorno
      gráfico no necesitan ventana propia. Para instalar a mano en un servidor sin pantalla gráfica, el instalador
      puede usar un **menú en modo texto** (tipo whiptail/dialog: ventanitas con flechas y Enter dentro de la consola).

### 8.10 Levantar equipos enteros y desplegar sistemas en masa (tipo FOG / Clonezilla) — preparado y apagado; fases por hacer
- [x] (13/10) En Ajustes → Funciones: USB de rescate, imagen de disco, arranque por red y despliegue en masa, «En pruebas»
      y apagados. En la ficha de cada equipo, «Levantar el equipo entero» con sus botones; **en un Mac salen desactivados
      con el motivo** (Apple no deja clonar ni arrancar por red los Mac modernos; la alternativa es Apple Business
      Manager con un MDM y «Borrar contenidos y ajustes»). El arranque por red dice por qué no está disponible si el
      servidor es Mac o Windows. El botón de despliegue en masa sale en Equipos (modo experto) con su explicación.
- [ ] Las fases de verdad (abajo). Necesitan probarse arrancando máquinas de verdad (VirtualBox del laboratorio, en
      modo EFI): en el entorno de Claude no hay virtualización para arrancar imágenes.
**Módulo OPCIONAL**: se elige al instalar el servidor o se activa luego en Ajustes. Si no se activa no ocupa nada ni
gasta recursos (pensado para servidores pequeños). Esfuerzo estimado: **grande (varias semanas)**, por fases.

Viabilidad:
| Qué | ¿Viable? |
|---|---|
| Recuperar un equipo entero que no arranca (Linux/Windows) | Sí |
| Desplegar el mismo sistema en muchos equipos | Sí en Windows y Linux; **no en Mac** |
| Detectar equipos sin sistema | Solo si arrancan por red (PXE) |
| Hacerlo solo con el agente, sin arranque de rescate | No (un sistema no puede sobrescribirse mientras funciona) |

Problemas a resolver:
- La copia completa actual guarda **archivos**, no el disco tal cual: hace falta un tipo de copia nuevo,
  **«imagen de disco»** (particiones y arranque incluidos), con herramientas libres como partclone (la de Clonezilla).
- Windows: en el mismo equipo o en uno igual, viable; en equipos distintos hay que preparar la imagen con **sysprep**
  (drivers e identidad de Windows).
- Linux: el caso más fácil. Mac: no viable (Apple no deja poner imágenes ni arrancar por red un sistema propio).
- Secure Boot / UEFI: con piezas firmadas (shim/GRUB de Ubuntu). BIOS antiguas también.
- El servidor tiene que estar en la misma red; para arrancar por red usa DHCP en modo «proxy» (sin tocar el router) y
  TFTP/HTTP, con permisos de red extra para el contenedor.
- Licencias: FOG, Clonezilla, partclone e iPXE son GPL (código público). Se usan como herramientas, sin copiar su
  código dentro de OCTOPUS. Los de pago (Acronis, SCCM) no tienen código disponible: solo se puede copiar la idea.

Fases:
- [ ] **Fase 1 — USB de rescate de OCTOPUS**: el panel genera un pendrive (mini-Linux) que arranca el equipo roto, se
      conecta al servidor, deja elegir equipo y copia, y vuelca la imagen de disco. Funciona en cualquier red.
- [ ] **Fase 2 — Copia «imagen de disco»** opcional por equipo (como la copia completa, pero del disco entero en bloque)
      para poder levantar el sistema tal cual estaba.
- [ ] **Fase 3 — Arranque por red (PXE) desde el servidor**: el equipo arranca con F12/red y aparece en el panel como
      «equipo nuevo esperando» (por su MAC); desde ahí se elige qué imagen ponerle. Encendido a distancia
      (Wake-on-LAN) si la BIOS lo permite.
- [ ] **Fase 4 — Despliegue en masa**: una imagen de referencia (Windows preparada con sysprep o Linux) a muchos
      equipos a la vez, con progreso de cada uno, avisos y banderines.

### 8.11 Actualizar OCTOPUS a distancia, de forma segura — HECHO (13/10); 🔴 <span style="color:red">**falta que José cree su clave de publicación y firme la versión**</span> 🔴
- [x] Busca versión nueva **sola cada 2 días** (`OCTOPUS_ACTUALIZACIONES_DIAS`) y con el botón **«Buscar actualizaciones»**
      (Ajustes → Actualizaciones). Si hay una nueva sale el aviso OCT-ACT-01.
- [x] Botón **«Actualizar ahora»** (pide la contraseña, queda registrado): se hace desde cualquier PC con el panel.
- [x] **Seguro**: el panel no ejecuta nada; solo deja la petición. Un temporizador del equipo (cada 5 min) la recoge,
      descarga de la dirección oficial por HTTPS y **solo instala si la versión viene firmada** con la clave de
      publicación (la pública es la de la instalación, no la de la descarga); un archivo cambiado, de más o de menos =
      no se instala; nunca instala una versión más antigua; guarda copia de la carpeta y, si la nueva no arranca,
      vuelve sola a la anterior. Probado con 10 pruebas (firma buena, manipulado, otra clave, archivo de más, versión
      antigua, sin clave, instalación fallida, sin petición).
- [x] **Se actualiza solo** (13/10): si hay versión nueva firmada, el mantenimiento de las 03:30 la pide sola (solo de
      madrugada, porque el panel se reinicia). Si falla, reintenta como mucho 3 veces con 2 días entre intentos y
      luego avisa. Los botones quedan por si no se actualiza solo por lo que sea.
- [x] **Botón «Poner en pausa las actualizaciones»** (y «Volver a actualizar solo») por si el cliente no quiere
      actualizar: en pausa sigue avisando de las versiones nuevas pero no instala nada solo. Queda en el registro.
- [x] Linux (systemd) y Mac (LaunchAgent). Herramientas: `herramientas/crear_manifiesto.sh` y `herramientas/firmar_version.sh`.
- [ ] 🔴 <span style="color:red">**José: crear la clave de publicación** (en tu PC, con Git Bash, dentro de la carpeta proyecto:
      `bash herramientas/firmar_version.sh` → la primera vez crea la clave y deja la pública en
      `install/firma_publicacion.pub`). Avisa a Claude para publicarla; luego, en cada versión, vuelves a ejecutar el
      script para firmar. **La clave privada no se comparte con nadie, tampoco con Claude.** Hasta entonces, la
      actualización a distancia está desactivada (por seguridad) y se actualiza a mano.</span>
- [x] Laboratorio (13/10): batería completa 111/0 (buscar equipos, alta en grupo, actualizaciones, avisos que se
      arreglan solos). La de Windows por SSH, lanzada (ver 8.9).
- [x] Servidores Windows: actualizador automático (`actualizador.ps1`, tarea «OCTOPUS Actualizador» cada 5 min), probado en GitHub.
- [ ] Los servidores ya instalados reciben la clave pública con la primera actualización hecha a mano.

Fuentes de las ideas: Veeam (Backup features small businesses should demand), Domotz (Best RMM tools for small
businesses 2026), foro de Veeam (aviso si no hay copias en X días), foros de UrBackup y Backup4all
(aviso al terminar una restauración).

## 9. Hecho el 13/10 por la noche (versión 2.3) — «todo configurable, básico o experto»
- [x] **Ajustes → Funciones** (`lib/funciones.py`): un único sitio con todo lo que se puede encender, apagar y ajustar,
      por grupos (Copias, Ataques, Seguridad del panel, Usuarios de la empresa, Equipos). **Modo básico** (lo justo,
      explicado en una frase) o **modo experto** (todos los números finos), cada usuario el suyo. Los interruptores se
      guardan solos al pulsarlos. Valida lo que se escribe (números con mínimo y máximo, redes) y los secretos nunca
      se vuelven a enseñar. Todo queda en el registro.
- [x] Lo que da guerra está hecho pero **«En pruebas»**: viene apagado, solo se enciende en modo experto marcando «Sé que
      está en pruebas», y queda apuntado quién lo encendió.
- [x] Usuarios y papeles, capas de seguridad y usuarios de la empresa (ver 8.3 y 8.4).
- [x] Modo consola y pregunta al terminar de instalar (ver 8.9).
- [x] Servidor de Windows en VM: todo correcto tras arreglar el firewall en redes «públicas» (ver 5).
- [x] Pruebas: Funciones 19/19, seguridad 26/26, usuarios 27/27, LDAP+RADIUS reales 20/20, OIDC 16/16, consola 19/19,
      y las de antes sin cambios (buscar 12/12, vigilante, v22). GitHub con las pruebas nuevas.

## 10. Hecho el 14/10 de madrugada (versión 2.4)
- [x] Doble autenticación con el móvil (sección 1) y monitorización (sección 2).
- [x] Batería del laboratorio con la versión nueva: **111 correctas, 0 fallos** (incluida la doble autenticación).
- [x] Fallo encontrado por GitHub y arreglado: en una instalación nueva el servidor no arrancaba (la 2FA tocaba la tabla
      de usuarios antes de crearla). Añadida a GitHub una comprobación de «arranca con base de datos nueva y las 35
      pantallas compilan» para que no vuelva a pasar.
- [x] `GUIA_PRUEBA_EQUIPOS_FISICOS.md`: 1 hora, con casillas, para probar en un Windows, un Mac y un portátil reales.
- [x] Borradores en `proyecto/legal/`: licencia de uso y protección de datos (RGPD), con lo que hay que rellenar y revisar
      con un asesor (incluido lo de informar a los trabajadores si se monitorizan sus equipos).
