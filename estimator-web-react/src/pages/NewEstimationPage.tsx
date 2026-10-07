import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EstimatorApiError, SessionExpiredError, createSessionEstimation } from "../api/estimatorApi";
import type { EstimationResponse } from "../api/types";
import { Alert } from "../components/Alert";
import { EstimationDetail } from "../components/EstimationDetail";
import { EstimationForm } from "../components/EstimationForm";
import { PromptSidebar } from "../components/PromptSidebar";
import { WithSidebar } from "../components/WithSidebar";
import { useElapsedSeconds } from "../hooks/useElapsedSeconds";
import { useConversation } from "../hooks/useConversation";
import { usePromptPreview } from "../hooks/usePromptPreview";
import { apiAttributes, defaultForm, sessionFormData, validateForm, type FormValues } from "../lib/estimationForm";

/** Estimación mostrada en línea cuando la API no devuelve `estimation_id` (sin enlace permanente). */
interface InlineEstimation {
  estimation: EstimationResponse;
  promptVersion: string;
}

export function NewEstimationPage() {
  const navigate = useNavigate();
  const conversation = useConversation();
  const [values, setValues] = useState<FormValues>(defaultForm);
  const [errors, setErrors] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [inline, setInline] = useState<InlineEstimation | null>(null);
  const elapsedSeconds = useElapsedSeconds(submitting);

  const shown = inline?.estimation.options ?? values;
  const { preview, loading } = usePromptPreview({
    prompt_version: inline?.promptVersion ?? values.prompt_version,
    project_type: shown.project_type,
    detail_level: shown.detail_level,
    output_format: shown.output_format,
  });

  async function submit() {
    const problems = validateForm(values);
    if (problems.length > 0) {
      setErrors(problems);
      return;
    }
    setErrors([]);
    setSubmitting(true);
    try {
      const attributes = apiAttributes(values);
      const sessionId = await conversation.ensureSession();
      const response = await createSessionEstimation(sessionId, sessionFormData(values));
      conversation.recordEstimation(response);
      if (response.estimation_id) {
        navigate(`/estimations/${response.estimation_id}`);
      } else {
        // Historial desactivado o no disponible: se muestra el resultado sin enlace permanente.
        setInline({
          estimation: { ...response, description: attributes.description, options: attributes },
          promptVersion: values.prompt_version,
        });
      }
    } catch (error) {
      if (error instanceof SessionExpiredError) {
        // La API perdió la sesión: se abre otra y el aviso aparece sobre el formulario, que conserva lo escrito.
        await conversation.recoverExpired();
      } else {
        setErrors([error instanceof EstimatorApiError ? error.message : "No se pudo completar la operación."]);
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (inline) {
    return (
      <WithSidebar
        sidebar={<PromptSidebar preview={preview} loading={loading} metrics={inline.estimation.metrics} promptVersion={inline.promptVersion} />}
      >
        <EstimationDetail estimation={inline.estimation} />
        <p>
          <Link to="/estimations">← Historial</Link> · <a href="/" onClick={(event) => { event.preventDefault(); setInline(null); }}>Nueva estimación</a>
        </p>
      </WithSidebar>
    );
  }

  return (
    <WithSidebar sidebar={<PromptSidebar preview={preview} loading={loading} />}>
      <h1>Estimador de proyectos</h1>
      {conversation.notice && <Alert kind="warn" id="conversation-notice">{conversation.notice}</Alert>}
      <EstimationForm
        values={values}
        errors={errors}
        submitting={submitting}
        elapsedSeconds={elapsedSeconds}
        onChange={setValues}
        onSubmit={submit}
        onUploadError={(message) => setErrors([message])}
      />
    </WithSidebar>
  );
}
