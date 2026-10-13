// OCTOPUS - Buzón de soporte (Cloudflare Workers, plan gratis).
//
// Recibe lo que los usuarios envían desde «Enviar sugerencia o problema» en cualquier servidor OCTOPUS y lo reenvía
// al Telegram del soporte (y, si se quiere, las sugerencias a GitHub como incidencia pública).
// Las claves NO están aquí: se guardan como «secretos» en Cloudflare (ver LEEME.md):
//   TELEGRAM_TOKEN   token del bot (de @BotFather)
//   TELEGRAM_CHAT    número del chat al que avisar
//   GITHUB_TOKEN / GITHUB_REPO   (opcional) para publicar las sugerencias en GitHub
//
// Protecciones: solo acepta POST /enviar con JSON pequeño, limita los mensajes por servidor y por IP, y recorta textos.

const MAX_BYTES = 24000;
const MAX_POR_HORA = 20;            // por IP
const GRAVEDADES = {
  sugerencia: "💡 Sugerencia", duda: "❓ Duda", problema: "⚠️ Algo no funciona",
  urgente: "🚨 URGENTE", prueba: "🧪 Prueba de envío",
};

function respuesta(datos, estado = 200) {
  return new Response(JSON.stringify(datos), { status: estado, headers: { "Content-Type": "application/json" } });
}

async function demasiados(request) {
  // contador aproximado por IP y hora en la caché de Cloudflare (sin bases de datos)
  const ip = request.headers.get("CF-Connecting-IP") || "desconocida";
  const hora = new Date().toISOString().slice(0, 13);
  const clave = new Request(`https://buzon.octopus/limite/${encodeURIComponent(ip)}/${hora}`);
  const cache = caches.default;
  const previo = await cache.match(clave);
  const n = previo ? parseInt(await previo.text(), 10) || 0 : 0;
  if (n >= MAX_POR_HORA) return true;
  await cache.put(clave, new Response(String(n + 1), { headers: { "Cache-Control": "max-age=3700" } }));
  return false;
}

function limpio(v, max) {
  return String(v ?? "").replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "").slice(0, max);
}

async function aTelegram(env, d) {
  const cab = `${GRAVEDADES[d.gravedad] || d.gravedad} · OCTOPUS ${d.version} · ${d.servidor}`;
  let texto = `${cab}\n${d.fecha}\n${d.correo ? "Responder a: " + d.correo + "\n" : ""}\n${d.texto}`;
  if (d.diagnostico) texto += `\n\n— Diagnóstico —\n${d.diagnostico}`;
  const partes = [];
  for (let i = 0; i < texto.length && partes.length < 4; i += 3900) partes.push(texto.slice(i, i + 3900));
  for (const p of partes) {
    const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/sendMessage`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT, text: p, disable_web_page_preview: true }),
    });
    if (!r.ok) return false;
  }
  return true;
}

async function aGithub(env, d) {
  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/issues`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json",
               "User-Agent": "octopus-buzon", "Content-Type": "application/json" },
    body: JSON.stringify({ title: `[Sugerencia] ${d.texto.slice(0, 70)}`,
                           body: `Enviada desde el panel de OCTOPUS ${d.version}.\n\n${d.texto}`, labels: ["sugerencia"] }),
  });
  return r.ok;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/estado")) {
      return respuesta({ ok: true, buzon: "OCTOPUS", telegram: Boolean(env.TELEGRAM_TOKEN && env.TELEGRAM_CHAT) });
    }
    if (request.method !== "POST" || url.pathname !== "/enviar") return respuesta({ ok: false, error: "no existe" }, 404);
    const largo = parseInt(request.headers.get("Content-Length") || "0", 10);
    if (largo > MAX_BYTES) return respuesta({ ok: false, error: "demasiado grande" }, 413);
    if (await demasiados(request)) return respuesta({ ok: false, error: "demasiados mensajes, prueba más tarde" }, 429);
    let d;
    try {
      const cuerpo = await request.text();
      if (cuerpo.length > MAX_BYTES) return respuesta({ ok: false, error: "demasiado grande" }, 413);
      d = JSON.parse(cuerpo);
    } catch {
      return respuesta({ ok: false, error: "JSON no válido" }, 400);
    }
    d = {
      version: limpio(d.version, 20), servidor: limpio(d.servidor, 20), gravedad: limpio(d.gravedad, 20),
      texto: limpio(d.texto, 5000), correo: limpio(d.correo, 200), diagnostico: limpio(d.diagnostico, 12000),
      fecha: limpio(d.fecha, 40),
    };
    if (d.texto.trim().length < 3) return respuesta({ ok: false, error: "mensaje vacío" }, 400);
    if (!env.TELEGRAM_TOKEN || !env.TELEGRAM_CHAT) return respuesta({ ok: false, error: "buzón sin configurar" }, 503);
    const ok = await aTelegram(env, d);
    if (ok && d.gravedad === "sugerencia" && !d.diagnostico && env.GITHUB_TOKEN && env.GITHUB_REPO) {
      await aGithub(env, d).catch(() => false);
    }
    return respuesta({ ok }, ok ? 200 : 502);
  },
};
