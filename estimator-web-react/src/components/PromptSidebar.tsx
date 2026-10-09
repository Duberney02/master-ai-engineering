import type { CallMetrics, ProjectMetadata, PromptPreview } from "../api/types";
import { useConversation } from "../hooks/useConversation";
import { formatInteger, formatUsd } from "../lib/format";

interface Props {
  preview: PromptPreview | null;
  loading?: boolean;
  metrics?: CallMetrics | null;
  promptVersion?: string;
}

// Barra lateral equivalente a la de Streamlit: metadatos del proyecto, contexto del prompt, ejemplos
// few-shot y última llamada.
export function PromptSidebar({ preview, loading = false, metrics = null, promptVersion }: Props) {
  const conversation = useConversation();
  return (
    <>
      <h2>Metadatos del proyecto</h2>
      <ProjectMetadataPanel metadata={conversation.metadata} />
      <button type="button" id="new-conversation" onClick={() => void conversation.newConversation()}>
        Nueva conversación
      </button>
      <h2>Contexto del prompt</h2>
      <SystemPrompt preview={preview} loading={loading} />
      <h3>Última llamada</h3>
      <LastCallMetrics metrics={metrics} promptVersion={promptVersion} />
    </>
  );
}

function ProjectMetadataPanel({ metadata }: { metadata: ProjectMetadata }) {
  const known =
    metadata.project_name || metadata.assumed_team_size || metadata.mentioned_technologies.length > 0 || metadata.agreed_scope;
  if (!known) {
    return (
      <p className="hint" id="no-project-metadata">
        Aún no hay datos del proyecto: se irán recogiendo durante la conversación.
      </p>
    );
  }
  return (
    <dl id="project-metadata">
      <div><dt>Nombre</dt><dd id="metadata-name">{metadata.project_name ?? "—"}</dd></div>
      <div><dt>Equipo supuesto</dt><dd id="metadata-team">{metadata.assumed_team_size ?? "—"}</dd></div>
      <div><dt>Tecnologías</dt><dd id="metadata-technologies">{metadata.mentioned_technologies.join(", ") || "—"}</dd></div>
      <div><dt>Alcance acordado</dt><dd id="metadata-scope">{metadata.agreed_scope ?? "—"}</dd></div>
    </dl>
  );
}

function SystemPrompt({ preview, loading }: { preview: PromptPreview | null; loading: boolean }) {
  if (!preview) {
    return loading ? (
      <p className="hint" id="prompt-loading" role="status">Cargando el contexto del prompt…</p>
    ) : (
      <p className="hint" id="prompt-unavailable">El contexto del prompt no está disponible en este momento.</p>
    );
  }
  return (
    <>
      <label htmlFor="system-prompt">System prompt</label>
      <textarea id="system-prompt" readOnly rows={14} value={preview.system_prompt} />
      <p className="hint">Plantillas {preview.prompt_version} renderizadas por la API para estas opciones.</p>

      <h3>Ejemplos few-shot</h3>
      <div id="few-shot">
        {(preview.examples ?? []).map((example, index) => (
          <p className="example" key={`${example.title}-${index}`}>
            <strong>{example.title}</strong>
            <br />
            <span className="hint">{example.description}</span>
          </p>
        ))}
      </div>
    </>
  );
}

function LastCallMetrics({ metrics, promptVersion }: { metrics: CallMetrics | null; promptVersion?: string }) {
  if (!metrics) {
    return <p className="hint" id="no-metrics">Aún no se ha generado ninguna estimación.</p>;
  }
  const usage = metrics.usage ?? {};
  return (
    <>
      <dl id="last-call">
        <div><dt>Modelo</dt><dd id="metric-model">{metrics.model || "Desconocido"}</dd></div>
        <div><dt>Versión del prompt</dt><dd id="metric-prompt-version">{promptVersion}</dd></div>
        <div><dt>Tokens de entrada</dt><dd id="metric-input-tokens">{formatInteger(usage.input_tokens)}</dd></div>
        <div><dt>Tokens de salida</dt><dd id="metric-output-tokens">{formatInteger(usage.output_tokens)}</dd></div>
        <div><dt>Latencia (ms)</dt><dd id="metric-latency">{formatInteger(metrics.latency_ms)}</dd></div>
        <div><dt>Coste de solicitud</dt><dd id="metric-cost">{formatUsd(metrics.request_cost_usd)}</dd></div>
      </dl>
      <p className="hint" id="metric-cache">{metrics.cache_hit ? "Respuesta de caché" : "Respuesta generada"}</p>
    </>
  );
}
