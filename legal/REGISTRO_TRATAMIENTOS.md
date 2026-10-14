# Registro de actividades de tratamiento — plantilla para OCTOPUS

> Para añadir al registro de la empresa (art. 30 RGPD). Rellena los [corchetes]. No es asesoramiento legal.

## 1. Copias de seguridad de los equipos

| Apartado | Contenido |
|---|---|
| Responsable | [Empresa], [NIF], [contacto]; Delegado de protección de datos: [si lo hay] |
| Finalidad | Copias de seguridad para recuperar la información ante averías, pérdidas o ataques |
| Base legal | Interés legítimo y obligación de seguridad (art. 6.1.f y 32 RGPD) |
| Personas | Trabajadores, clientes, proveedores y cualquier persona cuyos datos estén en las carpetas copiadas |
| Datos | Los que haya en los archivos copiados (pueden incluir categorías especiales si la empresa las trata) |
| Destinatarios | Ninguno. Si hay almacén externo: [proveedor y país] |
| Transferencias fuera de la UE | [Ninguna / proveedor del almacén externo y garantía] |
| Conservación | [Política de copias de Ajustes, por ejemplo: 30 diarias, 12 mensuales] |
| Medidas de seguridad | Cifrado AES-256 en el equipo antes de enviar; almacén que no permite borrar desde los equipos; acceso al panel con doble autenticación; registro de actividad firmado; prueba semanal de recuperación |

## 2. Monitorización técnica de los equipos (solo si se activa)

| Apartado | Contenido |
|---|---|
| Finalidad | Mantenimiento y seguridad de los equipos (no control de la actividad laboral) |
| Base legal | Interés legítimo (art. 6.1.f RGPD), art. 87 LOPDGDD, 20.3 Estatuto de los Trabajadores; información previa a los trabajadores |
| Personas | Trabajadores que usan los equipos monitorizados |
| Datos | Uso del procesador, memoria, discos, red, temperatura y batería; inventario del equipo; [programas abiertos — si está activado]; [usuario con sesión — si está activado] |
| Destinatarios | Ninguno |
| Conservación | Historial: [días configurados en Ajustes → Funciones → Monitorización] |
| Medidas de seguridad | Las mismas que el punto 1 |

## 3. Usuarios del panel de OCTOPUS

| Apartado | Contenido |
|---|---|
| Finalidad | Gestión del acceso al panel y registro de lo que se hace (seguridad y auditoría) |
| Personas | Personas con acceso al panel |
| Datos | Nombre de usuario, correo, huella de la contraseña (bcrypt), código de la doble autenticación (cifrado), accesos e IP, acciones |
| Conservación | Mientras tenga acceso; el registro de actividad, [plazo de auditoría de la empresa] |
