import { useEffect, useState, type FormEvent } from "react";
import { getSettings, saveSettings } from "../api/adminApi";
import { EstimatorApiError } from "../api/estimatorApi";
import type { ModelSettings, SettingsField } from "../api/types";
import { AccessRestricted } from "../components/AccessRestricted";
import { Alert } from "../components/Alert";
import { PlainPage } from "../components/Layout";
import { messageOf, useAdminResource } from "../hooks/useAdminResource";
import { useShell } from "../hooks/useShell";

const CONFIRMATION = "Modelos actualizados. El cambio aplica desde la siguiente solicitud.";

/** El selector muestra la sobreescritura vigente; sin ella queda en «valor por defecto» (vacío). */
function initialSelection(settings: ModelSettings): Record<string, string> {
  const selection: Record<string, string> = {};
  for (const field of settings.fields) {
    const value = settings.models[field.key];
    selection[field.key] = value?.overridden && value.effective ? value.effective : "";
  }
  return selection;
}

function optionsOf(field: SettingsField, selected: string): string[] {
  // Una sobreescritura fuera del catálogo filtrado sigue visible para que el operador la vea y pueda restablecerla.
  return selected && !field.options.includes(selected) ? [selected, ...field.options] : field.options;
}

function Display({ value }: { value: string | null | undefined }) {
  return <code>{value ? value : "—"}</code>;
}

interface FormProps {
  settings: ModelSettings;
  notice: string | null;
  failure: string | null;
  saving: boolean;
  onSave: (selection: Record<string, string>) => void;
}

function SettingsForm({ settings, notice, failure, saving, onSave }: FormProps) {
  const [selection, setSelection] = useState(() => initialSelection(settings));
  // Cuando llega lo vigente (tras guardar o tras un rechazo) el formulario refleja el servidor.
  useEffect(() => setSelection(initialSelection(settings)), [settings]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!saving) onSave(selection);
  }

  return (
    <>
      {notice && <Alert kind="warn" id="settings-notice">{notice}</Alert>}
      {failure && <Alert kind="error" id="settings-error">{failure}</Alert>}
      <p className="hint">
        Los modelos se cambian en tiempo de ejecución: el cambio aplica desde la siguiente solicitud, sin reiniciar el
        servicio ni tocar <code>.env</code>. Un campo vacío usa el valor por defecto. Solo aparecen los modelos de los
        proveedores con clave configurada.
      </p>
      <form id="settings-form" onSubmit={submit} noValidate>
        <div className="card table-scroll">
          <table id="models-table">
            <thead>
              <tr><th>Uso</th><th>Por defecto</th><th>Vigente</th><th>Modelo</th></tr>
            </thead>
            <tbody>
              {settings.fields.map((field) => {
                const value = settings.models[field.key];
                const selected = selection[field.key] ?? "";
                return (
                  <tr key={field.key} id={`knob-${field.key}`}>
                    <td>
                      <strong>{field.label}</strong>
                      <div className="meta">{field.description}</div>
                    </td>
                    <td><Display value={value?.default} /></td>
                    <td>
                      <Display value={value?.effective} />
                      {value?.overridden && <span className="badge parent" title="Hay un override en tiempo de ejecución">override</span>}
                    </td>
                    <td>
                      <select
                        id={`models_${field.key}`}
                        aria-label={field.label}
                        value={selected}
                        onChange={(event) => setSelection({ ...selection, [field.key]: event.target.value })}
                      >
                        <option value="">Valor por defecto{value?.default ? ` (${value.default})` : ""}</option>
                        {optionsOf(field, selected).map((option) => (
                          <option key={option} value={option}>{option}</option>
                        ))}
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <button type="submit" disabled={saving}>Guardar</button>
        </div>
      </form>

      <div className="card" id="embedding-model">
        <h2>Modelo de embeddings</h2>
        <p><code>{settings.embedding_model}</code></p>
        <p className="meta">
          {settings.embedding_model_note || "Solo lectura: cambiarlo invalidaría todos los vectores guardados."}
        </p>
      </div>
    </>
  );
}

export function SettingsPage() {
  const loaded = useAdminResource(getSettings);
  const { reportAccess, refreshModel } = useShell();
  const [current, setCurrent] = useState<ModelSettings | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // `loaded` es un objeto nuevo en cada render: la sincronización depende solo de los datos cargados.
  const loadedData = loaded.status === "ready" ? loaded.data : null;
  useEffect(() => {
    if (loadedData) {
      setCurrent(loadedData);
      setUnavailable(null);
    }
  }, [loadedData]);

  async function save(selection: Record<string, string>) {
    setSaving(true);
    setNotice(null);
    setFailure(null);
    try {
      // Cada guardado envía todos los campos; vacío significa «usar el valor por defecto».
      const models: Record<string, string | null> = {};
      for (const [key, value] of Object.entries(selection)) models[key] = value === "" ? null : value;
      setCurrent(await saveSettings(models));
      setNotice(CONFIRMATION);
      refreshModel();
    } catch (error) {
      if (error instanceof EstimatorApiError && error.status === 403) {
        reportAccess("denied");
        setCurrent(null);
        setUnavailable("denied");
        return;
      }
      setFailure(messageOf(error));
      // Tras un rechazo se vuelve a leer lo vigente; si tampoco se puede, la pantalla queda sin formulario.
      try {
        setCurrent(await getSettings());
      } catch {
        setCurrent(null);
        setUnavailable("No se puede mostrar la configuración ahora mismo.");
      }
    } finally {
      setSaving(false);
    }
  }

  if (loaded.status === "denied" || unavailable === "denied") return <AccessRestricted section="Los ajustes de IA" />;

  return (
    <PlainPage>
      <h1>Ajustes del servicio IA</h1>
      {loaded.status === "loading" && <p className="hint" role="status">Cargando los ajustes…</p>}
      {loaded.status === "error" && (
        <div className="card" id="settings-unavailable">
          <Alert kind="error" id="settings-load-error">{loaded.message}</Alert>
          <p>No se puede mostrar la configuración ahora mismo.</p>
          <button type="button" onClick={loaded.reload}>Reintentar</button>
        </div>
      )}
      {loaded.status === "ready" && current === null && (
        <div className="card" id="settings-unavailable">
          {failure && <Alert kind="error" id="settings-error">{failure}</Alert>}
          <p>{unavailable ?? "No se puede mostrar la configuración ahora mismo."}</p>
          <button type="button" onClick={loaded.reload}>Reintentar</button>
        </div>
      )}
      {loaded.status === "ready" && current && (
        <SettingsForm settings={current} notice={notice} failure={failure} saving={saving} onSave={save} />
      )}
    </PlainPage>
  );
}
