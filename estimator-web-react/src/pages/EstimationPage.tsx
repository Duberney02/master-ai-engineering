import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { EstimatorApiError, findEstimation } from "../api/estimatorApi";
import type { EstimationResponse } from "../api/types";
import { EstimationDetail } from "../components/EstimationDetail";
import { ErrorPage } from "../components/ErrorPage";
import { PlainPage } from "../components/Layout";
import { PromptSidebar } from "../components/PromptSidebar";
import { WithSidebar } from "../components/WithSidebar";
import { usePromptPreview } from "../hooks/usePromptPreview";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; estimation: EstimationResponse };

export function EstimationPage() {
  const { id = "" } = useParams();
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let current = true;
    setState({ status: "loading" });
    findEstimation(id)
      .then((estimation) => current && setState({ status: "ready", estimation }))
      .catch((error: unknown) => {
        if (!current) return;
        const message = error instanceof EstimatorApiError ? error.message : "No se pudo completar la operación.";
        setState({ status: "error", message });
      });
    return () => {
      current = false;
    };
  }, [id]);

  const estimation = state.status === "ready" ? state.estimation : null;
  const { preview, loading } = usePromptPreview(
    estimation
      ? {
          prompt_version: estimation.prompt_version,
          project_type: estimation.options?.project_type,
          detail_level: estimation.options?.detail_level,
          output_format: estimation.options?.output_format,
        }
      : null,
  );

  if (state.status === "error") return <ErrorPage message={state.message} />;
  if (!estimation) {
    return (
      <PlainPage>
        <p className="hint" role="status">Cargando la estimación…</p>
      </PlainPage>
    );
  }

  return (
    <WithSidebar
      sidebar={<PromptSidebar preview={preview} loading={loading} metrics={estimation.metrics} promptVersion={estimation.prompt_version} />}
    >
      <EstimationDetail estimation={estimation} />
      <p>
        <Link to="/estimations">← Historial</Link> · <Link to="/">Nueva estimación</Link>
      </p>
    </WithSidebar>
  );
}
