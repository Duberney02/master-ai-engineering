// Sonda de red para 13.1 y 13.2: se ejecuta DENTRO de un contenedor conectado a la red que se quiere probar.
// Comprueba DNS y conexión TCP directa y falla si el resultado difiere de lo esperado.
//   PROBE_TARGETS='[{"nombre":"go","host":"estimator-web","puerto":3000,"esperado":"alcanza"}]' node probe-network.mjs
//   PROBE_GATEWAY_PORTS=5432,11434,3000  añade el gateway por defecto del contenedor como objetivo que debe fallar.
//   node probe-network.mjs --self-test   comprueba la propia sonda sin red externa.
import dns from "node:dns/promises";
import fs from "node:fs";
import net from "node:net";
import { pathToFileURL } from "node:url";

export function gatewayPorDefecto(tabla = fs.readFileSync("/proc/net/route", "utf8")) {
  for (const linea of tabla.trim().split("\n").slice(1)) {
    const [, destino, gw] = linea.split(/\s+/);
    if (destino === "00000000") return gw.match(/../g).reverse().map((h) => parseInt(h, 16)).join(".");
  }
  return null;
}

export async function resolver(host) {
  if (net.isIP(host)) return { ok: true, direccion: host };
  try { return { ok: true, direccion: (await dns.lookup(host, { family: 4 })).address }; }
  catch (e) { return { ok: false, motivo: e.code ?? "ERROR" }; }
}

export function conectar(host, puerto, plazoMs = 3000) {
  return new Promise((res) => {
    const s = net.connect({ host, port: puerto });
    const fin = (r) => { s.destroy(); res(r); };
    s.setTimeout(plazoMs, () => fin({ ok: false, motivo: "TIMEOUT" }));
    s.once("connect", () => fin({ ok: true }));
    s.once("error", (e) => fin({ ok: false, motivo: e.code ?? "ERROR" }));
  });
}

export async function probar(obj) {
  const r = await resolver(obj.host);
  let res = r;
  if (r.ok && obj.puerto) res = { ...r, ...(await conectar(r.direccion, obj.puerto)) };
  const alcanzado = Boolean(res.ok);
  return { ...obj, alcanzado, motivo: res.motivo ?? null, aprobado: (obj.esperado === "alcanza") === alcanzado };
}

export async function ejecutar(objetivos) {
  const resultados = [];
  for (const o of objetivos) resultados.push(await probar(o));
  return resultados;
}

async function autoprueba() {
  const servidor = net.createServer((c) => c.end()).listen(0, "127.0.0.1");
  await new Promise((r) => servidor.once("listening", r));
  const puerto = servidor.address().port;
  const cerrado = await new Promise((r) => { const t = net.createServer().listen(0, "127.0.0.1", () => { const p = t.address().port; t.close(() => r(p)); }); });
  const resultados = await ejecutar([
    { nombre: "escucha local", host: "127.0.0.1", puerto, esperado: "alcanza" },
    { nombre: "puerto cerrado", host: "127.0.0.1", puerto: cerrado, esperado: "falla" },
    { nombre: "DNS inexistente", host: "no-existe.invalid", puerto: 80, esperado: "falla" },
  ]);
  servidor.close();
  return resultados;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let objetivos;
  let resultados;
  if (process.argv.includes("--self-test")) resultados = await autoprueba();
  else {
    objetivos = JSON.parse(process.env.PROBE_TARGETS ?? "[]");
    const puertos = (process.env.PROBE_GATEWAY_PORTS ?? "").split(",").filter(Boolean).map(Number);
    const gw = puertos.length ? gatewayPorDefecto() : null;
    if (puertos.length && gw) for (const p of puertos) objetivos.push({ nombre: `gateway:${p}`, host: gw, puerto: p, esperado: "falla" });
    resultados = await ejecutar(objetivos);
  }
  const fallidos = resultados.filter((r) => !r.aprobado);
  console.log(JSON.stringify({ ok: fallidos.length === 0, total: resultados.length, resultados }, null, 2));
  process.exit(fallidos.length === 0 ? 0 : 1);
}
