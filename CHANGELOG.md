# Cambios de OCTOPUS Zero-Touch

Cada versión publicada va firmada por José Murillo Rajo. Los servidores se actualizan solos (o desde el panel) y solo
instalan versiones con esa firma. Lo más nuevo, arriba.

## 3.0.0 - 2026-10-22 (primera versión para empresas)

**Copias**
- Ordenadores Windows, Linux y Mac con un agente que se instala solo; copia completa del equipo opcional.
- Máquinas virtuales de Hyper-V, KVM/libvirt y Proxmox, completas y sin pararlas. Viene «en pruebas».
- Bases de datos SQL Server, MySQL/MariaDB y PostgreSQL, cada día, cada 4 horas o cada hora. Se pueden recuperar
  como base nueva o descargar. Probado con los motores de verdad.
- Correo y archivos de Microsoft 365 (Exchange y OneDrive) y de Google Workspace (Gmail y Drive), con asistente
  paso a paso. Viene «en pruebas».
- Todo cifrado antes de salir del equipo; almacén con bloqueo contra borrado y copia externa con bloqueo por tiempo.

**Para casa o para empresa** (lo primero que pregunta)
- **Modo casa:** OCTOPUS en tu propio ordenador.
  - Se protege con un clic.
  - Las copias van a un disco USB u otro disco, con aviso si es el mismo disco y aviso de «conecta el disco».
  - El panel es más sencillo.
- **Modo discreto** (para todos): si la persona juega o usa el equipo a fondo, la copia se pone sola en «no
  molestar» y va casi parada; cuando lo deja, vuelve a toda velocidad. Sin ventanas y sin reinicios. En casa, el
  mantenimiento de la noche tampoco se nota y no actualiza mientras se usa el ordenador.
- **Icono «OCTOPUS te protege»** junto al reloj de Windows (encendido en casa): verde si todo va bien. Al pasar
  el ratón dice cuándo fue la última copia. Solo avisa si algo va mal.
- **Empresa:** OCTOPUS en una máquina aparte siempre encendida, con un icono en el escritorio del PC desde el que se
  maneja.
- **Destinos de copia:** un equipo puede copiar directo a otro disco, una carpeta de red, un NAS o un S3, «en lugar
  de» o «además» del servidor. OCTOPUS manda, vigila y avisa.

**Fácil de usar**
- Panel web en español, en modo básico (lo importante) o experto (todo).
- Avisos que explican qué pasa y se arreglan solos.
- Asistente para recuperar archivos.
- Funciones y módulos que se encienden y apagan desde la web.
- Modo multiempresa para técnicos que llevan varios clientes.
- Instalación en Linux, Windows o Mac.
- Paquetes fáciles para NAS Synology y QNAP, Unraid, Portainer, TrueNAS y Proxmox, con la imagen lista en GitHub.
- Buscar los equipos de la red y darlos de alta en grupo.

**Seguridad**
- Doble autenticación con el móvil.
- Bloqueo de quien prueba contraseñas.
- Aviso de acceso desde un navegador nuevo.
- Usuarios con papeles.
- Entrada con Active Directory/LDAP, OIDC o RADIUS (en pruebas).
- Sala aislada para analizar incidentes de ransomware.
- Kit de recuperación del servidor.
- Actualizaciones a distancia solo con versiones firmadas.

**Monitorización** (opcional y desactivada de serie): estado de los equipos, avisos y la nota informativa para los
trabajadores.

**Legal**: software libre AGPL-3.0, página «Legal y privacidad» y plantillas de protección de datos para la empresa.

Arreglado en esta versión: en una instalación nueva con doble autenticación obligatoria, el primer acceso se quedaba
dando vueltas entre «cambia la contraseña» y «activa el móvil».
