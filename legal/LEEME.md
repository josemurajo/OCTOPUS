# Qué tiene que hacer la empresa que instala OCTOPUS

> Guía orientativa, **no es asesoramiento legal**. Para un caso concreto, consulta con un asesor de protección de
> datos. Los textos entre [corchetes] los rellena la empresa.

OCTOPUS es **software libre y gratuito** (AGPL-3.0). Se instala en un servidor **de la propia empresa** y todo se
queda ahí: copias, ajustes, registros y monitorización. Los autores de OCTOPUS **no reciben ni ven** esos datos.

Por eso la empresa que lo instala es la **responsable del tratamiento** de los datos personales que haya en las
copias y en la monitorización (RGPD y Ley Orgánica 3/2018, LOPDGDD). Lo que le toca:

1. **Apuntarlo en su registro de actividades de tratamiento.** Plantilla: [Registro de actividades](REGISTRO_TRATAMIENTOS.md).
2. **Si activa la monitorización en equipos que usan trabajadores:**
   - informarles **antes**, por escrito ([Nota para los trabajadores](NOTA_TRABAJADORES.md)), y a sus representantes si
     los hay (art. 87 y 64 del Estatuto de los Trabajadores, art. 87 LOPDGDD);
   - usarla solo para **el mantenimiento y la seguridad de los equipos**, nunca para vigilar o medir el trabajo de nadie;
   - recoger solo lo necesario: en **Ajustes → Funciones → Monitorización** se puede dejar de guardar los programas
     abiertos y quién tiene la sesión iniciada (esto último viene apagado), y cuántos días se guarda el historial;
   - valorar si hace falta una evaluación de impacto ([plantilla medio rellena](EVALUACION_IMPACTO_MONITORIZACION.md)).
   El panel no deja activar la monitorización en un equipo sin confirmar que se ha informado a quien lo usa, y lo
   apunta en el registro de actividad.
3. **Proteger el acceso al panel:** doble autenticación con el móvil (viene encendida para administradores),
   contraseñas propias para cada persona y el kit de recuperación guardado fuera del servidor.
4. **Atender los derechos de las personas** (acceso, rectificación, supresión...). Las copias se borran solas según
   la política de Ajustes; si alguien pide que se borren sus datos, lo normal es que salgan de las copias cuando estas
   caduquen, sin restaurarlos mientras tanto. Explícalo en tu política de privacidad.
5. **Si hay un incidente de seguridad con datos personales** (por ejemplo, un ransomware), valorar si hay que avisar
   a la Agencia Española de Protección de Datos en **72 horas** (art. 33 RGPD). El informe del incidente que genera
   OCTOPUS sirve de punto de partida.
6. **Avisos por correo o Telegram, y «Enviar sugerencia o problema»:** son lo único que sale del servidor, y solo si
   se configuran. Telegram y los proveedores de correo pueden estar fuera de la UE: tenlo en cuenta al elegirlos.

Más información: [Protección de datos](PRIVACIDAD_BORRADOR.md) · Agencia Española de Protección de Datos: https://www.aepd.es
