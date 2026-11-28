import { Link } from "react-router-dom";
import type { ComparisonDetail, QueryOutcome, StrategyStats } from "../api/types";
import { formatFixed, formatTime, formatUsd } from "../lib/format";
import { strategyLabel } from "../lib/strategies";
import { Alert } from "./Alert";

const number1 = (value: number) => formatFixed(value, 1);
const number2 = (value: number) => formatFixed(value, 2);
const number3 = (value: number) => formatFixed(value, 3);
const plain = (value: number) => String(Math.round(value));

/** Duración con un decimal como la web HTML (`3.2 s`, `3 s`); `null` si no se midió. */
export function durationSeconds(ms: number | null): string | null {
  return ms === null ? null : `${Math.round(ms / 100) / 10} s`;
}

function StatsTable({ stats }: { stats: StrategyStats[] }) {
  return (
    <>
      <table id="stats-table">
        <thead>
          <tr>
            <th>Estrategia</th>
            <th className="num">Chunks</th>
            <th className="num">Mín</th>
            <th className="num">p50</th>
            <th className="num">p95</th>
            <th className="num">Máx</th>
            <th className="num" title="Menos de 20 tokens">Huérfanos</th>
            <th className="num" title="Más de 800 tokens">Obesos</th>
            <th className="num">Llamadas extra</th>
            <th className="num">Segundos</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((row) => (
            <tr key={row.strategy} id={`stats-${row.strategy}`}>
              <td><strong>{strategyLabel(row.strategy)}</strong></td>
              <td className="num">{row.n_chunks}</td>
              <td className="num">{plain(row.token_distribution.min)}</td>
              <td className="num">{number1(row.token_distribution.p50)}</td>
              <td className="num">{number1(row.token_distribution.p95)}</td>
              <td className="num">{plain(row.token_distribution.max)}</td>
              <td className="num">{row.n_orphan_chunks}{row.n_orphan_chunks > 0 ? " ⚠" : ""}</td>
              <td className="num">{row.n_obese_chunks}{row.n_obese_chunks > 0 ? " ⚠" : ""}</td>
              <td className="num">{row.extra_api_calls}</td>
              <td className="num">{number2(row.ingestion_seconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">Huérfanos: chunks de menos de 20 tokens. Obesos: más de 800 tokens. Los percentiles son de tokens por chunk.</p>
    </>
  );
}

function CostBars({ stats, total }: { stats: StrategyStats[]; total: number }) {
  const max = Math.max(0, ...stats.map((row) => row.ingestion_cost_usd));
  if (max === 0) {
    return <p id="cost-free">Todas las estrategias de esta ejecución son gratuitas: no tienen coste de ingesta.</p>;
  }
  return (
    <>
      <div id="cost-bars">
        {stats.map((row) => (
          <div className="bar-row" key={row.strategy} id={`cost-${row.strategy}`}>
            <span>{strategyLabel(row.strategy)}</span>
            <div className="bar" role="img" aria-label={`Coste de ${strategyLabel(row.strategy)}`}>
              <span style={{ width: `${Math.round((row.ingestion_cost_usd / max) * 100)}%` }} />
            </div>
            <span className="num">{row.ingestion_cost_usd === 0 ? "gratis" : formatUsd(row.ingestion_cost_usd)}</span>
          </div>
        ))}
      </div>
      <p className="hint">Total: {formatUsd(total)}. Es una estimación con tarifas de referencia, no la factura.</p>
    </>
  );
}

function Playground({ outcomes, strategies }: { outcomes: QueryOutcome[]; strategies: string[] }) {
  const queries = [...new Set(outcomes.map((outcome) => outcome.query))];
  return (
    <>
      {queries.map((query, index) => (
        <section className="card" id={`query-${index}`} key={query}>
          <h3>«{query}»</h3>
          <div className="strategies-grid">
            {strategies.flatMap((name) =>
              outcomes
                .filter((outcome) => outcome.query === query && outcome.strategy === name)
                .slice(0, 1)
                .map((outcome) => (
                  <div id={`query-${index}-${name}`} key={name}>
                    <h4>{strategyLabel(name)}</h4>
                    {outcome.top_k.map((hit) => {
                      const pct = Math.round(Math.min(Math.max(hit.cosine, 0), 1) * 100);
                      return (
                        <div className="hit" key={hit.chunk_id}>
                          <div className="bar" role="img" aria-label={`Similitud ${pct}%`}><span style={{ width: `${pct}%` }} /></div>
                          <div>
                            <strong>{number3(hit.cosine)}</strong> <code>{hit.chunk_id}</code>
                            {hit.level === "parent" && <span className="badge parent">padre</span>}
                            {hit.level === "child" && <span className="badge">hijo de <code>{hit.parent_chunk_id}</code></span>}
                          </div>
                          <div className="meta">{hit.text_preview}</div>
                        </div>
                      );
                    })}
                  </div>
                )),
            )}
          </div>
        </section>
      ))}
    </>
  );
}

/** Resultado de una comparación: estadísticas, barras de coste y recuperación por consulta (solo si hubo consultas). */
export function ComparisonView({ comparison }: { comparison: ComparisonDetail }) {
  const stats = comparison.result.stats_per_strategy;
  const outcomes = comparison.result.queries_per_strategy;
  const seconds = durationSeconds(comparison.duration_ms);
  return (
    <>
      <h1>Resultado de la comparación</h1>
      {comparison.warning && <Alert kind="warn" id="comparison-warning">{comparison.warning}</Alert>}
      <p className="meta" id="comparison-meta">
        {comparison.created_at && <>Ejecutada el {formatTime(comparison.created_at)} · </>}
        {comparison.corpus_count} presupuestos
        {seconds && <> · {seconds}</>}
        {" "}· coste de ingesta {formatUsd(comparison.total_ingestion_cost_usd)}
      </p>
      <p>
        <Link to="/rag/chunking-comparisons/new">← Nueva comparación</Link> · <Link to="/rag/chunking-comparisons">Historial</Link>
      </p>

      <section className="card" id="lab-stats">
        <h2>Estadísticas por estrategia</h2>
        <StatsTable stats={stats} />
      </section>
      <section className="card" id="lab-cost">
        <h2>Coste de la ingesta</h2>
        <CostBars stats={stats} total={comparison.total_ingestion_cost_usd} />
      </section>
      {outcomes.length > 0 ? (
        <section id="lab-playground">
          <h2>Recuperación por consulta</h2>
          <Playground outcomes={outcomes} strategies={stats.map((row) => row.strategy)} />
        </section>
      ) : (
        <div className="card" id="lab-no-queries">Esta ejecución no tuvo consultas: solo se calcularon las estadísticas.</div>
      )}
    </>
  );
}
