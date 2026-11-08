import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getLabOptions, runComparison } from "../api/chunkingApi";
import { EstimatorApiError } from "../api/estimatorApi";
import type { Comparison, LabOptions } from "../api/types";
import { Alert } from "../components/Alert";
import { ChunkingResult, ComparisonMeta } from "../components/ChunkingResult";
import { PlainPage } from "../components/Layout";

export const NO_STRATEGY_MESSAGE = "Selecciona al menos una estrategia.";

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; options: LabOptions };

/** Formulario del Chunking Lab: estrategias (las de pago, opt-in), consultas y top-k. */
export function ChunkingLabPage() {
  const navigate = useNavigate();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [selected, setSelected] = useState<string[]>([]);
  const [queries, setQueries] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const [topK, setTopK] = useState(3);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unsaved, setUnsaved] = useState<Comparison | null>(null);

  useEffect(() => {
    let current = true;
    getLabOptions()
      .then((options) => {
        if (!current) return;
        setSelected(options.default_strategies);
        setTopK(options.default_top_k);
        setLoad({ status: "ready", options });
      })
      .catch((failure: unknown) => {
        if (current) setLoad({ status: "error", message: failure instanceof EstimatorApiError ? failure.message : "No se pudo completar la operación." });
      });
    return () => {
      current = false;
    };
  }, []);

  if (load.status === "loading") {
    return <PlainPage><p className="hint" role="status">Cargando el Chunking Lab…</p></PlainPage>;
  }
  if (load.status === "error") {
    return <PlainPage><h1>Chunking Lab</h1><Alert kind="error" id="lab-error">{load.message}</Alert></PlainPage>;
  }

  const { options } = load;
  const paidSelected = options.strategies.some((strategy) => strategy.paid && selected.includes(strategy.name));

  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (running) return;
    if (selected.length === 0) {
      setError(NO_STRATEGY_MESSAGE);
      return;
    }
    setError(null);
    setUnsaved(null);
    setRunning(true);
    try {
      const own = custom.split("\n").map((line) => line.trim());
      const comparison = await runComparison({
        strategies: options.strategies.filter((strategy) => selected.includes(strategy.name)).map((strategy) => strategy.name),
        queries: [...queries, ...own].filter((query, index, all) => query !== "" && all.indexOf(query) === index),
        top_k: Math.min(Math.max(Math.trunc(topK) || 1, 1), 10),
      });
      if (comparison.saved) navigate(`/rag/chunking_comparisons/${comparison.id}`);
      else setUnsaved(comparison);
    } catch (failure) {
      setError(failure instanceof EstimatorApiError ? failure.message : "No se pudo completar la operación.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <PlainPage>
      <h1>Chunking Lab</h1>
      <p className="hint">
        Compara estrategias de chunking sobre los presupuestos históricos. Cada ejecución se guarda:{" "}
        <Link to="/rag/chunking_comparisons">consulta el historial</Link> antes de repetir una de pago.
      </p>
      {error && <Alert kind="error" id="lab-form-error">{error}</Alert>}

      <form id="lab-form" onSubmit={submit}>
        <div className="card">
          <h2>Estrategias</h2>
          <p className="hint">Las gratuitas vienen marcadas. Las de pago llaman a un LLM o a embeddings durante el chunking: son opcionales, cuestan dinero y pueden tardar minutos.</p>
          {options.strategies.map((strategy) => (
            <div className="strategy" key={strategy.name}>
              <input
                type="checkbox" id={`strategy_${strategy.name}`} value={strategy.name} data-paid={String(strategy.paid)}
                checked={selected.includes(strategy.name)} onChange={() => setSelected((list) => toggle(list, strategy.name))}
              />
              <div>
                <label htmlFor={`strategy_${strategy.name}`}>
                  {strategy.label} <span className={`badge ${strategy.cost_tier}`}>{strategy.cost_label}</span>
                  {strategy.key_name && <> <span className="badge">requiere {strategy.key_name}</span></>}
                </label>
                <p className="meta">{strategy.description}</p>
              </div>
            </div>
          ))}
          {paidSelected && (
            <Alert kind="warn" id="paid-warning">
              Has marcado estrategias de pago: llamarán a proveedores externos con tu clave del servicio IA y pueden tardar varios minutos (hasta {options.compare_timeout_seconds} s).
            </Alert>
          )}
        </div>

        <div className="card">
          <h2>Consultas</h2>
          <p className="hint">Sin consultas solo se calculan las estadísticas. Con consultas se compara qué chunks recupera cada estrategia (requiere <code>OPENAI_API_KEY</code> en el servicio).</p>
          {options.sample_queries.map((query, index) => (
            <div className="strategy" key={query}>
              <input
                type="checkbox" id={`query_${index}`} value={query}
                checked={queries.includes(query)} onChange={() => setQueries((list) => toggle(list, query))}
              />
              <label htmlFor={`query_${index}`}>{query}</label>
            </div>
          ))}
          <label htmlFor="custom_queries">Consultas propias (una por línea)</label>
          <textarea id="custom_queries" rows={3} value={custom} onChange={(event) => setCustom(event.target.value)} />

          <label htmlFor="top_k">Resultados por consulta (top-k)</label>
          <input
            type="number" id="top_k" min={1} max={10} value={topK}
            onChange={(event) => setTopK(Number(event.target.value))}
          />
        </div>

        <button type="submit" id="lab-submit" disabled={running}>Comparar</button>
        <div id="loading" className={running ? "active" : ""} role="status" aria-live="polite">
          {running && <><div className="spinner" /><span>Calculando… las estrategias de pago pueden tardar varios minutos.</span></>}
        </div>
      </form>

      {unsaved && (
        <>
          <Alert kind="warn" id="lab-unsaved">{unsaved.notice ?? "La comparación se calculó, pero no se pudo guardar en el historial."}</Alert>
          <h2>Resultado de la comparación</h2>
          <ComparisonMeta comparison={unsaved} />
          <ChunkingResult comparison={unsaved} />
        </>
      )}
    </PlainPage>
  );
}
