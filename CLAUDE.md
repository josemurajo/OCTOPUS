# Notas para Claude (y para cualquiera que mantenga OCTOPUS)

Léelo antes de tocar nada. Son las reglas del proyecto que José ha ido dejando claras.

## Quién y cómo
- Autor: **José Murillo Rajo**. Software libre AGPL-3.0, gratis. Repositorio público: github.com/josemurajo/OCTOPUS.
- José escribe en español y quiere respuestas **cortas, en español y «para tontos»**. El programa también: lo que
  ve el usuario tiene que entenderlo cualquiera. Eso es lo que hace distinto a OCTOPUS.
- La aplicación es **modular**: cada cosa nueva va como función en `lib/funciones.py`, que se enciende y se apaga
  desde la web (Ajustes → Funciones). Lo que no se ha probado en algo real va con `en_pruebas: True`.

## Reglas que no se rompen
- **Nada de pago.** Solo servicios y herramientas gratis.
- **Nunca pedir ni manejar las contraseñas de José.** Su clave privada de publicación y el token del bot de
  Telegram no se comparten nunca, tampoco con Claude.
- **Ningún secreto en el repositorio** (es público). Revisa el diff buscando claves antes de cada push.
- **Preguntar antes de borrar** archivos o destruir máquinas.
- **La IA local la decide José**: no tocar nada de eso hasta que él lo diga.
- Pruebas de seguridad, solo contra el servidor de pruebas propio.
- No copiar material con derechos de autor.

## Antes de construir algo
- **Mira si ya existe**: la lista de `lib/funciones.py`, `git log --oneline`, `ls agentes lib templates`. Ya pasó
  una vez que se hizo dos veces lo mismo (las copias de bases de datos).
- Lee `MAPA_DEL_CODIGO.md` (dónde está cada cosa) y `PENDIENTES.md` (qué falta y qué necesita José).

## Pruebas
- Cada push pasa `.github/workflows/pruebas.yml` en Linux, Windows y Mac reales. No des nada por terminado con
  la CI en rojo.
- Lo nuevo lleva su prueba en `tests/ci/` y su paso en la CI.
- Lo nuevo que pueda fallar lleva su aviso en `lib/avisos.py` (qué pasa, `causas`, `pasos`) y después
  `python3 herramientas/generar_soluciones.py` (escribe SOLUCIONES.md; la CI comprueba que está al día).
- Y si se puede arreglar, su aviso lleva `accion` + `boton` y su regla en `lib/autoarreglo.py` (POLITICA): sin
  riesgo → `auto: True` (lo arregla solo y avisa «lo he arreglado»); con riesgo (borra, reinicia, toca la seguridad
  del equipo) → `riesgo` y lo hace solo al pulsar «Solucionar» con permiso; si no se puede arreglar desde OCTOPUS,
  `pasos` claros. El arreglo va en `_ejecutar_arreglo` (lib/admin_panel.py). La prueba de prueba_casa.py lo exige.
- Antes de preparar una versión: README.md y CHANGELOG.md al día con lo nuevo.
- Comprobaciones rápidas sin equipos:
  - `python tests/ci/prueba_produccion.py`;
  - `bash tests/ci/prueba_publicar.sh`.

## Publicar una versión
- **Los servidores solo descargan la rama `publicado`.** `main` es el taller. Una versión pasa a `publicado`
  automáticamente cuando José sube su firma (`.github/workflows/publicar.yml`). Guía para José:
  `PUBLICAR_VERSION.md`.
- Para preparar una: añade la sección en `CHANGELOG.md`, haz commit y ejecuta
  `bash herramientas/preparar_version.sh X.Y.Z`. Después, push y avisa a José.
- José firma con `herramientas/FIRMAR_VERSION.bat` y **pega la firma en el chat** (empieza por
  `-----BEGIN SSH SIGNATURE-----`). Guárdala tal cual en `MANIFIESTO.sig`, con un salto de línea al final, y
  comprueba con `bash herramientas/comprobar_publicacion.sh` después de hacer commit y antes del push. Si falla, no
  la subas.
- **Entre preparar y que José firme, no se toca `main`.** Cualquier cambio rompe la firma. Si hace falta cambiar
  algo, se vuelve a preparar.

## Datos de José
- Su nombre y sus correos públicos están **solo** en `DATOS_DEL_AUTOR.txt`. El panel los lee de ahí. Si hace falta
  un dato suyo nuevo, añádelo a ese archivo; no lo repartas por el código.
