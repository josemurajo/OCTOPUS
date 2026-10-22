# Publicar una versión de OCTOPUS (lo que hace José)

**¿Para qué firmas?** Los servidores de las empresas se actualizan solos y **solo instalan lo que lleva tu firma**.
Si alguien entrara en tu cuenta de GitHub, no podría colar nada en los servidores de tus clientes: le faltaría tu
firma, y esa solo se puede hacer en tu PC.

## Cada vez que Claude te avise (1 minuto)

1. Doble clic en **`FIRMAR_VERSION.bat`** (guárdalo en el escritorio; está en la carpeta `herramientas`).
2. Escribe la **frase de paso** de tu clave (no se ve mientras escribes) y pulsa Enter.
3. Sale «LISTO» y la firma queda copiada. **Pégala en el chat de Claude (Ctrl+V)** y envía.

Ya está. Claude la sube y GitHub hace el resto: comprueba la firma, pasa la versión a los servidores (rama
`publicado`), la crea en *Releases* y publica la imagen para los NAS.

La firma no es secreta, se puede pegar sin problema. Lo secreto es tu clave (`~/.ssh/octopus_publicar`) con su frase
de paso. **No la compartas con nadie**, tampoco con Claude. Guarda una copia en un USB junto con la frase de paso:
si la pierdes, los servidores no podrían actualizarse solos.

## Si sale un mensaje

- **«no hay ninguna version preparada»:** todavía no hay nada que firmar. Espera al aviso de Claude.
- **«ya esta firmada»:** no hay que hacer nada.
- **«la clave publica del proyecto NO es la tuya»:** no sigas y avisa a Claude.
- **«falta ssh-keygen»:** instala Git for Windows (gratis, git-scm.com).

## A mano (sin el .bat)

En la carpeta del proyecto descargado de GitHub (*Code → Download ZIP*), abre Git Bash y ejecuta
`bash herramientas/firmar_version.sh`. Luego sube `MANIFIESTO.sig` con *Add file → Upload files*.
