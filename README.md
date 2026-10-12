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
Después, en el panel: **Equipos → Añadir equipo**.

- **Linux y Mac**: "Desde aquí" — se pone la IP, el usuario y la contraseña del equipo y el servidor
  entra y lo instala todo (la contraseña no se guarda).
- **Windows**: se descarga un instalador y se ejecuta con doble clic en el equipo.

## Carpetas del proyecto

| Carpeta / archivo | Qué es |
|---|---|
| `instalar_servidor.sh` | Instalador del servidor (Linux). Volver a ejecutarlo actualiza sin perder nada |
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

## Versión

Ver `VERSION`. La versión 2.1 añade: prueba de recuperación automática, copias sospechosas marcadas,
aviso sin copia configurable por equipo, aviso al terminar una recuperación, kit cifrado opcional,
límite de velocidad de las copias e informe mensual.
