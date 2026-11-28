// Verificación de nginx delante de Go (cambio homelab-route-clients-through-go, tarea 6.1). Se ejecuta con compose.nginx.yml contra el
// upstream simulado: entrega SSE sin buffering, cancelación hasta el upstream, clasificación de plazos por ruta,
// límite de cuerpo y cabeceras reenviadas. Cualquier fallo termina con código distinto de cero.
import { readFileSync } from "node:fs";

const NGINX = process.env.NGINX_URL ?? "http://nginx:8080";
const UPSTREAM = process.env.UPSTREAM_URL ?? "http://nginx-upstream:9000";
let failures = 0;
const results = [];
function check(name, condition, detail = "") {
  results.push(`${condition ? "OK  " : "FALLA"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!condition) failures += 1;
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const control = (path, init) => fetch(`${UPSTREAM}${path}`, init).then((r) => r.json());
const state = () => control("/__state");
const reset = () => control("/__reset", { method: "POST" });
async function until(predicate, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return true;
    await sleep(100);
  }
  return false;
}

/** Lee eventos SSE completos (separados por línea en blanco) de un cuerpo en streaming. */
async function* events(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      yield { event: /^event: (.*)$/m.exec(raw)?.[1], data: /^data: (.*)$/m.exec(raw)?.[1] };
    }
  }
}
const withTimeout = (promise, ms, label) =>
  Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error(`tiempo agotado: ${label}`)), ms))]);

const configured = (name) => Number(process.env[name].replace("s", ""));
const regular = configured("NGINX_REGULAR_TIMEOUT");
const long = configured("NGINX_LONG_TIMEOUT");

// 0. Sonda local y SPA
await reset();
{
  const health = await fetch(`${NGINX}/healthz`);
  check("/healthz responde 200 sin llamar al upstream", health.status === 200 && (await state()).requests.length === 0);
}

// 0b. /health llega al servicio Go (no a una sonda local) y se reenvía sin cuerpo propio de nginx
{
  const health = await fetch(`${NGINX}/health`);
  const body = await health.json().catch(() => null);
  check("/health se reenvía al upstream", health.status === 200 && body?.status === "healthy", JSON.stringify(body));
}

// 1. SSE: el primer evento llega antes de que el upstream emita el resto (sin buffering) en las dos rutas
for (const path of ["/api/v1/estimate/stream", "/api/v1/transcription/estimate/stream"]) {
  await reset();
  const response = await fetch(`${NGINX}${path}`, { method: "POST", headers: { "Content-Type": "application/json", "Accept-Encoding": "gzip" }, body: "{}" });
  check(`${path}: cabeceras SSE`, response.status === 200 && response.headers.get("content-type") === "text/event-stream" &&
    response.headers.get("cache-control") === "no-cache" && response.headers.get("x-accel-buffering") === "no" &&
    !response.headers.get("content-encoding"), JSON.stringify([...response.headers]));
  check(`${path}: conserva las cabeceras de seguridad`, response.headers.get("x-content-type-options") === "nosniff" && response.headers.get("x-frame-options") === "DENY");
  const iterator = events(response)[Symbol.asyncIterator]();
  let first = null;
  try {
    first = await withTimeout(iterator.next(), 5000, "primer evento");
  } catch (error) {
    check(`${path}: el primer evento llega antes de liberar el upstream`, false, error.message);
  }
  if (first) {
    check(`${path}: el primer evento llega antes de liberar el upstream`, first.value?.event === (path.includes("transcription") ? "token" : "result"));
    await control("/__release", { method: "POST" });
    const rest = [];
    for await (const item of { [Symbol.asyncIterator]: () => iterator }) rest.push(item.event);
    check(`${path}: el resto llega en orden tras la liberación`, rest.join(",") === "metadata,done", rest.join(","));
  }
  const seen = await state();
  check(`${path}: una sola solicitud al upstream y sin cierres prematuros`, seen.requests.length === 1 && seen.closed.length === 0);
  check(`${path}: Host del upstream y X-Forwarded-For reescrito por el proxy`, seen.requests[0]?.host === "nginx-upstream:9000" && /^\d+\.\d+\.\d+\.\d+$/.test(seen.requests[0]?.forwardedFor ?? ""), JSON.stringify(seen.requests[0]));
}

// 2. Cancelación: cerrar al cliente cierra la conexión upstream (SSE y REST largo), sin reintentos
for (const [path, headers] of [
  ["/api/v1/estimate/stream", {}], ["/api/v1/transcription/estimate/stream", {}],
  ["/api/v1/sessions/6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10/estimate", { "X-Test-Hold": "1" }],
  ["/api/v1/rag/chunking-comparisons", { "X-Test-Hold": "1" }],
]) {
  await reset();
  const controller = new AbortController();
  const pending = fetch(`${NGINX}${path}`, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: "{}", signal: controller.signal })
    .then(async (response) => {
      if (path.includes("stream")) { const it = events(response)[Symbol.asyncIterator](); await it.next(); }
    });
  await until(async () => (await state()).requests.length === 1);
  if (path.includes("stream")) await sleep(300); // el primer evento ya salió hacia el cliente
  controller.abort();
  await pending.catch(() => undefined);
  const closed = await until(async () => (await state()).closed.length === 1);
  const seen = await state();
  check(`${path}: el cierre del cliente llega al upstream`, closed && seen.closed[0] === path.split("?")[0], JSON.stringify(seen.closed));
  check(`${path}: un único POST, sin reintentos`, seen.requests.length === 1);
  await control("/__release", { method: "POST" });
}

// 3. Plazos por ruta: habitual, largo y SSE se clasifican por su ruta
{
  const limit = (seconds) => seconds * 1000;
  const delay = String(Math.round((regular + 1.5) * 1000));
  await reset();
  let started = Date.now();
  const regularResponse = await fetch(`${NGINX}/api/v1/estimations`, { headers: { "X-Test-Delay-Ms": delay } });
  const regularElapsed = Date.now() - started;
  check(`ruta habitual: nginx corta con 504 a los ${regular} s`, regularResponse.status === 504 && regularElapsed >= limit(regular) - 200 && regularElapsed < limit(regular + 1.4), `${regularResponse.status} en ${regularElapsed} ms`);
  for (const path of ["/api/v1/estimate", "/api/v1/sessions/6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10/estimate", "/api/v1/rag/chunking-comparisons"]) {
    started = Date.now();
    const response = await fetch(`${NGINX}${path}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Test-Delay-Ms": delay }, body: "{}" });
    const elapsed = Date.now() - started;
    check(`${path}: ruta larga, supera el plazo habitual y responde 200`, response.status === 200 && elapsed >= limit(regular + 1.4) && elapsed < limit(long), `${response.status} en ${elapsed} ms`);
  }
  for (const path of ["/api/v1/estimate/stream", "/api/v1/transcription/estimate/stream"]) {
    await reset();
    started = Date.now();
    const response = await fetch(`${NGINX}${path}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Test-Delay-Ms": delay }, body: "{}" });
    const first = await events(response)[Symbol.asyncIterator]().next();
    check(`${path}: SSE silencioso más allá del plazo habitual sigue vivo`, response.status === 200 && Boolean(first.value) && Date.now() - started >= limit(regular + 1.4), `${Date.now() - started} ms`);
    await control("/__release", { method: "POST" });
  }
  // Inactividad SSE superior al largo: nginx cierra a los `long` s sin un primer evento.
  await reset();
  started = Date.now();
  const silent = await fetch(`${NGINX}/api/v1/estimate/stream`, { method: "POST", headers: { "Content-Type": "application/json", "X-Test-Delay-Ms": String((long + 2) * 1000) }, body: "{}" });
  const body = await silent.text().catch(() => "");
  const elapsed = Date.now() - started;
  check(`SSE sin actividad más allá de ${long} s: nginx corta (502/504 o cuerpo vacío) sin inventar eventos`, !body.includes("event: done") && elapsed >= limit(long) - 300 && elapsed < limit(long + 1.5), `${silent.status} en ${elapsed} ms`);
}

// 4. Límite de cuerpo: 55 MiB (5 archivos de 10 MiB y texto); por encima responde 413 sin tocar el upstream
{
  await reset();
  const big = new Uint8Array(56 * 1024 * 1024);
  // nginx puede cerrar la conexión tras enviar el 413 mientras el cliente aún escribe: ambos desenlaces rechazan el cuerpo.
  const outcome = await fetch(`${NGINX}/api/v1/sessions/6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10/estimate`, {
    method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: big,
  }).then((response) => response.status, () => "conexión cerrada por nginx");
  check("56 MiB: nginx lo rechaza (413) sin llamar al upstream", (outcome === 413 || outcome === "conexión cerrada por nginx") && (await state()).requests.length === 0, String(outcome));
  const ok = await fetch(`${NGINX}/api/v1/sessions/6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10/estimate`, {
    method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: new Uint8Array(54 * 1024 * 1024),
  });
  check("54 MiB: llega al upstream", ok.status === 200);
}

// 5. Dockerfile: las variables por defecto de la imagen coinciden con las del diseño (35 s / 615 s, destino Go)
{
  const dockerfile = readFileSync("/fixtures/Dockerfile", "utf8");
  check("Dockerfile: destino Go y plazos 5/35/615 s", /API_UPSTREAM=http:\/\/estimator-web:3000/.test(dockerfile) &&
    /NGINX_CONNECT_TIMEOUT=5s/.test(dockerfile) && /NGINX_REGULAR_TIMEOUT=35s/.test(dockerfile) && /NGINX_LONG_TIMEOUT=615s/.test(dockerfile));
  check("Dockerfile: valida los plazos antes de la plantilla", /validar-plazos\.sh \/docker-entrypoint\.d\/15-/.test(dockerfile));
}

console.log(results.join("\n"));
process.exit(failures === 0 ? 0 : 1);
