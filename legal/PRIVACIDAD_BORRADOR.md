# OCTOPUS y la protección de datos (RGPD) — BORRADOR

> **Borrador para revisar con un asesor antes de vender.** No es asesoramiento legal. Los datos entre [corchetes]
> hay que rellenarlos. Hay dos textos: uno para explicar al cliente cómo trata OCTOPUS los datos, y una cláusula para
> el soporte (lo único que llega al Titular).

## A. Cómo trata OCTOPUS los datos (para el cliente)

**Dónde están los datos.** OCTOPUS se instala en un servidor del propio cliente. Las copias de seguridad, la
configuración, los registros y los datos de monitorización **se quedan en ese servidor** (y, si el cliente lo
configura, en su almacén externo). El Titular **no tiene acceso** a ellos.

**Cifrado.** Las copias se cifran en cada equipo antes de salir (AES-256, con restic). Sin el kit de recuperación del
cliente nadie puede leerlas, tampoco el Titular.

**Qué datos maneja OCTOPUS en el servidor del cliente**
- Copias de los archivos que el cliente elige proteger (pueden contener datos personales: el cliente es el
  **responsable del tratamiento** de esos datos).
- Usuarios del panel: nombre de usuario, correo, contraseña (solo su huella bcrypt), papel, códigos de la doble
  autenticación (cifrados), accesos y acciones (registro de actividad firmado).
- Monitorización (solo en los equipos donde se active): uso del equipo, programas en ejecución, usuario con sesión
  iniciada, inventario y estado de seguridad. **Si se monitorizan equipos de trabajadores, el cliente debe
  informarles** antes (art. 87 LOPDGDD y el deber de información del RGPD) y usarlo solo para el mantenimiento y la
  seguridad de los equipos, no para controlar su actividad. [Revisar con asesor.]
- Conservación: las copias se borran solas según la política elegida en Ajustes; el historial de monitorización, a los
  90 días; los registros de actividad se conservan para poder auditar.

**Qué sale del servidor del cliente**
- Avisos por correo o Telegram a las direcciones que el cliente configure.
- Comprobación de versiones nuevas (solo se descarga el número de versión y, si se actualiza, el programa firmado).
- **Solo si el cliente pulsa «Enviar sugerencia o problema»**: el texto que escriba, su correo de contacto si lo pone,
  un identificador anónimo del servidor y, si marca la casilla, un diagnóstico **sin contraseñas, sin claves y sin
  nombres de archivos** (los equipos aparecen como equipo-1, equipo-2…). Va al buzón de soporte del Titular.
- Si la empresa no quiere que salga nada: `SOPORTE_BUZON_URL=no` en los ajustes del servidor.

## B. Cláusula de soporte (lo que trata el Titular)

**Responsable:** [Nombre o empresa de José], [NIF], [dirección], [correo de privacidad].
**Qué datos:** los que el cliente envía al pulsar «Enviar sugerencia o problema» (texto, correo de contacto si lo da,
identificador anónimo del servidor y, si lo marca, el diagnóstico anónimo).
**Para qué:** responder y resolver la sugerencia o el problema, y mejorar el Programa.
**Base legal:** el interés legítimo en dar soporte y la ejecución del contrato de licencia.
**Cuánto tiempo:** lo necesario para resolverlo y, como mucho, [24 meses]; después se borra.
**Quién más lo ve:** los proveedores técnicos del buzón (Cloudflare y Telegram), con sus garantías para
transferencias internacionales. [Revisar con asesor: cláusulas contractuales tipo / marco UE-EE. UU.]
**Derechos:** acceso, rectificación, supresión, oposición, limitación y portabilidad escribiendo a [correo]. Si no se
atiende, reclamación ante la Agencia Española de Protección de Datos (www.aepd.es).

## C. ¿Hace falta contrato de encargado del tratamiento?
Si el Titular **no accede** a los datos del cliente (instalación en el servidor del cliente y soporte solo con el
diagnóstico anónimo), normalmente no es encargado del tratamiento de las copias. **Si alguna vez entra en el servidor
de un cliente** (soporte a distancia, instalación hecha por el Titular) o gestiona el servicio por él, sí hace falta un
contrato de encargado (art. 28 RGPD). [Revisar con asesor y preparar el modelo.]
