import type { EstimationResponse } from "../api/types";
import { formatCost, formatDecimal, formatWeeks, outOfScopeReason } from "../lib/format";

function MetricCard({ label, id, value }: { label: string; id: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong id={id}>{value}</strong>
    </div>
  );
}

function OutOfScopeAlert({ summary, confidence }: { summary: string; confidence: number }) {
  return (
    <div className="alert warn" id="out-of-scope">
      <strong>No estimable.</strong> {outOfScopeReason(summary)}
      <div className="meta">Confianza {confidence}% (por debajo del 30% no se ofrecen cifras).</div>
    </div>
  );
}

function PhasesTable({ phases }: { phases: EstimationResponse["result"]["phases"] }) {
  return (
    <table id="phases">
      <thead>
        <tr>
          <th>Fase</th>
          <th>Descripción</th>
          <th className="num">Semanas</th>
          <th className="num">Coste</th>
        </tr>
      </thead>
      <tbody>
        {phases.map((phase, index) => (
          <tr key={`${phase.name}-${index}`}>
            <td>{phase.name}</td>
            <td>{phase.description}</td>
            <td className="num">{formatDecimal(phase.duration_weeks)}</td>
            <td className="num">{formatCost(phase.cost_eur)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function EstimationResult({ estimation }: { estimation: EstimationResponse }) {
  const result = estimation.result;
  if (result.out_of_scope) {
    return <OutOfScopeAlert summary={result.summary} confidence={result.confidence_pct} />;
  }
  return (
    <>
      <p>{result.summary}</p>
      <div className="metrics">
        <MetricCard label="Confianza" id="confidence" value={`${result.confidence_pct}%`} />
        <MetricCard label="Duración total" id="duration" value={formatWeeks(result.total_duration_weeks)} />
        <MetricCard label="Coste total" id="cost" value={formatCost(result.total_cost_eur)} />
      </div>
      <PhasesTable phases={Array.isArray(result.phases) ? result.phases : []} />
    </>
  );
}
