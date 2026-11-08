import type { ChunkingResponse, ChunkingStats, Comparison, QueryResult } from "../api/types";
import { formatFixed, formatTime, formatUsd } from "../lib/format";

type Labels = Record<string, string>;

/** Etiquetas de las estrategias ejecutadas (las envía el backend); si falta alguna, su nombre. */
function labelsOf(comparison: Comparison): Labels {
  return Object.fromEntries(comparison.strategies.map((name, index) => [name, comparison.strategy_labels[index] ?? name]));
}

/** Orden de la ejecución y después las estrategias que solo aparezcan en la respuesta. */
function strategyNames(comparison: Comparison, response: ChunkingResponse): string[] {
  const present = Object.keys(response.stats_per_strategy);
  const ordered = comparison.strategies.filter((name) => present.includes(name));
  return [...ordered, ...present.filter((name) => !ordered.includes(name)).sort()];
}

interface Section {
  names: string[];
  stats: Record<string, ChunkingStats>;
  labels: Labels;
}

function StatsTable({ names, stats, labels }: Section) {
  return (
    <>
      <div className="table-scroll">
        <table id="stats-table">
          <thead>
            <tr>
              <th>Estrategia</th><th className="num">Chunks</th><th className="num">Mín</th><th className="num">p50</th>
              <th className="num">p95</th><th className="num">Máx</th>
              <th className="num" title="Menos de 20 tokens">Huérfanos</th>
              <th className="num" title="Más de 800 tokens">Obesos</th>
              <th className="num">Llamadas extra</th><th className="num">Segundos</th>
            </tr>
          </thead>
          <tbody>
            {names.map((name) => {
              const row = stats[name];
              const distribution = row.token_distribution;
              return (
                <tr key={name} id={`stats-${name}`}>
                  <td><strong>{labels[name] ?? name}</strong></td>
                  <td className="num">{row.n_chunks}</td>
                  <td className="num">{Math.round(distribution.min)}</td>
                  <td className="num">{formatFixed(distribution.p50, 1)}</td>
                  <td className="num">{formatFixed(distribution.p95, 1)}</td>
                  <td className="num">{Math.round(distribution.max)}</td>
                  <td className="num">{row.n_orphan_chunks}{row.n_orphan_chunks > 0 ? " ⚠" : ""}</td>
                  <td className="num">{row.n_obese_chunks}{row.n_obese_chunks > 0 ? " ⚠" : ""}</td>
                  <td className="num">{row.extra_api_calls}</td>
                  <td className="num">{formatFixed(row.ingestion_seconds, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="hint">Huérfanos: chunks de menos de 20 tokens. Obesos: más de 800 tokens. Los percentiles son de tokens por chunk.</p>
    </>
  );
}

function CostBars({ names, stats, labels }: Section) {
  const costs = names.map((name) => stats[name].ingestion_cost_usd);
  const max = Math.max(0, ...costs);
  const total = costs.reduce((sum, cost) => sum + cost, 0);
  if (max === 0) {
    return <p id="cost-free">Todas las estrategias de esta ejecución son gratuitas: no tienen coste de ingesta.</p>;
  }
  return (
    <>
      <div id="cost-bars">
        {names.map((name) => {
          const cost = stats[name].ingestion_cost_usd;
          return (
            <div className="bar-row" key={name} id={`cost-${name}`}>
              <span>{labels[name] ?? name}</span>
              <div className="bar" role="img" aria-label={`Coste de ${labels[name] ?? name}`}>
                <span style={{ width: `${(cost / max) * 100}%` }} />
              </div>
              <span className="num">{cost === 0 ? "gratis" : formatUsd(cost)}</span>
            </div>
          );
        })}
      </div>
      <p className="hint">Total: {formatUsd(total)}. Es una estimación con tarifas de referencia, no la factura.</p>
    </>
  );
}

function resultsFor(response: ChunkingResponse, names: string[], query: string): { name: string; result: QueryResult }[] {
  const found: { name: string; result: QueryResult }[] = [];
  for (const name of names) {
    const result = (response.queries_per_strategy[name] ?? []).find((item) => item.query === query);
    if (result) found.push({ name, result });
  }
  return found;
}

function Playground({ queries, names, response, labels }: { queries: string[]; names: string[]; response: ChunkingResponse; labels: Labels }) {
  return (
    <>
      {queries.map((query, index) => (
        <section className="card" id={`query-${index}`} key={query}>
          <h3>«{query}»</h3>
          <div className="strategies-grid">
            {resultsFor(response, names, query).map(({ name, result }) => (
              <div key={name} id={`query-${index}-${name}`}>
                <h4>{labels[name] ?? name}</h4>
                {result.top_k.map((chunk) => {
                  const pct = Math.round(Math.min(Math.max(chunk.cosine, 0), 1) * 100);
                  return (
                    <div className="hit" key={chunk.chunk_id}>
                      <div className="bar" role="img" aria-label={`Similitud ${pct}%`}><span style={{ width: `${pct}%` }} /></div>
                      <div>
                        <strong>{formatFixed(chunk.cosine, 3)}</strong> <code>{chunk.chunk_id}</code>
                        {chunk.level === "parent" && <span className="badge parent">padre</span>}
                        {chunk.level === "child" && <span className="badge">hijo de <code>{chunk.parent_chunk_id}</code></span>}
                      </div>
                      <div className="meta">{chunk.text_preview}</div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

/** Estadísticas, costes y recuperación por consulta de una ejecución del Chunking Lab. */
export function ChunkingResult({ comparison }: { comparison: Comparison }) {
  const response = comparison.response;
  if (!response) return null;
  const labels = labelsOf(comparison);
  const names = strategyNames(comparison, response);
  const queries = Array.from(
    new Set(Object.values(response.queries_per_strategy).flatMap((items) => items.map((item) => item.query))),
  );

  return (
    <>
      <section className="card" id="lab-stats">
        <h2>Estadísticas por estrategia</h2>
        <StatsTable names={names} stats={response.stats_per_strategy} labels={labels} />
      </section>
      <section className="card" id="lab-cost">
        <h2>Coste de la ingesta</h2>
        <CostBars names={names} stats={response.stats_per_strategy} labels={labels} />
      </section>
      {queries.length > 0 ? (
        <section id="lab-playground">
          <h2>Recuperación por consulta</h2>
          <Playground queries={queries} names={names} response={response} labels={labels} />
        </section>
      ) : (
        <div className="card" id="lab-no-queries">Esta ejecución no tuvo consultas: solo se calcularon las estadísticas.</div>
      )}
    </>
  );
}

/** Segundos con un decimal (`3,2`), o null si no se midió la duración. */
export function durationSeconds(comparison: Comparison): number | null {
  return comparison.duration_ms === null ? null : Math.round(comparison.duration_ms / 100) / 10;
}

/** Fecha, corpus, duración y coste de ingesta total de una ejecución. */
export function ComparisonMeta({ comparison }: { comparison: Comparison }) {
  const seconds = durationSeconds(comparison);
  return (
    <p className="meta">
      {comparison.saved && comparison.created_at ? `Ejecutada el ${formatTime(comparison.created_at)} · ` : ""}
      {comparison.corpus_count} presupuestos
      {seconds !== null ? ` · ${formatFixed(seconds, 1)} s` : ""}
      {` · coste de ingesta ${formatUsd(comparison.total_ingestion_cost_usd)}`}
    </p>
  );
}
