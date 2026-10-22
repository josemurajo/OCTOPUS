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
