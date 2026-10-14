# Laboratorio Vagrant - OCTOPUS Zero-Touch v2

Esta carpeta (`maquinas`) va siempre junto a la carpeta `proyecto`. El servidor del laboratorio
se instala desde `proyecto` en un Ubuntu 24.04 vacío, igual que se instalaría en producción.

## Uso

- **Doble clic en `EJECUTAR_PRUEBAS.bat`**: crea las máquinas, instala todo y hace las pruebas.
  El informe queda en `reportes\informe_<fecha>.txt` (PASS / FAIL / WARN por prueba).
- `EJECUTAR_PRUEBAS_WINDOWS.bat`: prueba con un equipo Windows Server 2022 (instalado con el instalador del panel).
- `RECARGAR_PANEL.bat`: copia a cerebro los cambios del proyecto y reinicia el panel (sin pasar las pruebas).
- `REINICIAR_CEREBRO_Y_PROBAR.bat`: si cerebro se queda colgado, lo apaga a la fuerza y lanza las pruebas.
- `PROBAR_INSTALACION_CON_CONTRASENA.bat`: prueba "Añadir equipo → Desde aquí" con un cliente1 recién creado.
- `DEMO_ATAQUE.bat`: demo manual de ataque simulado en cliente1 (mira el panel → Incidentes).
- `LIMPIAR_MAQUINAS.bat`: borra máquinas virtuales que sobran (nunca las de los laboratorios).
- `APAGAR_MAQUINAS.bat`: apaga las máquinas. `BORRAR_MAQUINAS.bat`: las borra (el proyecto no se toca).
- Avanzado (PowerShell): `.\ejecutar_todo.ps1 -Todo`, `-SoloPruebas`, `-Limpio`; `.\menu_principal.ps1`.

Las máquinas se llaman `ZT2-*` y usan las mismas IPs que el laboratorio de la v1:
**no tengas los dos laboratorios encendidos a la vez**.

## Máquinas

| VM | IP | SO | RAM | Función |
|---|---|---|---|---|
| cerebro | 192.168.10.10 / 192.168.20.10 | Ubuntu 24.04 | 3 GB | servidor OCTOPUS en un contenedor: panel (8080) y almacén (8000) |
| cliente1 | 192.168.10.20 | Ubuntu 20.04 | 1 GB | cliente protegido |
| cliente2 | 192.168.20.20 | Rocky Linux 9 | 1 GB | cliente en la red segura |
| rocky9 | 192.168.10.50 | Rocky Linux 9 | 1 GB | opcional |
| debian12 | 192.168.10.60 | Debian 12 | 1 GB | opcional |
| win2022 | 192.168.10.40 | Windows Server 2022 | 4 GB | opcional (agente Windows) |
| router | 192.168.10.254 / 192.168.20.254 | Ubuntu 20.04 | 512 MB | opcional |

## Qué hace `ejecutar_todo.ps1`

1. Comprueba Vagrant, VirtualBox y la RAM libre.
2. `vagrant up cerebro` (Ubuntu 24.04 vacío): copia `..\proyecto` a `/opt/zerotouch` y ejecuta `instalar_servidor.sh`
   (Docker y el contenedor `octopus`: panel, almacén de copias, API interna y mantenimiento).
3. Levanta los clientes, libera los incidentes que quedaran abiertos de otra prueba y **despliega los agentes
   con Ansible desde el contenedor** (`docker exec octopus bash /app/ansible/deploy_vagrant.sh`).
4. Pruebas desde el cerebro (`scripts/pruebas_cerebro.sh`), con un usuario de pruebas temporal en el panel
   (se borra al terminar; no toca tu usuario admin):
   - servidor: contenedor sano, solo 2 puertos (8080 y 8000), certificado válido para 192.168.10.10 y 192.168.20.10,
     almacén con contraseña y en modo solo-añadir, API interna cerrada, CSRF, cabeceras, claves falsas rechazadas
   - instalador que da el panel («Añadir equipo») instalado de verdad en cliente1
   - por cliente: SSH solo con clave, ningún puerto abierto, agente conectado, **copia**, la copia se ve en el
     almacén, **explorar** la copia desde el panel, archivo estropeado → **restaurado desde el panel**,
     carpeta vaciada → restaurada
   - **incidente declarado desde el panel** en el primer cliente: aislar, copia forense, vuelta a la copia sana,
     aviso al usuario, sala de análisis y **liberar desde el panel** (sin simular ataques; la demo es `DEMO_ATAQUE.bat`)
   - **mantenimiento** (limpieza, comprobación, copia del servidor, vigilancia) y **kit de recuperación**
     (se descarga con contraseña y con su clave se leen las copias sin el panel)
5. Genera el informe.

## Accesos

- Panel: **https://192.168.10.10:8080**. Usuario `admin`.
  La contraseña inicial está en `.runtime\CREDENCIALES_INICIALES.txt`; al entrar la primera vez te pide cambiarla.
  El navegador avisará de que el certificado no es de una entidad conocida (es propio del servidor): pulsa
  «Configuración avanzada» → «Continuar». La conexión va cifrada igualmente.

## Seguridad (capas)

1. Panel por HTTPS, cookies seguras, token anti-CSRF en todos los formularios y cabeceras de seguridad.
2. Bloqueo de la cuenta 15 min tras 5 intentos fallidos; sesión que caduca a los 30 min sin uso.
3. Contraseña inicial de un solo uso (obliga a cambiarla) y mínimo 12 caracteres.
4. La API solo escucha dentro del servidor.
5. **Sin puertos abiertos en los equipos**: el agente se conecta él al servidor por HTTPS (autoridad de
   certificados propia de OCTOPUS) y recoge sus órdenes. Su puerto 9999 solo escucha en 127.0.0.1.
6. El servidor entra en los equipos con **clave SSH**; tras el primer despliegue se **desactiva el acceso
   SSH con contraseña**.
7. Cada equipo tiene su propia clave (si se roba, solo vale para ese equipo) y solo restaura dentro de las carpetas protegidas.
8. Las copias van cifradas por restic antes de salir del equipo.

## Respuesta automática a ataques (ransomware)

Cuando el agente de un equipo detecta un ataque grave (extensiones de ransomware, nota de rescate o
cifrado masivo de archivos), el servidor, sin intervención:

1. **Aísla el equipo**: solo puede hablar con el servidor.
2. Guarda una **copia forense** del estado infectado en un almacén de **cuarentena** separado.
3. **Restaura la última copia sana** anterior al ataque y borra lo que dejó el ataque.
4. Muestra un **aviso al usuario** del equipo («se ha restaurado una copia… contacte con seguridad»).
5. Abre un **incidente** en el panel y avisa por correo/Telegram.

Desde el panel (menú **Incidentes**) se puede: abrir la **sala de análisis** (la copia forense dentro de un
contenedor sin red, de solo lectura y sin permisos: tipos reales, huellas SHA-256, hexadecimal, texto, YARA y
terminal de pruebas), **borrar la amenaza** del equipo, **descargar el paquete forense** (.7z cifrado),
**liberar el equipo** y, al cerrar el caso, **destruir la copia forense**.

Todo ocurre dentro de las máquinas virtuales: el ataque de las pruebas es **simulado e inofensivo**
(archivos de datos aleatorios y una nota de texto). Si descargas el paquete forense en Windows, **no lo
descomprimas** fuera de una máquina virtual de análisis.

- Demo en directo: abre el panel y haz doble clic en `DEMO_ATAQUE.bat`.

## Otros

- Entrar a una VM: `vagrant ssh cerebro`
- Copiar cambios del proyecto al cerebro: `.\copiar_proyecto.ps1`; reinstalar: `.\desplegar_zerotouch.ps1 -Reinstalar`

## Si algo falla

- `.\capturar_logs.ps1` → `reportes\logs_<fecha>.txt` (docker, servicios, agentes).
- El log completo de la ejecución está en `reportes\ejecucion_<fecha>.log`.
- macOS no se puede virtualizar en VirtualBox sobre Windows (licencia de Apple).
