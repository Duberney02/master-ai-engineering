// Equivalente de ApplicationHelper (Rails): etiquetas y formato español de cifras y fechas.
// No usa Intl para que el resultado no dependa del ICU ni de la zona horaria del navegador.

const LABELS: Record<string, string> = {
  mobile_app: "App móvil",
  web_saas: "SaaS web",
  internal_tool: "Herramienta interna",
  data_pipeline: "Pipeline de datos",
  summary: "Resumen",
  medium: "Medio",
  detailed: "Detallado",
  phases_table: "Tabla de fases",
  line_items: "Partidas",
  narrative: "Narrativa",
};

const CACHE_SOURCES: Record<string, string> = {
  none: "Generada",
  exact: "Caché exacta",
  semantic: "Caché semántica",
};

const OUT_OF_SCOPE_PREFIX = "Out of scope:";

export function labelFor(value: unknown): string {
  const key = String(value ?? "");
  return LABELS[key] ?? key;
}

export function optionsForLabels(values: readonly string[]): { label: string; value: string }[] {
  return values.map((value) => ({ label: labelFor(value), value }));
}

export function cacheSourceLabel(source: unknown): string {
  return CACHE_SOURCES[String(source ?? "")] ?? "Generada";
}

function groupThousands(digits: string, delimiter: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, delimiter);
}

/** number_with_precision de Rails: separador decimal `,` y, opcionalmente, miles `.` y ceros no significativos. */
function formatNumber(
  value: number,
  precision: number,
  { delimiter = "", stripZeros = false }: { delimiter?: string; stripZeros?: boolean } = {},
): string {
  const [integer, fraction = ""] = Math.abs(value).toFixed(precision).split(".");
  const decimals = stripZeros ? fraction.replace(/0+$/, "") : fraction;
  const isZero = Number(`${integer}.${fraction || "0"}`) === 0;
  const sign = value < 0 && !isZero ? "-" : "";
  return `${sign}${groupThousands(integer, delimiter)}${decimals ? `,${decimals}` : ""}`;
}

export function formatDecimal(value: number, precision = 1): string {
  return formatNumber(Number(value), precision, { stripZeros: true });
}

export function formatInteger(value: unknown): string {
  const number = Number(value);
  return groupThousands(String(Math.trunc(Number.isFinite(number) ? Math.abs(number) : 0)), ".");
}

export function formatCost(value: number): string {
  return `${formatNumber(Number(value), 2, { delimiter: "." })} EUR`;
}

export function formatWeeks(value: number): string {
  return `${formatNumber(Number(value), 1, { stripZeros: true })} semanas`;
}

export function formatUsd(value: number | null | undefined): string {
  return value === null || value === undefined ? "Sin tarifa" : `${formatNumber(Number(value), 6)} USD`;
}

/** `dd/mm/aaaa hh:mm UTC`; si no es una fecha ISO válida devuelve el texto tal cual. */
export function formatTime(iso: unknown): string {
  const text = String(iso ?? "");
  const date = new Date(text);
  if (!/^\d{4}-\d{2}-\d{2}T/.test(text) || Number.isNaN(date.getTime())) return text;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${pad(date.getUTCDate())}/${pad(date.getUTCMonth() + 1)}/${date.getUTCFullYear()} ` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`
  );
}

export function outOfScopeReason(summary: unknown): string {
  const text = String(summary ?? "");
  return (text.startsWith(OUT_OF_SCOPE_PREFIX) ? text.slice(OUT_OF_SCOPE_PREFIX.length) : text).trim();
}

/** Equivalente de `String#truncate` de Rails: recorta y añade «...» dentro del límite. */
export function truncate(text: string, limit: number): string {
  const chars = Array.from(text);
  return chars.length <= limit ? text : `${chars.slice(0, limit - 3).join("")}...`;
}
