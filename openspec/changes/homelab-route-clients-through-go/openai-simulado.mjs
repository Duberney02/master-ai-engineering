// Proveedor OpenAI simulado (solo pruebas, 14.1): chat completions (normal y SSE), embeddings y moderaciones.
// Jamás contacta proveedores reales. Control: POST /__sim/mode/{normal|slow|fail|hang}, GET /__sim/state.
import http from "node:http";

const RESULT = {
  summary: "Resultado simulado de la estimación",
  confidence_pct: 80,
  phases: [{ name: "Análisis", description: "", duration_weeks: 2, cost_eur: 4000 }, { name: "Desarrollo", description: "", duration_weeks: 6, cost_eur: 18000 }],
  total_duration_weeks: 8,
  total_cost_eur: 22000,
};
let mode = "normal";
const state = { chat: 0, stream: 0, embeddings: 0, moderations: 0, aborted: 0, last_user_chars: 0 };

function vector(text, dims) {
  const v = new Array(dims).fill(0);
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; v[h % dims] += 1; }
  const n = Math.sqrt(v.reduce((a, b) => a + b * b, 0)) || 1;
  return v.map((x) => x / n);
}

function content(messages) {
  const system = String(messages?.[0]?.content ?? "");
  if (/resum|summar/i.test(system) && !/estim/i.test(system.slice(0, 200))) return "Resumen simulado de la conversación.";
  return JSON.stringify(RESULT);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const json = (res, status, body) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };

http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const raw = Buffer.concat(chunks).toString("utf8");
  const path = new URL(req.url, "http://x").pathname;
  let done = false;
  res.on("finish", () => { done = true; });
  req.on("close", () => { if (!done && !res.writableEnded) state.aborted += 1; });

  if (path === "/__sim/state") return json(res, 200, { mode, ...state });
  if (path.startsWith("/__sim/mode/")) { mode = path.split("/").pop(); return json(res, 200, { mode }); }
  if (path === "/__sim/reset") { for (const k of Object.keys(state)) state[k] = 0; mode = "normal"; return json(res, 200, { mode }); }

  let body = {};
  try { body = raw ? JSON.parse(raw) : {}; } catch { /* cuerpo vacío o no JSON */ }

  if (path.endsWith("/chat/completions")) {
    state.chat += 1;
    state.last_user_chars = String(body.messages?.at(-1)?.content ?? "").length;
    if (mode === "fail") return json(res, 500, { error: { message: "sim-secret-detail sk-leak-test interno openai-simulado:8080", type: "server_error" } });
    if (mode === "hang") { await new Promise(() => {}); }
    const text = content(body.messages);
    const model = body.model ?? "gpt-4o-mini";
    const usage = { prompt_tokens: 120, completion_tokens: 80, total_tokens: 200 };
    if (!body.stream) {
      return json(res, 200, { id: "chatcmpl-sim", object: "chat.completion", created: 1, model, choices: [{ index: 0, message: { role: "assistant", content: text }, finish_reason: "stop" }], usage });
    }
    state.stream += 1;
    res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
    const pieces = text.match(/[\s\S]{1,30}/g) ?? [text];
    for (const p of pieces) {
      res.write(`data: ${JSON.stringify({ id: "chatcmpl-sim", object: "chat.completion.chunk", created: 1, model, choices: [{ index: 0, delta: { content: p }, finish_reason: null }] })}\n\n`);
      if (mode === "slow") await sleep(250);
    }
    res.write(`data: ${JSON.stringify({ id: "chatcmpl-sim", object: "chat.completion.chunk", created: 1, model, choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\n`);
    res.write(`data: ${JSON.stringify({ id: "chatcmpl-sim", object: "chat.completion.chunk", created: 1, model, choices: [], usage })}\n\n`);
    res.end("data: [DONE]\n\n");
    return undefined;
  }
  if (path.endsWith("/embeddings")) {
    state.embeddings += 1;
    const inputs = Array.isArray(body.input) ? body.input : [body.input ?? ""];
    const dims = body.dimensions ?? 1536;
    return json(res, 200, { object: "list", model: body.model ?? "text-embedding-3-small", data: inputs.map((t, index) => ({ object: "embedding", index, embedding: vector(String(t), dims) })), usage: { prompt_tokens: 10, total_tokens: 10 } });
  }
  if (path.endsWith("/moderations")) {
    state.moderations += 1;
    const inputs = Array.isArray(body.input) ? body.input : [body.input ?? ""];
    return json(res, 200, { id: "modr-sim", model: body.model ?? "omni-moderation-latest", results: inputs.map(() => ({ flagged: false, categories: {}, category_scores: {} })) });
  }
  return json(res, 404, { error: { message: "ruta no simulada" } });
}).listen(8080, "0.0.0.0", () => console.log("OpenAI simulado en :8080"));
