import { Link } from "react-router-dom";
import { listComparisons } from "../api/adminApi";
import { AccessRestricted } from "../components/AccessRestricted";
import { Alert } from "../components/Alert";
import { durationSeconds } from "../components/ComparisonView";
import { PlainPage } from "../components/Layout";
import { useAdminResource } from "../hooks/useAdminResource";
import { formatTime, formatUsd } from "../lib/format";
import { strategyLabel } from "../lib/strategies";

export function LabHistoryPage() {
  const resource = useAdminResource(listComparisons);
  if (resource.status === "denied") return <AccessRestricted section="El Chunking Lab" />;

  return (
    <PlainPage>
      <h1>Chunking Lab · historial</h1>
      <p><Link className="button" to="/rag/chunking-comparisons/new">Nueva comparación</Link></p>
      {resource.status === "loading" && <p className="hint" role="status">Cargando el historial…</p>}
      {resource.status === "error" && (
        <>
          <Alert kind="error" id="lab-history-error">{resource.message}</Alert>
          <button type="button" onClick={resource.reload}>Reintentar</button>
        </>
      )}
      {resource.status === "ready" && resource.data.warning && <Alert kind="warn" id="lab-history-warning">{resource.data.warning}</Alert>}
      {resource.status === "ready" && resource.data.items.length === 0 && (
        <div className="card" id="lab-history-empty">
          Todavía no hay comparaciones guardadas. <Link to="/rag/chunking-comparisons/new">Crea la primera</Link>.
        </div>
      )}
      {resource.status === "ready" && resource.data.items.length > 0 && (
        <div className="card table-scroll">
          <table id="lab-history">
            <thead>
              <tr><th>Fecha</th><th>Estrategias</th><th className="num">Consultas</th><th className="num">Coste</th><th className="num">Duración</th><th /></tr>
            </thead>
            <tbody>
              {resource.data.items.map((item) => (
                <tr key={item.id ?? item.created_at}>
                  <td>{item.created_at ? formatTime(item.created_at) : "—"}</td>
                  <td>{item.strategies.map(strategyLabel).join(", ")}</td>
                  <td className="num">{item.queries.length}</td>
                  <td className="num">{formatUsd(item.total_ingestion_cost_usd)}</td>
                  <td className="num">{durationSeconds(item.duration_ms) ?? "—"}</td>
                  <td>{item.id && <Link to={`/rag/chunking-comparisons/${item.id}`}>Ver</Link>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PlainPage>
  );
}
