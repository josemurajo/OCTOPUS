# OCTOPUS Zero-Touch

*Creado por **José Murillo Rajo**. Software libre y gratuito (AGPL-3.0).*

Copias de seguridad automáticas y cifradas para los equipos de una empresa, con respuesta automática
a ataques (ransomware) y un panel web pensado para personas que no son técnicas.

- **Copias cada día** de las carpetas importantes de cada equipo (Windows, Linux y Mac), cifradas antes de salir.
- **Almacén "solo añadir"**: los equipos pueden guardar copias pero no borrarlas. Un atacante que entre en
  un equipo no puede destruir sus copias.
- **Ataques**: si un equipo empieza a cifrar archivos en masa, OCTOPUS lo aísla de la red, guarda una copia
  forense, restaura la última copia limpia y avisa.
- **Prueba de recuperación semanal**: OCTOPUS recupera de verdad unos archivos de cada equipo para comprobar
  que las copias sirven.
- **Avisos** por correo y Telegram, siempre con "qué hacer". **Informe mensual** para imprimir o enviar.
- **Kit de recuperación**: las claves para abrir las copias aunque se pierda el servidor.
- **Copia completa del equipo** (opcional): todo el disco, para reconstruir un equipo entero.
- **Bases de datos**: SQL Server, MySQL/MariaDB y PostgreSQL copiadas por su propio motor (siempre sirven), cada día,
  cada 4 horas o cada hora; se vuelve a la hora que quieras como una base nueva, sin tocar la original.
- **Máquinas virtuales** (en pruebas): copia cada máquina **entera** aunque esté encendida (Hyper-V, KVM/libvirt y
  Proxmox) y la recupera aparte, sin tocar la original.
- **Monitorización** (opcional, viene apagada): uso, temperatura, discos y batería de cada equipo, en directo.
- **Panel seguro**: doble autenticación con el móvil, bloqueo de atacantes, usuarios de Active Directory/Microsoft 365.

| Para… | Mira |
|---|---|
| Instalarlo en una empresa | **[PRODUCCION.md](PRODUCCION.md)** |
| Probarlo con máquinas virtuales | **[maquinas/](maquinas/)** (laboratorio con su README) |
| Saber qué archivo tocar para cambiar algo | **[MAPA_DEL_CODIGO.md](MAPA_DEL_CODIGO.md)** |
| Ver que todo pasa las pruebas | pestaña **Actions** (Linux, Windows y Mac en cada cambio) |

## Cómo funciona

```
 Equipos (agente)                          Servidor OCTOPUS (un contenedor Docker)
 ┌──────────────┐   HTTPS 8080 (órdenes)   ┌────────────────────────────────────────┐
 │ zerotouch_   │ ───────────────────────► │ Panel web + canal de órdenes (8080)    │
 │ agent.py     │   HTTPS 8000 (copias)    │ Almacén de copias restic, solo añadir  │
 │ + restic     │ ───────────────────────► │ (8000)                                 │
 └──────────────┘                          │ Mantenimiento nocturno (03:30)         │
   No abre puertos: es el                  │ Datos en los volúmenes /data y /boveda │
   equipo el que llama al servidor         └────────────────────────────────────────┘
```

- Cada equipo tiene **su propia clave** para hablar con el servidor y se conecta él (no hace falta abrir
  puertos en los equipos).
- Solo hay **dos puertos TCP** en el servidor, los dos cifrados con una autoridad de certificados propia.
- Las copias se hacen con [restic](https://restic.net): formato abierto, se pueden abrir sin OCTOPUS con
  la clave del kit de recuperación.

## Instalar en dos minutos

En un servidor Linux recién instalado (Ubuntu, Debian, Rocky, Fedora...):

```bash
sudo bash instalar_servidor.sh
```

Instala Docker si no está, arranca OCTOPUS y muestra la dirección del panel y la contraseña inicial.
También en **Windows** (doble clic en `INSTALAR_SERVIDOR_WINDOWS.bat`) y **Mac** (doble clic en `INSTALAR_SERVIDOR_MAC.command`),
sin WSL2, sin Docker y sin Homebrew: el sistema pide la contraseña de administrador una vez y lo demás lo hace solo:
ver [PRODUCCION.md](PRODUCCION.md).
¿Tienes un **NAS Synology o QNAP, Unraid, Portainer o Proxmox**? Se instala pegando un archivo, sin compilar
nada: ver [INSTALAR_EN_NAS.md](INSTALAR_EN_NAS.md).

Después, en el panel: **Equipos → Añadir equipo**.

- **Linux y Mac**: "Desde aquí" — se pone la IP, el usuario y la contraseña del equipo y el servidor
  entra y lo instala todo (la contraseña no se guarda).
- **Windows**: se descarga un instalador y se ejecuta con doble clic en el equipo.

## Carpetas del proyecto

| Carpeta / archivo | Qué es |
|---|---|
| `instalar_servidor.sh` | Instalador del servidor (Linux). Volver a ejecutarlo actualiza sin perder nada |
| `INSTALAR_SERVIDOR_WINDOWS.bat`, `instalar_servidor_windows.ps1`, `octopus.ps1`, `actualizador.ps1` | Servidor en Windows (nativo: sin WSL2 ni Docker) |
| `INSTALAR_SERVIDOR_MAC.command`, `instalar_servidor_mac.sh` | Servidor en Mac (nativo: sin Docker ni Homebrew) |
| `octopus.sh` | Gestión del servidor: estado, logs, kit, mantenimiento, actualizar, volver... |
| `Dockerfile`, `install/docker-compose.yml` | La imagen y el contenedor del servidor |
| `lib/` | El servidor: panel (`admin_panel.py`), arranque (`servidor.py`), mantenimiento, incidentes, informe... |
| `templates/` | Las pantallas del panel |
| `agentes/zerotouch_agent.py` | El agente que va en cada equipo (el mismo para Windows, Linux y Mac) |
| `agentes/instaladores/` | Instaladores del agente que entrega el panel (Windows `.bat/.ps1`, Linux `.sh`, Mac `.command`) |
| `ansible/` | Despliegue de agentes a muchos equipos Linux a la vez (`octopus.sh desplegar`) |
| `install/sandbox/` | Sala de análisis de incidentes (contenedor aislado sin red) |
| `tests/ci/` | Pruebas automáticas en equipos reales de GitHub (Linux, Windows y Mac) |

El laboratorio de pruebas con máquinas virtuales está en la carpeta `maquinas` (al lado de esta).

## Cómo se publica una versión (para que una actualización nunca rompa las copias)

1. Cada cambio que se sube a GitHub pasa solo las pruebas automáticas en equipos reales (Linux, Windows y Mac).
2. Quien mantiene el código prepara la versión: explica los cambios en [CHANGELOG.md](CHANGELOG.md) y ejecuta
   `bash herramientas/preparar_version.sh 3.0.0` (pone el número y crea el MANIFIESTO con la huella de cada archivo).
3. José la **firma** en su PC (`bash herramientas/firmar_version.sh`, con su clave privada, que nunca sale de su PC) y
   sube el archivo `MANIFIESTO.sig` a GitHub. Paso a paso: [PUBLICAR_VERSION.md](PUBLICAR_VERSION.md).
4. A partir de ahí todo es automático: se comprueba la firma, la versión pasa a la rama `publicado` (la única que
   descargan los servidores), se crea en *Releases* y se publica la imagen para los NAS. Lo que está a medio hacer en
   `main` nunca llega a las empresas.
5. Al actualizar un servidor, si la versión nueva no arranca, se vuelve sola a la anterior.

## Versión

Ver `VERSION` y la lista de cambios en [CHANGELOG.md](CHANGELOG.md).

## Licencia

OCTOPUS Zero-Touch es **software libre y gratuito**, con licencia **GNU AGPL-3.0 o posterior** ([LICENSE](LICENSE)):
se puede usar, copiar, modificar y repartir, también en empresas. La única condición importante es que quien
reparta el programa, o lo ofrezca a otros a través de la red con cambios, publique también su código con la misma
licencia.

Se entrega **«tal cual», sin garantía de ningún tipo** (secciones 15 y 16 de la licencia). Ningún sistema de copias
garantiza recuperar todo en cualquier caso: guarda el kit de recuperación fuera del servidor y revisa los avisos.

- Componentes de terceros y sus licencias: [TERCEROS.md](TERCEROS.md)
- Avisar de un fallo de seguridad: [SECURITY.md](SECURITY.md)
- Colaborar: [CONTRIBUTING.md](CONTRIBUTING.md)
- El nombre y el logotipo: [MARCA.md](MARCA.md)
- Protección de datos para quien lo instala: [legal/](legal/)
