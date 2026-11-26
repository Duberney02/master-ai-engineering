// Upstream simulado de Go para verificar nginx (Bloque 3). Solo existe en el Compose de verificación.
// Las barreras son explícitas: un flujo SSE emite su primer evento y espera POST /__release antes del resto, y todo
// cierre de la conexión desde nginx queda registrado en GET /__state.
import http from "node:http";

const state = { requests: [], closed: [], gates: 0 };
let gate = null;
const newGate = () => {
  let release;
  const promise = new Promise((resolve) => { release = resolve; });
  gate = { promise, release };
};
newGate();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const json = (res, status, body) => {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
};
const sse = (res, event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://upstream");
  if (url.pathname === "/__state") return json(res, 200, state);
  if (url.pathname === "/__release") { gate.release(); return json(res, 200, { ok: true }); }
  if (url.pathname === "/__reset") { state.requests = []; state.closed = []; newGate(); return json(res, 200, { ok: true }); }
  if (url.pathname === "/health") return json(res, 200, { status: "healthy" });

  state.requests.push({ method: req.method, path: url.pathname, host: req.headers.host, origin: req.headers.origin ?? null,
    forwardedFor: req.headers["x-forwarded-for"] ?? null, connection: req.headers.connection ?? null });
  const delay = Number(req.headers["x-test-delay-ms"] ?? 0);
  let finished = false;
  res.on("close", () => { if (!finished) state.closed.push(url.pathname); });
  req.resume();

  if (req.method === "POST" && /^\/api\/v1\/(estimate\/stream|transcription\/estimate\/stream)$/.test(url.pathname)) {
    await sleep(delay);
    res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no" });
    const first = url.pathname.includes("transcription") ? ["token", { text: "Hola" }] : ["result", { result: { summary: "ok" } }];
    sse(res, ...first);
    await gate.promise;
    sse(res, "metadata", { cache_source: "none" });
    sse(res, "done", {});
    finished = true;
    return res.end();
  }
  if (/^\/api\/v1\/(estimate|sessions\/[^/]+\/estimate)$/.test(url.pathname) || url.pathname === "/api/v1/rag/chunking-comparisons") {
    if (req.headers["x-test-hold"] === "1") await gate.promise; else await sleep(delay);
    finished = true;
    return json(res, 200, { ok: true });
  }
  if (url.pathname.startsWith("/api/")) {
    await sleep(delay);
    finished = true;
    return json(res, 200, []);
  }
  finished = true;
  return json(res, 404, { detail: "no" });
}).listen(9000, "0.0.0.0", () => console.log("upstream de nginx listo"));
