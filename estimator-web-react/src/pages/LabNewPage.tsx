import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getLabOptions, runComparison } from "../api/adminApi";
import { EstimatorApiError } from "../api/estimatorApi";
import type { ComparisonDetail, LabOptions } from "../api/types";
import { AccessRestricted } from "../components/AccessRestricted";
import { Alert } from "../components/Alert";
import { ComparisonView } from "../components/ComparisonView";
import { PlainPage } from "../components/Layout";
import { messageOf, useAdminResource } from "../hooks/useAdminResource";
import { useElapsedSeconds } from "../hooks/useElapsedSeconds";
import { useShell } from "../hooks/useShell";

interface FormState {
  strategies: string[];
  queries: string[];
  customQueries: string;
  topK: string;
}

function initialState(options: LabOptions): FormState {
  return {
    strategies: options.strategies.filter((strategy) => strategy.default_checked).map((strategy) => strategy.name),
    queries: [],
    customQueries: "",
    topK: String(options.top_k.default),
  };
}

function toggle(list: string[], value: string, on: boolean): string[] {
  return on ? [...list.filter((item) => item !== value), value] : list.filter((item) => item !== value);
}

interface Props {
  options: LabOptions;
}

function LabForm({ options }: Props) {
  const navigate = useNavigate();
  const { reportAccess } = useShell();
  const [state, setState] = useState(() => initialState(options));
  const [errors, setErrors] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [inline, setInline] = useState<ComparisonDetail | null>(null);
  const [denied, setDenied] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const elapsed = useElapsedSeconds(submitting);

  // Salir de la pantalla cancela la comparación en curso: Go cierra la solicitud a IA y no se guarda nada.
  useEffect(() => () => controller.current?.abort(), []);

  const paid = options.strategies.filter((strategy) => strategy.cost_tier !== "free" && state.strategies.includes(strategy.name));
  const keys = [...new Set(paid.map((strategy) => strategy.key_name).filter((name): name is string => name !== null))];

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const request: Parameters<typeof runComparison>[0] = {
      strategies: state.strategies, queries: state.queries, custom_queries: state.customQueries,
    };
    const topK = state.topK.trim();
    if (topK !== "") {
      // Go acepta enteros y los acota a 1–10; decimales o exponentes se rechazan con 422.
      if (!/^-?\d+$/.test(topK)) {
        setErrors([`Los resultados por consulta (top-k) deben ser un entero entre ${options.top_k.min} y ${options.top_k.max}.`]);
        return;
      }
      // Un entero fuera del rango seguro de JavaScript se acota aquí: serializado perdería su forma entera (1e+23).
      const parsed = Number(topK);
      request.top_k = Number.isSafeInteger(parsed) ? parsed : topK.startsWith("-") ? options.top_k.min : options.top_k.max;
    }
    if (state.strategies.length === 0) {
      setErrors(["Selecciona al menos una estrategia."]);
      return;
    }
    setErrors([]);
    setSubmitting(true);
    const abort = new AbortController();
    controller.current = abort;
    try {
      const comparison = await runComparison(request, abort.signal);
      reportAccess("allowed");
      if (comparison.id) {
        navigate(`/rag/chunking-comparisons/${comparison.id}`);
      } else {
        // Calculada pero no guardada: se muestra igualmente, con su aviso, en lugar de perderla.
        setInline(comparison);
      }
    } catch (error) {
      if (abort.signal.aborted) return; // cancelada: sin resultado parcial ni reenvío, el formulario se rehabilita
      if (error instanceof EstimatorApiError && error.status === 403) {
        reportAccess("denied");
        setDenied(true);
      } else {
        // El formulario conserva todo lo marcado y escrito.
        setErrors([messageOf(error)]);
      }
    } finally {
      controller.current = null;
      setSubmitting(false);
    }
  }

  if (denied) return <AccessRestricted section="El Chunking Lab" />;
  if (inline) {
    return (
      <PlainPage>
        <ComparisonView comparison={inline} />
      </PlainPage>
    );
  }

  const textChange = (field: "customQueries" | "topK") => (event: ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) =>
    setState({ ...state, [field]: event.target.value });

  return (
    <PlainPage>
      <h1>Chunking Lab</h1>
      <p className="hint">
        Compara estrategias de chunking sobre presupuestos históricos. Cada ejecución se guarda:{" "}
        <Link to="/rag/chunking-comparisons">consulta el historial</Link> antes de repetir una de pago.
      </p>
      {errors.length > 0 && (
        <Alert kind="error" id="lab-errors">
          {errors.map((message) => <div key={message}>{message}</div>)}
        </Alert>
      )}
      <form id="lab-form" onSubmit={submit} noValidate>
        <div className="card">
          <h2>Estrategias</h2>
          <p className="hint">
            Las gratuitas vienen marcadas. Las de pago llaman a un LLM o a embeddings durante el chunking: son opcionales,
            cuestan dinero y pueden tardar minutos.
          </p>
          {options.strategies.map((strategy) => (
            <div className="strategy" key={strategy.name}>
              <input
                type="checkbox"
                id={`strategy_${strategy.name}`}
                checked={state.strategies.includes(strategy.name)}
                onChange={(event) => setState({ ...state, strategies: toggle(state.strategies, strategy.name, event.target.checked) })}
              />
              <div>
                <label htmlFor={`strategy_${strategy.name}`}>
                  {strategy.label}
                  <span className={`badge ${strategy.cost_tier}`}>{strategy.cost_label}</span>
                  {strategy.key_name && <span className="badge">requiere {strategy.key_name}</span>}
                </label>
                <p className="meta">{strategy.description}</p>
              </div>
            </div>
          ))}
          {paid.length > 0 && (
            <Alert kind="warn" id="paid-warning">
              Has marcado estrategias de pago: llamarán a proveedores externos con la clave del servicio IA
              {keys.length > 0 && <> ({keys.join(", ")})</>} y pueden tardar varios minutos (hasta {options.compare_timeout_seconds} s).
            </Alert>
          )}
        </div>

        <div className="card">
          <h2>Consultas</h2>
          <p className="hint">
            Sin consultas solo se calculan las estadísticas. Con consultas se compara qué chunks recupera cada estrategia
            (requiere <code>OPENAI_API_KEY</code> en el servicio).
          </p>
          {options.sample_queries.map((query, index) => (
            <div className="strategy" key={query}>
              <input
                type="checkbox"
                id={`query_${index}`}
                checked={state.queries.includes(query)}
                onChange={(event) => setState({ ...state, queries: toggle(state.queries, query, event.target.checked) })}
              />
              <label htmlFor={`query_${index}`}>{query}</label>
            </div>
          ))}
          <label htmlFor="custom_queries">Consultas propias (una por línea)</label>
          <textarea id="custom_queries" rows={3} value={state.customQueries} onChange={textChange("customQueries")} />

          <label htmlFor="top_k">Resultados por consulta (top-k)</label>
          <input
            type="number" id="top_k" value={state.topK} min={options.top_k.min} max={options.top_k.max} step={1}
            onChange={textChange("topK")}
          />
        </div>

        <button type="submit" id="lab-submit" disabled={submitting}>Comparar</button>
        {submitting && (
          <button type="button" className="secondary" id="lab-cancel" onClick={() => controller.current?.abort()}>Cancelar</button>
        )}
        <div id="loading" className={submitting ? "active" : undefined} role="status" aria-live="polite">
          <div className="spinner" aria-hidden="true" />
          <span>Calculando… <strong>{submitting ? elapsed : 0} s</strong> las estrategias de pago pueden tardar varios minutos.</span>
        </div>
      </form>
    </PlainPage>
  );
}

export function LabNewPage() {
  const resource = useAdminResource(getLabOptions);
  if (resource.status === "denied") return <AccessRestricted section="El Chunking Lab" />;
  if (resource.status === "ready") return <LabForm options={resource.data} />;
  return (
    <PlainPage>
      <h1>Chunking Lab</h1>
      {resource.status === "loading" && <p className="hint" role="status">Cargando las opciones…</p>}
      {resource.status === "error" && (
        <>
          <Alert kind="error" id="lab-options-error">{resource.message}</Alert>
          <button type="button" onClick={resource.reload}>Reintentar</button>
        </>
      )}
    </PlainPage>
  );
}
