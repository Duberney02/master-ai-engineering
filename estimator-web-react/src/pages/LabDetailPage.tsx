import { Link, useParams } from "react-router-dom";
import { getComparison } from "../api/adminApi";
import { AccessRestricted } from "../components/AccessRestricted";
import { Alert } from "../components/Alert";
import { ComparisonView } from "../components/ComparisonView";
import { PlainPage } from "../components/Layout";
import { useAdminResource } from "../hooks/useAdminResource";

export function LabDetailPage() {
  const { id = "" } = useParams();
  // El ID viaja como texto: un número JavaScript perdería dígitos por encima de 2^53 − 1 (DA-27).
  const resource = useAdminResource((signal) => getComparison(id, signal), id);
  if (resource.status === "denied") return <AccessRestricted section="El Chunking Lab" />;

  return (
    <PlainPage>
      {resource.status === "loading" && <p className="hint" role="status">Cargando la comparación…</p>}
      {resource.status === "error" && (
        <>
          <h1>No se pudo completar la operación</h1>
          <Alert kind="error" id="lab-detail-error">{resource.message}</Alert>
          <p>
            <Link to="/rag/chunking-comparisons">← Historial</Link> · <Link to="/rag/chunking-comparisons/new">Nueva comparación</Link>
          </p>
        </>
      )}
      {resource.status === "ready" && <ComparisonView comparison={resource.data} />}
    </PlainPage>
  );
}
