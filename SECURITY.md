# Avisar de un fallo de seguridad

Gracias por ayudar a que OCTOPUS sea seguro.

## Cómo avisar

**No abras una incidencia pública** con los detalles de un fallo de seguridad: cualquiera podría aprovecharlo antes
de que esté arreglado.

Usa el aviso privado de GitHub: pestaña **Security → Report a vulnerability** de este repositorio. Solo lo ven los
responsables del proyecto. Otra forma de avisar en privado: [correo de seguridad].

Cuéntanos, si puedes:
- qué versión (archivo `VERSION`) y en qué sistema (Linux, Windows, Mac; servidor o agente);
- qué se puede hacer con el fallo y cómo reproducirlo;
- si sabes que alguien ya lo está aprovechando.

## Qué haremos

| Cuándo | Qué |
|---|---|
| 3 días laborables | Te confirmamos que lo hemos recibido |
| 10 días | Te decimos si lo confirmamos y cómo de grave es |
| Lo antes posible | Arreglo firmado, publicado como versión nueva (los servidores se actualizan solos) |
| Con el arreglo | Aviso de seguridad público explicando el fallo, a quién afecta y qué hacer; te citamos si quieres |

Si el fallo **ya se está aprovechando**, es lo primero: se publica el arreglo, o al menos cómo protegerse, en cuanto
sea posible.

## Qué versiones reciben arreglos

La última versión publicada. Los servidores de OCTOPUS se actualizan solos con versiones firmadas, así que lo normal
es estar siempre en la última.

## Qué entra

Todo lo que hay en este repositorio: el panel, el servidor, los agentes, los instaladores y los scripts de gestión.
Los fallos de los componentes de terceros (restic, Flask...) avísalos a su proyecto; si afectan a OCTOPUS, dínoslo
también.

Prueba solo en equipos que sean tuyos o que tengas permiso para probar.
