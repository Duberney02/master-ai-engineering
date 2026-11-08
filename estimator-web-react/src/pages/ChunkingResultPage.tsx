import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { findComparison } from "../api/chunkingApi";
import { EstimatorApiError } from "../api/estimatorApi";
import type { Comparison } from "../api/types";
import { ChunkingResult, ComparisonMeta } from "../components/ChunkingResult";
import { ErrorPage } from "../components/ErrorPage";
import { PlainPage } from "../components/Layout";

type State = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; comparison: Comparison };

/** Resultado de una ejecución guardada del Chunking Lab. */
export function ChunkingResultPage() {
  const { id = "" } = useParams();
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let current = true;
    setState({ status: "loading" });
    findComparison(id)
      .then((comparison) => current && setState({ status: "ready", comparison }))
      .catch((failure: unknown) => {
        if (current) setState({ status: "error", message: failure instanceof EstimatorApiError ? failure.message : "No se pudo completar la operación." });
      });
    return () => {
      current = false;
    };
  }, [id]);

  if (state.status === "error") return <ErrorPage message={state.message} />;
  if (state.status === "loading") return <PlainPage><p className="hint" role="status">Cargando la comparación…</p></PlainPage>;

  return (
    <PlainPage>
      <h1>Resultado de la comparación</h1>
      <ComparisonMeta comparison={state.comparison} />
      <p>
        <Link to="/rag/chunking_comparisons/new">← Nueva comparación</Link> · <Link to="/rag/chunking_comparisons">Historial</Link>
      </p>
      <ChunkingResult comparison={state.comparison} />
    </PlainPage>
  );
}
