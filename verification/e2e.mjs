// Recorridos de extremo a extremo de 14.1: cliente → Nginx (React) → Go → Python, con proveedor simulado.
// El navegador se sustituye por un cliente Node que usa el mismo contrato HTTP y la misma cancelación (AbortController)
// que `estimatorApi.ts`; las pruebas Vitest cubren el cableado interno de React.
//   node e2e.mjs flows | backend-down | cancellation
import { readFileSync } from "node:fs";

const CLIENT = process.env.CLIENT ?? "http://estimator-web-react:8080";
const SIM = process.env.SIM ?? "http://openai-fake:8080";
const FIXTURE = process.env.FIXTURE ?? "http://ia-fixture:8000";
const resultados = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function ok(nombre, condicion, detalle = "") {
  resultados.push({ nombre, ok: Boolean(condicion), detalle: condicion ? "" : String(detalle).slice(0, 300) });
}
async function call(path, { method = "GET", body, headers = {}, base = CLIENT, signal } = {}) {
  const init = { method, headers: { Accept: "application/json", ...headers }, signal };
  if (body !== undefined) {
    if (body instanceof FormData) init.body = body;
    else { init.body = typeof body === "string" ? body : JSON.stringify(body); init.headers["Content-Type"] ??= "application/json"; }
  }
  const r = await fetch(base + path, init);
  const text = await r.text();
  let json; try { json = JSON.parse(text); } catch { json = undefined; }
  return { status: r.status, text, json, headers: r.headers };
}
const sim = (p, m = "GET") => call(p, { method: m, base: SIM }).then((r) => r.json);
const fixture = (p, m = "GET") => call(p, { method: m, base: FIXTURE }).then((r) => r.json);

const ESTIMATE = { description: "Una plataforma web para gestionar pedidos, facturas y clientes con panel de control.", project_type: "web_saas", detail_level: "medium", output_format: "phases_table" };

function turno(texto, extra = {}, archivos = []) {
  const f = new FormData();
  f.set("transcript", texto);
  f.set("project_type", "web_saas");
  f.set("detail_level", "medium");
  f.set("output_format", "phases_table");
  for (const [k, v] of Object.entries(extra)) f.set(k, v);
  for (const [nombre, bytes, tipo] of archivos) f.append("attachments", new Blob([bytes], { type: tipo }), nombre);
  return f;
}

async function sse(path, body, { abortAfter, signal } = {}) {
  const t0 = Date.now();
  const r = await fetch(CLIENT + path, { method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" }, body: JSON.stringify(body), signal });
  const eventos = [];
  if (!r.body) return { status: r.status, eventos, ct: r.headers.get("content-type") };
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { done, value } = await reader.read().catch(() => ({ done: true }));
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.search(/\r?\n\r?\n/)) >= 0) {
      const frame = buf.slice(0, i); buf = buf.slice(i + (buf[i] === "\r" ? 4 : 2));
      const name = /^event: ?(.*)$/m.exec(frame)?.[1] ?? "message";
      eventos.push({ name, t: Date.now() - t0, data: /^data: ?(.*)$/m.exec(frame)?.[1] });
      if (abortAfter && abortAfter(eventos)) return { status: r.status, eventos, ct: r.headers.get("content-type"), cortado: true };
    }
  }
  return { status: r.status, eventos, ct: r.headers.get("content-type"), total: Date.now() - t0 };
}

const sanitizado = (texto) => !/sim-secret-detail|sk-leak-test|openai-fake|estimador-cag|Traceback|File "\//.test(texto);

async function flujos() {
  const adjuntos = JSON.parse(readFileSync("/fixtures/attachments.json", "utf8"));
  const pdf = Buffer.from(adjuntos.pdf, "base64"), docx = Buffer.from(adjuntos.docx, "base64");
  await sim("/__sim/reset", "POST");

  // Salud y vista previa del prompt
  const h = await call("/healthz"); ok("nginx /healthz", h.status === 200, h.text);
  const pv = await call("/api/v1/prompts/estimation?project_type=web_saas&detail_level=medium&output_format=phases_table");
  ok("vista previa del prompt (200, prompt y ejemplos few-shot)", pv.status === 200 && typeof pv.json?.system_prompt === "string" && pv.json.system_prompt.length > 100 && Array.isArray(pv.json?.examples ?? pv.json?.few_shot_examples ?? []), pv.text);
  ok("vista previa sin proveedor", (await sim("/__sim/state")).chat === 0);

  // Estimación REST, historial y detalle
  const e = await call("/api/v1/estimate", { method: "POST", body: ESTIMATE });
  ok("estimación REST 200 con resultado e ID", e.status === 200 && e.json?.result?.total_cost_eur === 22000 && e.json?.estimation_id != null, e.text);
  const id = e.json?.estimation_id;
  const lista = await call("/api/v1/estimations?limit=5");
  ok("historial lista la estimación", lista.status === 200 && Array.isArray(lista.json) && lista.json.some((x) => String(x.id) === String(id)), lista.text);
  const det = await call(`/api/v1/estimations/${id}`);
  ok("detalle por ID", det.status === 200 && det.json?.result?.summary?.includes("simulado"), det.text);
  ok("detalle inexistente 404", (await call("/api/v1/estimations/987654321")).status === 404);
  const malId = await call("/api/v1/estimations/abc");
  ok("ID no numérico rechazado sin 5xx", [404, 422].includes(malId.status), malId.status);
  ok("límites del historial 1–50", (await call("/api/v1/estimations?limit=0")).status === 422 && (await call("/api/v1/estimations?limit=51")).status === 422);

  // Conversación: creación, continuidad, metadatos, adjuntos y expiración
  const s = await call("/api/v1/sessions", { method: "POST" });
  const sid = s.json?.session_id;
  ok("sesión creada (201 + UUID)", s.status === 201 && /^[0-9a-f-]{36}$/.test(sid ?? ""), s.text);
  const t1 = await call(`/api/v1/sessions/${sid}/estimate`, { method: "POST", body: turno("Necesito una plataforma web de pedidos para una pyme.") });
  ok("turno 1 (200, turn_count 1, project_metadata)", t1.status === 200 && t1.json?.turn_count === 1 && t1.json?.project_metadata && t1.json?.max_turns >= 1, t1.text);
  const t2 = await call(`/api/v1/sessions/${sid}/estimate`, { method: "POST", body: turno("Añade facturación electrónica y un panel de métricas.") });
  ok("turno 2 continúa la conversación (turn_count 2)", t2.status === 200 && t2.json?.turn_count === 2, t2.text);
  const t3 = await call(`/api/v1/sessions/${sid}/estimate`, { method: "POST", body: turno("Resumen de requisitos adjuntos.", {}, [["req.pdf", pdf, "application/pdf"], ["req.docx", docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]]) });
  ok("adjuntos PDF y DOCX aceptados (200)", t3.status === 200 && t3.json?.turn_count === 3, t3.text);
  const txt = "Transcripción de reunión TXT. ".repeat(2300); // ≈ 69 000 caracteres, dentro del máximo de 80 000
  const t4 = await call(`/api/v1/sessions/${sid}/estimate`, { method: "POST", body: turno(txt) });
  ok("transcripción TXT larga como texto del turno (200)", t4.status === 200, t4.text);
  ok("sesión inexistente 404", (await call(`/api/v1/sessions/00000000-0000-4000-8000-000000000000/estimate`, { method: "POST", body: turno("hola hola hola hola hola hola") })).status === 404);
  const mal = await call(`/api/v1/sessions/${sid}/estimate`, { method: "POST", body: turno("x", {}, [["a.exe", Buffer.from("MZ"), "application/x-msdownload"]]) });
  ok("adjunto no admitido (4xx saneado)", [413, 415, 422].includes(mal.status) && sanitizado(mal.text), `${mal.status} ${mal.text}`);
  const grande = await call(`/api/v1/sessions/${sid}/estimate`, { method: "POST", body: turno("x".repeat(40), {}, [["gran.pdf", Buffer.alloc(11 * 1024 * 1024, 0x41), "application/pdf"]]) });
  ok("archivo de 11 MiB rechazado (413)", grande.status === 413, grande.status);
  const seis = await call(`/api/v1/sessions/${sid}/estimate`, { method: "POST", body: turno("texto suficiente para turno", {}, Array.from({ length: 6 }, (_, i) => [`d${i}.pdf`, pdf, "application/pdf"])) });
  ok("más de cinco archivos rechazado (4xx)", [413, 415, 422].includes(seis.status), seis.status);

  // Límites y superficie
  ok("JSON de más de 1 MiB rechazado (413)", (await call("/api/v1/estimate", { method: "POST", body: JSON.stringify({ ...ESTIMATE, description: "a".repeat(1_200_000) }) })).status === 413);
  ok("descripción corta rechazada (422)", (await call("/api/v1/estimate", { method: "POST", body: { ...ESTIMATE, description: "corta" } })).status === 422);
  ok("tipo de contenido no admitido (415)", [415, 422].includes((await call("/api/v1/estimate", { method: "POST", body: "x", headers: { "Content-Type": "text/plain" } })).status));
  const r404 = await call("/api/v1/no-existe"); ok("ruta desconocida 404 JSON", r404.status === 404 && r404.json !== undefined, r404.text);
  ok("método no admitido 405", (await call("/api/v1/estimations", { method: "DELETE" })).status === 405);
  const html = await call("/estimations/new"); ok("rutas HTML antiguas de Go ya no existen (SPA o 404, nunca HTML de Go)", !/<form|Ajustes del servicio IA|_estimator_web_session/.test(html.text) || html.text.includes('id="root"'), html.status);

  // Autorización administrativa: denegada por defecto (403) sin llegar a IA ni PostgreSQL
  const antes = await sim("/__sim/state");
  const admin = [["GET", "/api/v1/ai/settings"], ["PUT", "/api/v1/ai/settings"], ["GET", "/api/v1/rag/chunking-comparisons/options"], ["GET", "/api/v1/rag/chunking-comparisons"], ["POST", "/api/v1/rag/chunking-comparisons"], ["GET", "/api/v1/rag/chunking-comparisons/1"]];
  for (const [m, p] of admin) {
    const r = await call(p, { method: m, body: m === "GET" ? undefined : {}, headers: { Cookie: "_estimator_web_session=falsa; role=admin", "X-User-Role": "admin", Origin: "http://localhost:3001" } });
    ok(`${m} ${p} → 403 saneado`, r.status === 403 && sanitizado(r.text), `${r.status} ${r.text}`);
  }
  ok("lo administrativo no llamó al proveedor", (await sim("/__sim/state")).chat === antes.chat);
  const prim = await call("/api/v1/ai/primary-model"); ok("proyección pública del modelo primario (200, sin catálogo)", prim.status === 200 && !("catalog" in (prim.json ?? {})) && !/catalog/.test(prim.text), prim.text);

  // SSE: estructurada y transcripción, con entrega incremental
  await sim("/__sim/mode/slow", "POST");
  const tr = await sse("/api/v1/transcription/estimate/stream", { transcription: `Una transcripción de reunión suficientemente larga para estimar un proyecto web de pedidos. Ejecución ${Date.now()}.` });
  const tokens = tr.eventos.filter((x) => x.name === "token");
  ok("SSE transcripción: text/event-stream, tokens y done", tr.status === 200 && /text\/event-stream/.test(tr.ct ?? "") && tokens.length > 1 && tr.eventos.at(-1)?.name === "done", JSON.stringify(tr.eventos.map((x) => x.name)));
  ok("SSE transcripción: entrega incremental (primer token mucho antes del final)", tokens.length > 1 && tr.total - tokens[0].t > 300, `primer token ${tokens[0]?.t} ms, total ${tr.total} ms`);
  const st = await sse("/api/v1/estimate/stream", ESTIMATE);
  ok("SSE estructurada: result y done en orden", st.status === 200 && st.eventos.map((x) => x.name).join(",").includes("result") && st.eventos.at(-1)?.name === "done" && st.eventos.findIndex((x) => x.name === "result") < st.eventos.length - 1, JSON.stringify(st.eventos.map((x) => x.name)));
  await sim("/__sim/mode/normal", "POST");

  // Errores del proveedor: saneados, sin reintentos de POST ni fugas
  await sim("/__sim/reset", "POST"); await sim("/__sim/mode/fail", "POST");
  // Descripción nueva: la caché exacta serviría la anterior sin llamar al proveedor.
  const f = await call("/api/v1/estimate", { method: "POST", body: { ...ESTIMATE, description: ESTIMATE.description + " Variante sin caché para el escenario de fallo." } });
  const est = await sim("/__sim/state");
  ok("fallo del proveedor → 5xx saneado (sin cuerpo del proveedor, claves ni hosts internos)", f.status >= 500 && f.status <= 504 && sanitizado(f.text), `${f.status} ${f.text}`);
  ok("sin reintentos de POST desde Nginx ni Go (una sola ráfaga de reintentos del SDK, no multiplicada)", est.chat >= 1 && est.chat <= 4, JSON.stringify(est));
  await sim("/__sim/mode/normal", "POST");
  ok("recuperación tras el fallo", (await call("/api/v1/estimate", { method: "POST", body: { ...ESTIMATE, description: ESTIMATE.description + " Recuperación tras el fallo." } })).status === 200);
  const fin = await call("/api/v1/estimations?limit=50");
  ok("persistencia: el historial conserva las estimaciones", Array.isArray(fin.json) && fin.json.length >= 2, fin.text);
}

async function caido() {
  const r = await call("/api/v1/estimate", { method: "POST", body: ESTIMATE });
  ok("Python detenido → 502/503/504 saneado desde React→Go", [502, 503, 504].includes(r.status) && sanitizado(r.text), `${r.status} ${r.text}`);
  const h = await call("/api/v1/estimations?limit=5");
  ok("historial con Python detenido → error saneado, no HTML ni traza", h.status >= 500 && sanitizado(h.text), `${h.status} ${h.text}`);
  const u = await call("/healthz"); ok("Nginx sigue sirviendo con Python detenido", u.status === 200);
}

async function esperar(fn, ms = 6000) {
  const fin = Date.now() + ms; let s;
  while (Date.now() < fin) { s = await fixture("/__test/state"); if (fn(s)) return s; await sleep(40); }
  throw new Error(`barrera no alcanzada: ${JSON.stringify(s)}`);
}

async function cancelacion() {
  const reinicia = (n) => fixture(`/__test/reset/${n}`, "POST");
  const aborta = async (path, body, cond) => {
    const ctl = new AbortController();
    const p = fetch(CLIENT + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal }).then((r) => r.text()).catch((e) => e.name);
    return { ctl, p, cancelar: async () => { ctl.abort(); return p; } };
  };
  const filaCompleta = (s) => { try { const x = JSON.parse(s.rows[0]); return x.description === ESTIMATE.description && x.result?.summary && x.options?.project_type === "web_saas" && x.completed_at; } catch { return false; } };

  // REST antes de escribir (proveedor retenido)
  await reinicia("before");
  let c = await aborta("/api/v1/estimate", ESTIMATE);
  await esperar((s) => s.provider_active);
  const rA = await c.cancelar();
  let s = await esperar((x) => x.provider_closed);
  ok("REST/antes: el cliente recibe la cancelación", rA === "AbortError", rA);
  ok("REST/antes: Python observa el cierre, un único POST y cero filas", s.posts === 1 && s.committed === 0 && s.cache_writes === 0 && !s.writing, JSON.stringify(s));

  // REST durante la escritura (commit retenido)
  await reinicia("write");
  c = await aborta("/api/v1/estimate", ESTIMATE);
  await esperar((x) => x.writing);
  await c.cancelar();
  s = await esperar((x) => x.write_closed);
  ok("REST/escritura: Python libera la escritura, un único POST y cero filas confirmadas", s.posts === 1 && s.committed === 0, JSON.stringify(s));

  // REST tras confirmar la escritura (respuesta retenida)
  await reinicia("rest-after");
  c = await aborta("/api/v1/estimate", ESTIMATE);
  await esperar((x) => x.committed === 1);
  await c.cancelar();
  s = await esperar((x) => x.response_closed);
  ok("REST/después: Python observa el cierre, un único POST y exactamente una fila completa consultable", s.posts === 1 && s.committed === 1 && filaCompleta(s), JSON.stringify(s).slice(0, 400));

  // SSE estructurada: antes, durante la escritura y tras result
  for (const [escenario, espera, cierre] of [["before", (x) => x.provider_active, (x) => x.provider_closed], ["write", (x) => x.writing, (x) => x.write_closed]]) {
    await reinicia(escenario);
    c = await aborta("/api/v1/estimate/stream", ESTIMATE);
    await esperar(espera);
    await c.cancelar();
    s = await esperar(cierre);
    // Tras generar, la caché guarda el resultado completo (el fixture lo valida contra EstimationResult: 2 escrituras, exacta y
    // semántica). Lo que no debe existir es una fila de historial sin confirmar ni una entrada parcial.
    const cache = escenario === "write" ? 2 : 0;
    ok(`SSE estructurada/${escenario}: cierre hasta Python, un POST, ninguna fila y sin caché parcial (${cache} entradas completas)`, s.posts === 1 && s.committed === 0 && s.cache_writes === cache, JSON.stringify(s));
  }
  await reinicia("after");
  const ctl = new AbortController();
  const r = await sse("/api/v1/estimate/stream", ESTIMATE, { signal: ctl.signal, abortAfter: (ev) => ev.some((x) => x.name === "result") });
  ctl.abort();
  s = await esperar((x) => x.response_closed);
  ok("SSE estructurada/tras result: cierre hasta Python, un POST y exactamente una fila completa", r.eventos.at(-1)?.name === "result" && s.posts === 1 && s.committed === 1 && filaCompleta(s), JSON.stringify(s).slice(0, 400));

  // SSE de transcripción: tras el primer token
  await reinicia("transcription");
  const ctl2 = new AbortController();
  const rt = await sse("/api/v1/transcription/estimate/stream", { transcription: "Una transcripción suficientemente larga para estimar." }, { signal: ctl2.signal, abortAfter: (ev) => ev.some((x) => x.name === "token") });
  ctl2.abort();
  s = await esperar((x) => x.provider_closed);
  ok("SSE transcripción/tras el primer token: cierre hasta Python, liberación del proveedor, un POST y sin datos parciales", rt.eventos.some((x) => x.name === "token") && s.posts === 1 && s.committed === 0 && s.cache_writes === 0, JSON.stringify(s));
}

const modo = process.argv[2];
try {
  if (modo === "flows") await flujos(); else if (modo === "backend-down") await caido(); else if (modo === "cancellation") await cancelacion();
  else { console.error("uso: node e2e.mjs flows|backend-down|cancellation"); process.exit(2); }
} catch (e) { ok(`excepción en ${modo}`, false, e.stack ?? e); }
const fallos = resultados.filter((r) => !r.ok);
for (const r of resultados) console.log(`${r.ok ? "OK   " : "FALLA"} ${r.nombre}${r.ok ? "" : " -> " + r.detalle}`);
console.log(`${modo}: ${resultados.length - fallos.length}/${resultados.length} correctas`);
process.exit(fallos.length ? 1 : 0);
