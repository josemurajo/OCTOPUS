# Prueba en equipos de verdad (1 hora)

En GitHub, OCTOPUS se prueba solo en cada cambio, pero en máquinas de prueba. Esta guía es para probarlo una vez en
equipos de verdad de la oficina antes de dárselo a una empresa. Apunta lo que no salga como dice aquí y pásamelo con
una foto de la pantalla.

**Necesitas:**
- el servidor de OCTOPUS (un PC con Linux, Windows o Mac, un NAS o un Proxmox; ver [README](README.md) e
  [INSTALAR_EN_NAS.md](INSTALAR_EN_NAS.md));
- un **PC con Windows** y, si puedes, un **Mac**;
- todos en la misma red.

## 1. El servidor (10 min)

- [ ] Instálalo y entra en el panel con la contraseña inicial.
- [ ] Te obliga a poner una contraseña nueva y después a activar el móvil (doble autenticación).
- [ ] La pantalla **Inicio** sale en verde o en amarillo, nunca en rojo, y dice qué falta.
- [ ] En **Ajustes**, descarga el **kit de recuperación** y guárdalo fuera del servidor.

## 2. El PC con Windows (15 min)

- [ ] En el panel: **Equipos → Añadir equipo → Windows**. Descarga el instalador.
- [ ] Llévalo al PC (USB o correo) y ábrelo con doble clic. Windows pide permiso una vez.
- [ ] En 1 o 2 minutos el equipo sale **conectado** en el panel.
- [ ] Crea una carpeta `C:\Prueba OCTOPUS` con unos cuantos archivos (un Word, una foto, un PDF).
- [ ] En la ficha del equipo, añade esa carpeta y pulsa **Hacer copia ahora**. Termina sin errores.

## 3. Recuperar (10 min)

- [ ] Borra un archivo de `C:\Prueba OCTOPUS` y vacía la papelera.
- [ ] En el panel: **Recuperar archivos**. Busca el archivo por su nombre, elige «a su sitio» y recupéralo.
- [ ] El archivo vuelve a su carpeta y se abre bien.
- [ ] Prueba también a recuperar la carpeta entera en otro sitio.

## 4. Si atacan el equipo (10 min; simulado, no hace daño)

OCTOPUS deja en cada carpeta copiada un archivo trampa oculto, `~octopus_no_tocar.docx`. Si cambia, entiende que hay
un ransomware.

- [ ] En el Explorador de Windows, activa **Vista → Mostrar → Elementos ocultos** y entra en `C:\Prueba OCTOPUS`.
- [ ] Abre `~octopus_no_tocar.docx` con el **Bloc de notas**, escribe cualquier cosa y guarda.
- [ ] En menos de un minuto, el panel avisa en rojo y explica qué ha pasado.
- [ ] El PC se queda **aislado de la red** (es lo que haría con un ataque de verdad): no hay Internet ni carpetas
      compartidas, pero sigue hablando con OCTOPUS.
- [ ] En el panel, abre el incidente y pulsa **«Liberar equipo y cerrar incidente»**. El PC recupera la red y vuelve
      a verde.

## 5. El Mac (15 min, si tienes)

- [ ] **Equipos → Añadir equipo → Mac**, y elige «Desde aquí». Pon la IP del Mac, el usuario y la contraseña. La
      contraseña no se guarda.
  - Antes, en el Mac: **Ajustes del Sistema → General → Compartir → Sesión remota** activado.
- [ ] Repite los pasos 2 (copia) y 3 (recuperar) con una carpeta del Mac.
- [ ] Si macOS pide permiso de **Acceso total al disco** para OCTOPUS, dáselo y comprueba que la copia sigue bien.

## 6. Al día siguiente (5 min)

- [ ] Las copias se han hecho solas por la noche (ficha de cada equipo → última copia).
- [ ] **Inicio** sigue en verde.
- [ ] Si configuraste correo o Telegram, te ha llegado el resumen o los avisos.

Si todo está marcado, OCTOPUS está listo para esa empresa. 🎉
