import { useCallback, useEffect, useState, type FormEvent } from "react";
import { EstimatorApiError } from "../api/estimatorApi";
import { getSettings, saveSettings } from "../api/settingsApi";
import type { AiSettings } from "../api/types";
import { Alert } from "../components/Alert";
import { PlainPage } from "../components/Layout";
import { usePrimaryModel } from "../hooks/usePrimaryModel";

export const SAVED_MESSAGE = "Modelos actualizados. El cambio aplica desde la siguiente solicitud.";

type Load = { status: "loading" } | { status: "ready"; settings: AiSettings | null };

function messageOf(failure: unknown): string {
  return failure instanceof EstimatorApiError ? failure.message : "No se pudo completar la operación.";
}

function initialValues(settings: AiSettings): Record<string, string> {
  return Object.fromEntries(settings.models.map((model) => [model.key, model.selected]));
}

/** Ajustes del servicio IA: modelos del LLM en tiempo de ejecución. */
export function SettingsPage() {
  const { refresh } = usePrimaryModel();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const apply = useCallback((settings: AiSettings | null) => {
    setLoad({ status: "ready", settings });
    setValues(settings ? initialValues(settings) : {});
  }, []);

  const read = useCallback(async () => {
    setLoad({ status: "loading" });
    try {
      apply(await getSettings());
    } catch (failure) {
      setError(`No se pudo leer la configuración del servicio IA: ${messageOf(failure)}`);
      apply(null);
    }
  }, [apply]);

  useEffect(() => {
    void read();
  }, [read]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      apply(await saveSettings(values));
      setNotice(SAVED_MESSAGE);
      await refresh();
    } catch (failure) {
      setError(failure instanceof EstimatorApiError && failure.status === 422 ? failure.message : messageOf(failure));
    } finally {
      setSaving(false);
    }
  }

  if (load.status === "loading") {
    return <PlainPage><p className="hint" role="status">Cargando los ajustes…</p></PlainPage>;
  }
  const settings = load.settings;

  return (
    <PlainPage>
      <h1>Ajustes del servicio IA</h1>
      {notice && <div className="notice" id="settings-notice" role="status">{notice}</div>}
      {error && <Alert kind="error" id="settings-error">{error}</Alert>}

      {!settings ? (
        <div className="card" id="settings-unavailable">
          <p>No se puede mostrar la configuración ahora mismo. <button type="button" className="link" onClick={() => { setError(null); void read(); }}>Reintentar</button>.</p>
        </div>
      ) : (
        <>
          <p className="hint">
            Los modelos se cambian en tiempo de ejecución: el cambio aplica desde la siguiente solicitud, sin reiniciar el servicio ni tocar <code>.env</code>.
            Un campo vacío usa el valor por defecto. Solo aparecen los modelos de los proveedores con clave configurada.
          </p>
          <form id="settings-form" onSubmit={submit}>
            <div className="card table-scroll">
              <table id="models-table">
                <thead>
                  <tr><th>Uso</th><th>Por defecto</th><th>Vigente</th><th>Modelo</th></tr>
                </thead>
                <tbody>
                  {settings.models.map((model) => (
                    <tr key={model.key} id={`knob-${model.key}`}>
                      <td>
                        <strong>{model.label}</strong>
                        <div className="meta">{model.description}</div>
                      </td>
                      <td><code>{model.default || "—"}</code></td>
                      <td>
                        <code>{model.effective || "—"}</code>
                        {model.overridden && <> <span className="badge parent" title="Hay un override en tiempo de ejecución">override</span></>}
                      </td>
                      <td>
                        <select
                          id={`models_${model.key}`} aria-label={model.label} value={values[model.key] ?? ""}
                          onChange={(event) => setValues((current) => ({ ...current, [model.key]: event.target.value }))}
                        >
                          <option value="">Valor por defecto{model.default ? ` (${model.default})` : ""}</option>
                          {model.options.map((option) => <option key={option} value={option}>{option}</option>)}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button type="submit" disabled={saving}>Guardar</button>
            </div>
          </form>

          <div className="card" id="embedding-model">
            <h2>Modelo de embeddings</h2>
            <p><code>{settings.embedding_model}</code></p>
            <p className="meta">{settings.embedding_model_note || "Solo lectura: cambiarlo invalidaría todos los vectores guardados."}</p>
          </div>
        </>
      )}
    </PlainPage>
  );
}
