# Publicar una versión de OCTOPUS (lo que hace José)

Una versión solo llega a los servidores de las empresas si **tú** la firmas con tu clave. Tardas unos 5 minutos y no
hace falta saber programar. La primera vez, haz también el paso 0.

## 0. Solo la primera vez

- Necesitas **Git Bash**. En Windows se instala con «Git for Windows» (gratis, git-scm.com).
- Tu clave de publicación ya existe (`~/.ssh/octopus_publicar`), porque la creaste con este mismo script.
  - **No la compartas con nadie**, tampoco con Claude.
  - Guarda una copia en un USB que tengas a buen recaudo, junto con su frase de paso. Si la pierdes, los servidores
    ya instalados no podrán actualizarse solos y habría que actualizarlos a mano.

## 1. Descarga la versión preparada

1. Entra en https://github.com/josemurajo/OCTOPUS.
2. Pulsa el botón verde **Code** y luego **Download ZIP**.
3. Descomprime el ZIP (por ejemplo, en el Escritorio).

## 2. Fírmala

1. Haz clic derecho dentro de la carpeta descomprimida (la que tiene `VERSION`, `MANIFIESTO`, `lib`…) y elige
   **Open Git Bash here**.
2. Escribe esto y pulsa Enter:

   ```bash
   bash herramientas/firmar_version.sh
   ```

3. Te pide la **frase de paso** de tu clave. Escríbela (no se ve mientras escribes) y pulsa Enter.
4. Debe salir «Versión X firmada». Junto al `MANIFIESTO` aparece un archivo nuevo: **`MANIFIESTO.sig`**.

## 3. Súbela

1. En la página del proyecto en GitHub, pulsa **Add file** y luego **Upload files**.
2. Arrastra el archivo **`MANIFIESTO.sig`** (solo ese) y pulsa **Commit changes**.

Ya está. Se encarga GitHub: comprueba tu firma y cada archivo, la pasa a la rama `publicado`, la crea en
*Releases* y publica la imagen para los NAS. Los servidores la instalarán solos esa noche, o cuando alguien pulse
«Actualizar» en el panel.

## Si algo sale mal

- **«No hay MANIFIESTO que firmar»:** la versión todavía no está preparada. Pídeselo a Claude.
- **«install/firma_publicacion.pub no es tu clave pública actual»:** estás firmando con otra clave o en otra
  carpeta. No sigas y avisa a Claude.
- **En la pestaña *Actions* sale en rojo «Publicar versión firmada»:** no se ha publicado nada y los servidores
  siguen como estaban. Lo normal es que algo cambiara entre preparar la versión y firmarla. Claude la vuelve a
  preparar y tú la firmas otra vez.
