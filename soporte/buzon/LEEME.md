# Buzón de soporte de OCTOPUS (gratis, unos 15 minutos)

Cuando alguien pulsa **«Enviar sugerencia o problema»** en el panel de cualquier servidor OCTOPUS, el mensaje va a
este buzón, y el buzón te lo manda a **tu Telegram**. Así:

- el código del bot de Telegram **no está** en los servidores de los clientes ni en GitHub (solo en tu cuenta de
  Cloudflare, como secreto);
- funciona igual con 1 cliente que con 1000;
- es gratis (plan gratuito de Cloudflare Workers: 100 000 mensajes al día).

Nunca le pases a nadie (tampoco a Claude) el token del bot: se pega directamente en Cloudflare.

## 1. Crear el bot de Telegram (3 minutos)

1. En Telegram, abre el chat con **@BotFather** (el oficial, con la marca azul).
2. Escribe `/newbot`, ponle un nombre (por ejemplo `OCTOPUS Soporte`) y un usuario que acabe en `bot`
   (por ejemplo `octopus_soporte_jose_bot`).
3. BotFather te da un **token** (algo como `123456789:AAE...`). Guárdalo en tu gestor de contraseñas.
4. Abre el chat con tu bot nuevo y escríbele cualquier cosa (por ejemplo `hola`). Esto es necesario para que te
   pueda escribir.
5. Averigua tu número de chat: en el navegador abre
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` (cambia `<TU_TOKEN>` por el token) y busca
   `"chat":{"id":` — ese número (por ejemplo `987654321`) es tu **chat**.

## 2. Publicar el buzón en Cloudflare (10 minutos, desde la web)

1. Créate una cuenta gratis en <https://dash.cloudflare.com/sign-up> (si no tienes).
2. En el menú: **Compute (Workers) → Workers & Pages → Create → Create Worker** (plantilla «Hello World»).
   Ponle de nombre `octopus-buzon` y pulsa **Deploy**.
3. Pulsa **Edit code**, borra todo lo que hay, pega el contenido de `worker.js` (este mismo directorio) y pulsa
   **Deploy**.
4. Ve a **Settings → Variables and Secrets → Add**:
   - Tipo **Secret**, nombre `TELEGRAM_TOKEN`, valor: el token del bot.
   - Tipo **Secret**, nombre `TELEGRAM_CHAT`, valor: tu número de chat.
   Pulsa **Deploy** otra vez.
5. Copia la dirección del worker (algo como `https://octopus-buzon.TU-USUARIO.workers.dev`) y ábrela en el
   navegador: tiene que salir `{"ok":true,"buzon":"OCTOPUS","telegram":true}`.

## 3. Decirle a OCTOPUS dónde está el buzón

La dirección del buzón **no es secreta** (sin el token no sirve para nada más que enviarte mensajes, y el buzón
limita cuántos puede mandar cada uno). Hay dos formas:

- **Para todos los servidores** (lo normal): pon la dirección en `lib/sugerencias.py`, en
  `BUZON_POR_DEFECTO = "https://octopus-buzon.TU-USUARIO.workers.dev"`, y publica la versión. (Claude lo puede
  hacer: basta con darle la dirección.)
- **Solo en un servidor**: `sudo bash octopus.sh ajustes` y añade `SOPORTE_BUZON_URL=https://...`.

Para comprobarlo: en el panel, **Enviar sugerencia o problema → Enviar una prueba al soporte** (solo administradores).
Te tiene que llegar un mensaje «🧪 Prueba de envío» al Telegram.

## Opcional

- **Que las sugerencias salgan también en GitHub** (incidencias públicas del repositorio; nunca los problemas ni los
  diagnósticos): añade los secretos `GITHUB_REPO` (`usuario/repositorio`) y `GITHUB_TOKEN` (un *fine-grained token*
  con permiso solo de «Issues: Read and write» en ese repositorio).
- **Una empresa que no quiera que salga nada hacia fuera**: en su servidor, `SOPORTE_BUZON_URL=no`. Lo que escriban
  se queda guardado en su servidor.
- **Correo además de Telegram**: en cada servidor, `SOPORTE_CORREO=tu-correo-de-soporte` (se envía con el correo de
  avisos que tenga configurado ese servidor).
