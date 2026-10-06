import type { EstimationResponse } from "../api/types";
import { cacheSourceLabel, formatInteger, formatTime, labelFor } from "../lib/format";
import { EstimationResult } from "./EstimationResult";

const DESCRIPTION_LIMIT = 2000;

function EstimationMeta({ estimation }: { estimation: EstimationResponse }) {
  const options = estimation.options ?? {};
  const parts = [
    labelFor(options.project_type),
    `detalle ${labelFor(options.detail_level).toLowerCase()}`,
    labelFor(options.output_format).toLowerCase(),
    `prompt ${estimation.prompt_version ?? ""}`,
    cacheSourceLabel(estimation.cache_source),
  ];
  if (estimation.requested_at) parts.push(formatTime(estimation.requested_at));
  return <p className="meta" id="estimation-meta">{parts.join(" · ")}</p>;
}

function DescriptionCard({ description }: { description: string }) {
  const chars = Array.from(description);
  return (
    <div className="card">
      <h2>Descripción</h2>
      <p id="description-text" style={{ whiteSpace: "pre-wrap" }}>
        {chars.length > DESCRIPTION_LIMIT ? chars.slice(0, DESCRIPTION_LIMIT).join("") : description}
      </p>
      {chars.length > DESCRIPTION_LIMIT && (
        <p className="meta">{formatInteger(chars.length)} caracteres en total.</p>
      )}
    </div>
  );
}

/** Contenido de la vista de una estimación (tarjeta de resultado + descripción). */
export function EstimationDetail({ estimation }: { estimation: EstimationResponse }) {
  const id = estimation.id ?? estimation.estimation_id;
  return (
    <>
      <h1>Estimación{id ? ` #${id}` : ""}</h1>
      <div className="card">
        <EstimationMeta estimation={estimation} />
        <EstimationResult estimation={estimation} />
      </div>
      <DescriptionCard description={estimation.description ?? ""} />
    </>
  );
}
