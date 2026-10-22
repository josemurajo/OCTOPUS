# Probar OCTOPUS en tu PC sin dejar rastro (Windows 10/11 Pro)

Se usa el **Espacio aislado de Windows** (Windows Sandbox), que viene con Windows. Es un Windows desechable dentro
del tuyo:

- no ve tus archivos;
- al cerrarlo, Windows borra todo lo que pasó dentro.

## Una sola vez: activarlo (2 minutos y un reinicio)

1. Pulsa la tecla Windows, escribe **«características de Windows»** y abre **«Activar o desactivar las
   características de Windows»**.
2. Marca **«Espacio aislado de Windows»**, pulsa *Aceptar* y reinicia cuando te lo pida.

Si no aparece o da error, falta la virtualización en la BIOS (suele llamarse «Intel VT-x» o «AMD-V/SVM»).

## Probar

1. Doble clic en **`PROBAR_OCTOPUS.wsb`**.
2. Se abre una ventana con otro Windows. Dentro, OCTOPUS se descarga, se instala y se prueba solo en unos 10
   minutos.
3. Al final verás «TODO CORRECTO» (o lo que haya fallado: haz una foto y pásamela). También se abre el panel con
   el usuario y la contraseña, para que lo mires a tu aire.
4. Cuando termines, **cierra la ventana del Espacio aislado**. Windows avisa de que se perderá todo: dile que sí.

## Qué queda en tu PC

Nada de OCTOPUS: ni programas, ni tareas, ni carpetas, ni ajustes. Solo quedan dos cosas:

- el archivo `PROBAR_OCTOPUS.wsb`, que puedes borrar;
- la función «Espacio aislado de Windows» activada. Si quieres quitarla, desmárcala en el mismo sitio donde la
  activaste.
