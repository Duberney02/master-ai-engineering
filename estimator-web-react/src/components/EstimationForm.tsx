import { useId, useRef, type ChangeEvent, type FormEvent } from "react";
import { formatInteger, optionsForLabels } from "../lib/format";
import {
  DETAIL_LEVELS, MAX_DESCRIPTION, MAX_UPLOAD_BYTES, MIN_DESCRIPTION, OUTPUT_FORMATS, PROJECT_TYPES,
  PROMPT_VERSIONS, readTxtFile, type FormValues,
} from "../lib/estimationForm";
import { Alert } from "./Alert";

interface Props {
  values: FormValues;
  errors: string[];
  submitting: boolean;
  elapsedSeconds: number;
  onChange: (values: FormValues) => void;
  onSubmit: () => void;
  onUploadError: (message: string) => void;
}

function LoadingIndicator({ active, seconds }: { active: boolean; seconds: number }) {
  return (
    <div id="loading" className={active ? "active" : undefined} role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <div>
        Estimando… <strong id="timer">{active ? seconds : 0} s</strong>{" "}
        <span className="hint">(las transcripciones largas pueden tardar un par de minutos)</span>
      </div>
    </div>
  );
}

export function EstimationForm({ values, errors, submitting, elapsedSeconds, onChange, onSubmit, onUploadError }: Props) {
  const ids = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const set = (field: keyof FormValues) => (event: ChangeEvent<HTMLTextAreaElement | HTMLSelectElement>) =>
    onChange({ ...values, [field]: event.target.value });

  // Lee el .txt en el navegador: su contenido sustituye a la descripción escrita.
  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const result = await readTxtFile(file);
    if (result.ok) {
      onChange({ ...values, description: result.text });
    } else {
      onUploadError(result.error);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!submitting) onSubmit();
  }

  return (
    <>
      {errors.length > 0 && (
        <Alert kind="error" id="form-errors">
          {errors.map((message) => (
            <div key={message}>{message}</div>
          ))}
        </Alert>
      )}

      <form id="estimation-form" onSubmit={handleSubmit} noValidate>
        <div className="card">
          <label htmlFor="description">Descripción del proyecto o transcripción</label>
          <textarea
            id="description"
            value={values.description}
            maxLength={MAX_DESCRIPTION}
            onChange={set("description")}
            placeholder="Qué debe hacer el sistema, para quién y con qué restricciones, o pega la transcripción completa de la reunión."
          />
          <div className="counter">
            <span id="char-count">{Array.from(values.description).length}</span> / {formatInteger(MAX_DESCRIPTION)} caracteres (mínimo {MIN_DESCRIPTION})
          </div>

          <label htmlFor="upload">…o carga una transcripción (.txt)</label>
          <input id="upload" ref={fileInput} type="file" accept=".txt,text/plain" onChange={handleUpload} />
          <div className="hint">
            El contenido del archivo sustituye a la descripción. Máximo {MAX_UPLOAD_BYTES / 1000} KB, codificación UTF-8.
          </div>

          <div className="row">
            <SelectField id={`${ids}-type`} label="Tipo de proyecto" value={values.project_type} options={optionsForLabels(PROJECT_TYPES)} onChange={set("project_type")} />
            <SelectField id={`${ids}-detail`} label="Nivel de detalle" value={values.detail_level} options={optionsForLabels(DETAIL_LEVELS)} onChange={set("detail_level")} />
            <SelectField id={`${ids}-format`} label="Formato de salida" value={values.output_format} options={optionsForLabels(OUTPUT_FORMATS)} onChange={set("output_format")} />
            <SelectField
              id={`${ids}-version`}
              label="Versión del prompt"
              value={values.prompt_version}
              options={PROMPT_VERSIONS.map((version) => ({ label: version, value: version }))}
              onChange={set("prompt_version")}
            />
          </div>

          <button type="submit" id="submit-button" disabled={submitting}>Estimar</button>
          <LoadingIndicator active={submitting} seconds={elapsedSeconds} />
        </div>
      </form>
    </>
  );
}

interface SelectProps {
  id: string;
  label: string;
  value: string;
  options: { label: string; value: string }[];
  onChange: (event: ChangeEvent<HTMLSelectElement>) => void;
}

function SelectField({ id, label, value, options, onChange }: SelectProps) {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={onChange}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </div>
  );
}
