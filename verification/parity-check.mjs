// Paridad tras la retirada del HTML de Go (cambio homelab-route-clients-through-go, tarea 10.2). Usa la matriz de paridad
// (parity.json) y evalúa sus columnas contra los resultados reales actuales:
//  - recorrido_react y contrato_go: cada prueba nombrada debe existir y haber pasado (sin omitidas ni ausentes).
//  - referencia_html_go: cada prueba HTML nombrada debe figurar como RETIRADA (ausente en la ejecución actual) o, si
//    se conservó, haber pasado. Una prueba HTML que falle u omitida invalida la fila. La correspondencia detallada de
//    cada retirada con su cobertura vigente está en estimator-web-go/EVIDENCIA-RETIRADA-HTML.md.
// La matriz no se modifica: este comprobador solo la lee.
import { readFileSync } from "node:fs";

const matrix = JSON.parse(readFileSync("/tools/parity.json", "utf8"));
const goLines = readFileSync("/evidence/go-test.json", "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const vitest = JSON.parse(readFileSync("/evidence/vitest.json", "utf8"));

const go = new Map();
for (const e of goLines) if (e.Test && ["pass", "fail", "skip"].includes(e.Action)) go.set(`${e.Package}|${e.Test}`, e.Action);
const goState = (name) => {
  const states = [...go.entries()].filter(([k]) => { const t = k.split("|")[1]; return t === name || t.startsWith(`${name}/`); }).map(([, v]) => v);
  if (!states.length) return "ausente";
  if (states.includes("fail")) return "fail";
  return states.every((v) => v === "skip") ? "skip" : "pass";
};
const react = [];
for (const f of vitest.testResults) for (const t of f.assertionResults) react.push({ title: t.title, status: t.status });
const reactState = (title) => {
  const found = react.filter((t) => t.title === title);
  if (!found.length) return "ausente";
  return found.every((t) => t.status === "passed") ? "pass" : "fail";
};

let fallos = 0, retiradas = 0, conservadas = 0, vigentes = 0;
const lineas = [];
for (const row of matrix.capacidades) {
  const malos = [];
  for (const n of row.recorrido_react) { vigentes++; const s = reactState(n); if (s !== "pass") malos.push(`[react] ${s}: ${n}`); }
  for (const n of row.contrato_go) { vigentes++; const s = goState(n); if (s !== "pass") malos.push(`[go] ${s}: ${n}`); }
  let r = 0, c = 0;
  for (const n of row.referencia_html_go) {
    const s = goState(n);
    if (s === "ausente") r++; else if (s === "pass") c++; else malos.push(`[html] ${s}: ${n}`);
  }
  retiradas += r; conservadas += c;
  if (!row.recorrido_react.length || !row.contrato_go.length) malos.push("la fila carece de recorrido React o de contrato Go vigente");
  if (malos.length) { fallos += malos.length; lineas.push(`FALLA ${row.id}\n  ${malos.join("\n  ")}`); }
  else lineas.push(`OK    ${row.id} — React ${row.recorrido_react.length}, contrato Go ${row.contrato_go.length}, HTML retiradas ${r}, conservadas ${c}`);
}
lineas.push(`Filas: ${matrix.capacidades.length}. Pruebas vigentes exigidas: ${vigentes}. Referencias HTML retiradas: ${retiradas}, conservadas: ${conservadas}. Go ejecutadas: ${go.size}. React ejecutadas: ${react.length}.`);
console.log(lineas.join("\n"));
process.exit(fallos === 0 ? 0 : 1);
