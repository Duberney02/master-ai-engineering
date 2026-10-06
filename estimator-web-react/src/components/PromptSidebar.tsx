import type { CallMetrics, PromptPreview } from "../api/types";
import { formatInteger, formatUsd } from "../lib/format";

interface Props {
  preview: PromptPreview | null;
  loading?: boolean;
  metrics?: CallMetrics | null;
  promptVersion?: string;
}

// Barra lateral equivalente a la de Streamlit: contexto del prompt, ejemplos few-shot y última llamada.
export function PromptSidebar({ preview, loading = false, metrics = null, promptVersion }: Props) {
  return (
    <>
      <h2>Contexto del prompt</h2>
      <SystemPrompt preview={preview} loading={loading} />
      <h3>Última llamada</h3>
      <LastCallMetrics metrics={metrics} promptVersion={promptVersion} />
    </>
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
