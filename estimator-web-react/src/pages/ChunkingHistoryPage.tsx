import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listComparisons } from "../api/chunkingApi";
import { EstimatorApiError } from "../api/estimatorApi";
import type { Comparison } from "../api/types";
import { Alert } from "../components/Alert";
import { durationSeconds } from "../components/ChunkingResult";
import { PlainPage } from "../components/Layout";
import { formatFixed, formatTime, formatUsd } from "../lib/format";

type State =
  | { status: "loading" }
  | { status: "ready"; items: Comparison[]; warning: string | null };

/** Últimas 20 comparaciones. Si el historial no está disponible se muestra vacío, con un aviso. */
export function ChunkingHistoryPage() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let current = true;
    listComparisons()
      .then((items) => current && setState({ status: "ready", items, warning: null }))
      .catch((failure: unknown) => {
        if (!current) return;
        const warning = failure instanceof EstimatorApiError ? failure.message : "No se pudo completar la operación.";
        setState({ status: "ready", items: [], warning });
      });
    return () => {
      current = false;
    };
  }, []);

  return (
    <PlainPage>
      <h1>Chunking Lab · historial</h1>
      <p><Link className="button" to="/rag/chunking_comparisons/new">Nueva comparación</Link></p>
      {state.status === "loading" && <p className="hint" role="status">Cargando el historial…</p>}
      {state.status === "ready" && state.warning && <Alert kind="warn" id="lab-history-error">{state.warning}</Alert>}
      {state.status === "ready" && state.items.length === 0 && (
        <div className="card" id="lab-history-empty">
          Todavía no hay comparaciones guardadas. <Link to="/rag/chunking_comparisons/new">Crea la primera</Link>.
        </div>
      )}
      {state.status === "ready" && state.items.length > 0 && (
        <div className="card table-scroll">
          <table id="lab-history">
            <thead>
              <tr><th>Fecha</th><th>Estrategias</th><th className="num">Consultas</th><th className="num">Coste</th><th className="num">Duración</th><th /></tr>
            </thead>
            <tbody>
              {state.items.map((item) => {
                const seconds = durationSeconds(item);
                return (
                  <tr key={item.id}>
                    <td>{item.created_at ? formatTime(item.created_at) : "—"}</td>
                    <td>{item.strategy_labels.join(", ")}</td>
                    <td className="num">{item.queries.length}</td>
                    <td className="num">{formatUsd(item.total_ingestion_cost_usd)}</td>
                    <td className="num">{seconds === null ? "—" : `${formatFixed(seconds, 1)} s`}</td>
                    <td><Link to={`/rag/chunking_comparisons/${item.id}`}>Ver</Link></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </PlainPage>
  );
}
