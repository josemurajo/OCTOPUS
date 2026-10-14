# OCTOPUS y la protección de datos (RGPD)

> Texto orientativo, **no es asesoramiento legal**. Los datos entre [corchetes] los rellenan los autores del
> proyecto. OCTOPUS es software libre y gratuito (AGPL-3.0): hay dos partes, cómo trata los datos el programa en la
> empresa que lo instala, y qué pasa con lo poco que llega a los autores (solo si alguien pulsa «Enviar sugerencia o
> problema»).

## A. Cómo trata OCTOPUS los datos (para la empresa que lo instala)

**Dónde están los datos.** OCTOPUS se instala en un servidor del propio cliente. Las copias de seguridad, la
configuración, los registros y los datos de monitorización **se quedan en ese servidor** (y, si el cliente lo
configura, en su almacén externo). Los autores de OCTOPUS **no tienen acceso** a ellos.
La empresa que lo instala es la responsable de esos datos: ver [Qué tiene que hacer la empresa](LEEME.md).

**Cifrado.** Las copias se cifran en cada equipo antes de salir (AES-256, con restic). Sin el kit de recuperación del
cliente nadie puede leerlas, tampoco los autores.

**Qué datos maneja OCTOPUS en el servidor del cliente**
- Copias de los archivos que el cliente elige proteger (pueden contener datos personales: el cliente es el
  **responsable del tratamiento** de esos datos).
- Usuarios del panel: nombre de usuario, correo, contraseña (solo su huella bcrypt), papel, códigos de la doble
  autenticación (cifrados), accesos y acciones (registro de actividad firmado).
- Monitorización (viene apagada; solo en los equipos donde se active): uso del equipo, inventario y estado de
  seguridad; los programas abiertos y el usuario con sesión solo si se eligen en Ajustes → Funciones (el usuario viene
  apagado). No graba la pantalla ni lo que se escribe. **Si se monitorizan equipos de trabajadores, la empresa debe
  informarles antes** ([nota para los trabajadores](NOTA_TRABAJADORES.md)); el panel pide confirmarlo al activarla.
- Conservación: las copias se borran solas según la política elegida en Ajustes; el historial de monitorización, a los
  días elegidos (90 por defecto); al desinstalar la monitorización de un equipo se borra su historial; los registros
  de actividad se conservan para poder auditar.

**Qué sale del servidor del cliente**
- Avisos por correo o Telegram a las direcciones que el cliente configure.
- Comprobación de versiones nuevas en GitHub (solo se descarga el número de versión y, si se actualiza, el programa
  firmado; GitHub ve la IP del servidor como en cualquier descarga).
- **Solo si el cliente pulsa «Enviar sugerencia o problema»**: el texto que escriba, su correo de contacto si lo pone,
  un identificador anónimo del servidor y, si marca la casilla, un diagnóstico **sin contraseñas, sin claves y sin
  nombres de archivos** (los equipos aparecen como equipo-1, equipo-2…). Va al buzón de los autores.
- Si la empresa no quiere que salga nada: `SOPORTE_BUZON_URL=no` en los ajustes del servidor.

## B. Lo que llega a los autores (botón «Enviar sugerencia o problema»)

**Responsable:** [nombre de quien mantiene el proyecto], [correo de privacidad].
**Qué datos:** los que el cliente envía al pulsar «Enviar sugerencia o problema» (texto, correo de contacto si lo da,
identificador anónimo del servidor y, si lo marca, el diagnóstico anónimo).
**Para qué:** responder y resolver la sugerencia o el problema, y mejorar el Programa.
**Base legal:** el consentimiento de quien lo envía (pulsar el botón es voluntario) y el interés legítimo en mejorar el programa.
**Cuánto tiempo:** lo necesario para resolverlo y, como mucho, [24 meses]; después se borra.
**Quién más lo ve:** los proveedores técnicos del buzón (Cloudflare y Telegram), con sus garantías para
transferencias internacionales. [Revisar con asesor: cláusulas contractuales tipo / marco UE-EE. UU.]
**Derechos:** acceso, rectificación, supresión, oposición, limitación y portabilidad escribiendo a [correo]. Si no se
atiende, reclamación ante la Agencia Española de Protección de Datos (www.aepd.es).

## C. Si alguien instala o mantiene OCTOPUS para otra empresa
Los autores no entran en los servidores de nadie. Pero si un técnico o una empresa de informática instala o mantiene
OCTOPUS **para un cliente** y puede ver sus datos, es su **encargado del tratamiento** y necesita un contrato con él
(art. 28 RGPD). Eso es entre ellos; el programa no cambia.
