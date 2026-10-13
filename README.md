# OCTOPUS Zero-Touch

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

Instalación y uso en una empresa: **[PRODUCCION.md](PRODUCCION.md)**.

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
| `instalar_servidor_windows_docker.ps1`, `instalar_servidor_mac_docker.sh` | Opcional: servidor con Docker en Windows / Mac |
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

## Antes de publicar una versión (para que una actualización nunca rompa las copias)

1. Cada cambio que se sube a GitHub pasa solo las pruebas automáticas (agente en Linux, Windows y Mac, instalador
   nativo del servidor en Windows y en Mac, almacén con bloqueo por tiempo y sintaxis de todos los scripts). Si algo falla, no se publica.
2. Antes de cambiar `VERSION`, se pasa la batería del laboratorio (`maquinas/EJECUTAR_PRUEBAS.bat`): tiene que salir
   «TODO CORRECTO».
3. Para que los servidores puedan actualizarse solos, la versión se **firma**: `bash herramientas/crear_manifiesto.sh`
   (lista de archivos con su huella) y, en el PC de quien publica, `bash herramientas/firmar_version.sh` (con su clave
   privada, que nunca sale de su PC). Sin firma válida ningún servidor instala la versión.
4. Al actualizar un servidor, si la versión nueva no arranca, el instalador vuelve solo a la anterior.

## Versión

Ver `VERSION`. La versión 2.2 añade: avisos con código, explicación y botón «Solucionar», banderines (pasos de cada
proceso) y diagnóstico descargable, semáforo 3-2-1, archivos señuelo contra ransomware, asistente «Buscar y
recuperar», «Enviar sugerencia o problema», quién recibe cada aviso, registro de actividad firmado y aviso de
versión nueva. La versión 2.1 añadió: prueba de recuperación automática, copias sospechosas marcadas,
aviso sin copia configurable por equipo, aviso al terminar una recuperación, kit cifrado opcional,
límite de velocidad de las copias e informe mensual.
