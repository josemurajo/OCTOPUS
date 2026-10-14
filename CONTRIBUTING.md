# Colaborar con OCTOPUS

Las mejoras, arreglos e ideas son bienvenidos.

## Antes de empezar
- Para un cambio grande, abre primero una incidencia y lo hablamos.
- Los fallos de seguridad **no** van en incidencias públicas: ver [SECURITY.md](SECURITY.md).
- Escribe pensando en quien no sabe informática: mensajes claros, en castellano, que digan qué hacer.

## Las pruebas
Cada cambio que se sube pasa solo las pruebas de GitHub (agente en Linux, Windows y Mac, servidor nativo en Windows
y en Mac, modo consola, limite de peticiones, almacén externo y sintaxis de todos los scripts). Si algo falla, no se
acepta.

## Derechos sobre lo que aportas (DCO)
Al aportar código aceptas que se publique con la licencia del proyecto (**AGPL-3.0 o posterior**) y certificas el
[Developer Certificate of Origin 1.1](https://developercertificate.org/): que el código es tuyo, o que tienes derecho a
aportarlo con esta licencia.

Se indica firmando cada commit:

```
git commit -s -m "Lo que cambia"
```

Eso añade la línea `Signed-off-by: Tu Nombre <tu@correo>`. No aportes código copiado de otros programas cuya licencia
no lo permita, ni claves, contraseñas o datos de personas reales.
