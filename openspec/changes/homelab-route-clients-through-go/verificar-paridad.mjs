// Verifica la matriz de paridad del Bloque 3: cada prueba nombrada en paridad-bloque3.json debe existir y haber
// pasado en los resultados reales de `go test -json` y `vitest --reporter=json` (sin omitidas ni ausentes).
import { readFileSync } from "node:fs";

const matrix = JSON.parse(readFileSync("/fixtures/paridad-bloque3.json", "utf8"));
const goLines = readFileSync("/evidencias/go-test.json", "utf8").split("\n").filter(Boolean).map((line) => JSON.parse(line));
const vitest = JSON.parse(readFileSync("/evidencias/vitest.json", "utf8"));

const go = new Map(); // nombre → estado final
for (const event of goLines) {
  if (event.Test && ["pass", "fail", "skip"].includes(event.Action)) go.set(`${event.Package}|${event.Test}`, event.Action);
}
const goState = (name) => {
  const states = [...go.entries()].filter(([key]) => key.split("|")[1] === name || key.split("|")[1].startsWith(`${name}/`)).map(([, value]) => value);
  if (states.length === 0) return "ausente";
  if (states.includes("fail")) return "fail";
  return states.every((value) => value === "skip") ? "skip" : "pass";
};
const react = [];
for (const file of vitest.testResults) for (const test of file.assertionResults) react.push({ title: test.title, status: test.status });
const reactState = (title) => {
  const found = react.filter((test) => test.title === title);
  if (found.length === 0) return "ausente";
  return found.every((test) => test.status === "passed") ? "pass" : "fail";
};

let failures = 0;
const lines = [];
let totals = { go: 0, react: 0 };
for (const row of matrix.capacidades) {
  const entries = [
    ...row.referencia_html_go.map((name) => ["html", name, goState(name)]),
    ...row.recorrido_react.map((title) => ["react", title, reactState(title)]),
    ...row.contrato_go.map((name) => ["go", name, goState(name)]),
  ];
  const missing = entries.filter(([, , state]) => state !== "pass");
  if (row.recorrido_react.length === 0 || row.contrato_go.length === 0 || row.referencia_html_go.length === 0) {
    failures += 1;
    lines.push(`FALLA ${row.id}: la fila debe tener referencia HTML, recorrido React y contrato Go`);
  }
  totals.go += row.referencia_html_go.length + row.contrato_go.length;
  totals.react += row.recorrido_react.length;
  for (const [kind, name, state] of missing) {
    failures += 1;
    lines.push(`FALLA ${row.id} [${kind}] ${state}: ${name}`);
  }
  if (missing.length === 0) lines.push(`OK    ${row.id} — HTML Go ${row.referencia_html_go.length}, React ${row.recorrido_react.length}, contrato Go ${row.contrato_go.length}`);
}
lines.push(`Filas: ${matrix.capacidades.length}. Referencias a pruebas Go: ${totals.go}. Referencias a pruebas React: ${totals.react}. Pruebas Go ejecutadas: ${go.size}. Pruebas React ejecutadas: ${react.length}.`);
console.log(lines.join("\n"));
process.exit(failures === 0 ? 0 : 1);
