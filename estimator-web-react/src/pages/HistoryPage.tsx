import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EstimatorApiError, listEstimations } from "../api/estimatorApi";
import type { EstimationSummary } from "../api/types";
import { Alert } from "../components/Alert";
import { PromptSidebar } from "../components/PromptSidebar";
import { WithSidebar } from "../components/WithSidebar";
import { usePromptPreview } from "../hooks/usePromptPreview";
import { defaultForm } from "../lib/estimationForm";
import { cacheSourceLabel, formatCost, formatTime, labelFor, truncate } from "../lib/format";

const HISTORY_LIMIT = 10;
const DEFAULTS = defaultForm();

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: EstimationSummary[] };

function HistoryTable({ items }: { items: EstimationSummary[] }) {
  return (
    <div className="card table-scroll">
      <table id="history">
        <thead>
          <tr>
            <th>Fecha</th><th>Tipo</th><th className="num">Confianza</th><th className="num">Coste</th><th>Procedencia</th><th>Descripción</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td><Link to={`/estimations/${item.id}`}>{formatTime(item.requested_at)}</Link></td>
              <td>{labelFor(item.project_type)}</td>
              <td className="num">{item.confidence_pct}%</td>
              <td className="num">{item.out_of_scope ? "No estimable" : formatCost(item.total_cost_eur)}</td>
              <td>{cacheSourceLabel(item.cache_source)}</td>
              <td>{truncate(item.description_excerpt ?? "", 90)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HistoryPage() {
  const [state, setState] = useState<State>({ status: "loading" });
  const { preview, loading } = usePromptPreview({
    prompt_version: DEFAULTS.prompt_version,
    project_type: DEFAULTS.project_type,
    detail_level: DEFAULTS.detail_level,
    output_format: DEFAULTS.output_format,
  });

  useEffect(() => {
    let current = true;
    listEstimations(HISTORY_LIMIT)
      .then((items) => current && setState({ status: "ready", items }))
      .catch((error: unknown) => {
        if (!current) return;
        setState({
          status: "error",
          message: error instanceof EstimatorApiError ? error.message : "No se pudo completar la operación.",
        });
      });
    return () => {
      current = false;
    };
  }, []);

  return (
    <WithSidebar sidebar={<PromptSidebar preview={preview} loading={loading} />}>
      <h1>Historial</h1>
      {state.status === "loading" && <p className="hint" role="status">Cargando el historial…</p>}
      {state.status === "error" && <Alert kind="warn" id="history-error">{state.message}</Alert>}
      {state.status === "ready" && state.items.length === 0 && (
        <div className="card" id="history-empty">
          Todavía no hay estimaciones. <Link to="/">Crea la primera</Link>.
        </div>
      )}
      {state.status === "ready" && state.items.length > 0 && <HistoryTable items={state.items} />}
    </WithSidebar>
  );
}
