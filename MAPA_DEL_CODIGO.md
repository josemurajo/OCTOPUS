# Mapa del código de OCTOPUS — para saber qué tocar

> Guía para orientarse rápido. Dice **qué hace cada parte** y **qué archivo tocar** para cambiar cada cosa.
> Todos los archivos de código llevan arriba una explicación de para qué son.

## En una frase
El **servidor** (un contenedor Docker, o instalado nativo en Windows/Mac) tiene un **panel web**. Cada **equipo** de
la empresa lleva un **agente** que, cada pocos segundos, le pregunta al servidor «¿algo para mí?» por HTTPS, hace lo
que haya (copias, etc.) y responde. El servidor **nunca entra** en los equipos: por eso funciona sin abrir puertos.

## Las carpetas
| Carpeta | Qué es |
|---|---|
| `lib/` | El servidor y el panel (casi todo el cerebro está aquí) |
| `templates/` | Las pantallas del panel (HTML) |
| `agentes/` | El programa que va en cada equipo (`zerotouch_agent.py`), el de monitorización (`octopus_monitor.py`) y el de copias de máquinas virtuales (`octopus_vms.py`) y el de bases de datos (`octopus_bd.py`) |
| `tests/ci/` | Pruebas automáticas que GitHub pasa en cada cambio (Linux, Windows y Mac) |
| `legal/` | Textos legales (licencia, privacidad, plantillas para la empresa) — se ven en el panel en «Legal y privacidad» |
| `herramientas/` | Firmar una versión, crear el manifiesto |
| `install/` | docker-compose y la sala de análisis de incidentes |
| `maquinas/` (al lado) | El laboratorio de pruebas con máquinas virtuales |

## Los archivos de `lib/` (el cerebro)
| Archivo | Para qué | Tócalo para… |
|---|---|---|
| `admin_panel.py` | El panel web entero (Flask): cada página y cada botón | cambiar una página, un botón o una regla del panel |
| `funciones.py` | La **lista** de todo lo que se puede encender/apagar/ajustar | añadir una función nueva, cambiar su texto, su nivel (básico/experto) o si viene encendida |
| `config_manager.py` | Guarda y lee los ajustes en la base de datos | (rara vez) cómo se guardan los ajustes |
| `ordenes.py` | La **cola** de órdenes para los agentes | cambiar cómo el servidor manda trabajo a los equipos |
| `agentes.py` | Da de alta equipos y prepara sus instaladores | el alta de equipos y los paquetes de instalación |
| `alta_equipos.py` | Empaqueta el instalador del agente (con el monitor dentro) | qué archivos se le meten al agente |
| `mantenimiento.py` | Tareas de cada noche: borrar copias viejas, verificar, copia del servidor, buscar versión nueva | el mantenimiento automático |
| `incidentes.py` | Respuesta a ataques (aislar, copia forense, restaurar) | cómo se actúa ante un ransomware |
| `seguridad.py` | Bloqueo de atacantes, avisos de acceso nuevo, doble aprobación | las capas de seguridad del panel |
| `dosfa.py` | Doble autenticación con el móvil (TOTP) | la 2FA (códigos, recuperación, quitar) |
| `identidad.py` | Entrar con los usuarios de la empresa (LDAP/AD, RADIUS, OIDC) | la conexión con Active Directory, Microsoft 365, etc. |
| `monitor.py` | Monitorización de equipos (guarda lo que mandan, historial, avisos) | la monitorización en el servidor |
| `avisos.py` | **Catálogo** de avisos: cada problema con su código, qué pasa, por qué importa y los pasos para arreglarlo | el texto de un aviso o su botón «Solucionar» |
| `legal.py` | Enseña los textos legales en el panel (convierte los .md a web, sin dejar meter HTML) | la página «Legal y privacidad» |
| `sugerencias.py` | El botón «Enviar sugerencia o problema» (al buzón de soporte) | el soporte |
| `informe.py` | El informe mensual | el informe |
| `consola.py` | El modo consola (`octopus.sh buscar-equipos`): buscar y proteger equipos sin navegador | el modo texto/ventanas |
| `servidor.py` | Arranca el servidor (TLS, pone en marcha el panel y el mantenimiento) | el arranque |
| `firma.py` | Comprueba la firma de las versiones (para que una actualización no sea falsa) | la firma de versiones |

## Cómo cambiar las cosas más habituales
- **Encender una función de serie, o cambiar sus opciones** → `lib/funciones.py` (la lista `FUNCIONES`). `defecto`
  = si viene encendida; `nivel` = básico o experto; `en_pruebas: True` = hecha pero apagada hasta probarla en
  equipos reales (el usuario la enciende a sabiendas). Al terminar de probarla, se le quita `en_pruebas`.
- **El aspecto del panel** (colores, tipografía, cabecera, pie) → `templates/base.html`.
- **El texto de una pantalla** → su archivo en `templates/` (el nombre coincide con la página).
- **Un aviso nuevo, o cambiar qué dice y qué botón tiene** → `lib/avisos.py`.
- **Qué recoge la monitorización** (y qué no se guarda nunca) → función en `lib/funciones.py` (opciones de
  `monitorizacion`) y `lib/monitor.py` (`_privacidad`).
- **Copias de bases de datos** → `agentes/octopus_bd.py` (cada motor: detectar, cómo entrar, copiar, recuperar); el
  panel en `lib/admin_panel.py` (rutas `/equipos/<id>/bd`) y `templates/bd.html`; cada cuánto lo decide `bd_loop()` en
  el agente; cuánto se guardan, en `lib/mantenimiento.py` (etiqueta `bd`).
- **Copias de máquinas virtuales** → `agentes/octopus_vms.py` (cada hipervisor: detectar, copiar, recuperar); el
  panel en `lib/admin_panel.py` (rutas `/equipos/<id>/vms`) y `templates/vms.html`; cuánto se guardan, en
  `lib/mantenimiento.py` (etiqueta `vm`).
- **Textos legales** → los `.md` de `legal/` (se ven solos en el panel). La lista de cuáles se enseñan, en
  `lib/legal.py` (`DOCUMENTOS`).
- **El nombre del autor / la atribución** → `NOTICE`, `AUTHORS` y la cabecera de cada archivo de código.

## Las pruebas
- **GitHub** pasa solas las de `tests/ci/` en cada cambio (ver `.github/workflows/pruebas.yml`). Si algo falla, no
  se publica.
- Antes de cambiar `VERSION`, se pasa la **batería del laboratorio** (`maquinas/`), que prueba con máquinas de verdad.
- Regla de oro: **cada función nueva, su prueba**. Así una mejora no rompe lo que ya iba.
