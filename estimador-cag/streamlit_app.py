"""Cliente HTTP del estimador: conversación con memoria (sesión), formulario tipado y adjuntos.

Crea una sesión al cargar la página y envía cada estimación a `/api/v1/sessions/{id}/estimate`; no
necesita claves de proveedores.
"""

import os
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from app.prompts.loader import render_system_prompt
from app.schemas import (
    MAX_DESCRIPTION_CHARS,
    MIN_DESCRIPTION_CHARS,
    DetailLevel,
    EstimationRequest,
    EstimationResult,
    OutputFormat,
    ProjectType,
)
from app.schemas.project_estimation import OUT_OF_SCOPE_PREFIX
from app.services.sessions import ProjectMetadata
from app.streamlit_client import (
    PROMPT_VERSIONS,
    EstimationStreamError,
    SessionExpiredError,
    create_session,
    request_session_estimation,
)
from app.streamlit_support import decode_transcript, few_shot_examples

load_dotenv()
try:
    api_url = os.getenv("ESTIMATOR_API_BASE_URL") or st.secrets.get("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
except Exception:
    api_url = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")

LABELS = {
    ProjectType.MOBILE_APP: "App móvil",
    ProjectType.WEB_SAAS: "SaaS web",
    ProjectType.INTERNAL_TOOL: "Herramienta interna",
    ProjectType.DATA_PIPELINE: "Pipeline de datos",
    DetailLevel.SUMMARY: "Resumen",
    DetailLevel.MEDIUM: "Medio",
    DetailLevel.DETAILED: "Detallado",
    OutputFormat.PHASES_TABLE: "Tabla de fases",
    OutputFormat.LINE_ITEMS: "Partidas",
    OutputFormat.NARRATIVE: "Narrativa",
}
DEFAULT_DETAIL_INDEX = 1  # "Medio"
# Solo sirve para mostrar el prompt de sistema: no incluye la descripción.
PREVIEW_DESCRIPTION = "Vista previa del prompt con los valores elegidos en el formulario."
PREVIEW_REQUEST = EstimationRequest(
    description=PREVIEW_DESCRIPTION,
    project_type=list(ProjectType)[0],
    detail_level=list(DetailLevel)[DEFAULT_DETAIL_INDEX],
    output_format=list(OutputFormat)[0],
)
RANGE_MESSAGE = f"La descripción debe tener entre {MIN_DESCRIPTION_CHARS} y {MAX_DESCRIPTION_CHARS} caracteres."
EXPIRED_MESSAGE = "La conversación anterior expiró en el servidor; se inició una nueva. Vuelve a enviar tu mensaje."


def _label(value: str) -> str:
    return next(label for member, label in LABELS.items() if member.value == value)


def _validation_message(exc: ValidationError) -> str:
    if any(error["loc"] == ("description",) for error in exc.errors()):
        return RANGE_MESSAGE
    return "Revisa los campos del formulario."


def _show_result(result: dict) -> None:
    """Presenta un `EstimationResult`; fuera de alcance se muestra como no estimable, sin cifras."""
    data = EstimationResult.model_validate(result)
    if data.out_of_scope:
        reason = data.summary.removeprefix(OUT_OF_SCOPE_PREFIX).strip()
        st.warning(f"**No estimable.** {reason}")
        st.caption(f"Confianza {data.confidence_pct}% (por debajo del 30% no se ofrecen cifras).")
        return
    st.markdown(data.summary)
    confidence, duration, cost = st.columns(3)
    confidence.metric("Confianza", f"{data.confidence_pct}%")
    duration.metric("Duración total", f"{data.total_duration_weeks:g} semanas")
    cost.metric("Coste total", f"{data.total_cost_eur:,.2f} EUR")
    st.dataframe(
        pd.DataFrame(
            [
                {"Fase": p.name, "Descripción": p.description,
                 "Semanas": p.duration_weeks, "Coste (EUR)": p.cost_eur}
                for p in data.phases
            ]
        ),
        hide_index=True,
    )


SUMMARY_PREVIEW_CHARS = 600


def _request_summary(
    text: str, project_type: str, detail_level: str, output_format: str, prompt_version: str,
    attachment_names: list[str],
) -> str:
    shown = text
    if len(shown) > SUMMARY_PREVIEW_CHARS:
        # Una transcripción de 80 000 caracteres no debe llenar el historial del chat.
        shown = f"{shown[:SUMMARY_PREVIEW_CHARS].rstrip()}… ({len(text):,} caracteres)"
    summary = (
        f"**{_label(project_type)}** · detalle {_label(detail_level).lower()}"
        f" · {_label(output_format).lower()} · prompt {prompt_version}\n\n{shown}"
    )
    if attachment_names:
        summary += "\n\nAdjuntos: " + ", ".join(f"`{name}`" for name in attachment_names)
    return summary.strip()


def _new_conversation() -> None:
    """Crea otra sesión en la API y reinicia el historial, los metadatos y las métricas."""
    st.session_state.session_id = create_session(api_url)
    st.session_state.messages = []
    st.session_state.last_metrics = None
    st.session_state.project_metadata = ProjectMetadata().model_dump()


def _show_project_metadata(metadata: dict) -> None:
    facts = ProjectMetadata.model_validate(metadata)
    if facts.is_empty():
        st.sidebar.caption("Aún no hay datos del proyecto: se irán recogiendo durante la conversación.")
        return
    st.sidebar.markdown(f"**Nombre:** {facts.project_name or '—'}")
    st.sidebar.markdown(f"**Equipo supuesto:** {facts.assumed_team_size or '—'}")
    st.sidebar.markdown(f"**Tecnologías:** {', '.join(facts.mentioned_technologies) or '—'}")
    st.sidebar.markdown(f"**Alcance acordado:** {facts.agreed_scope or '—'}")


st.set_page_config(page_title="Estimador de proyectos")
st.title("Estimador de proyectos")

st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_metrics", None)
st.session_state.setdefault("last_prompt", (PREVIEW_REQUEST, PROMPT_VERSIONS[0]))
st.session_state.setdefault("project_metadata", ProjectMetadata().model_dump())

# La sesión se crea una vez por pestaña y se conserva en `session_state` entre recargas de la app.
if st.session_state.get("session_id") is None:
    try:
        st.session_state.session_id = create_session(api_url)
    except EstimationStreamError as exc:
        st.error(str(exc))
        st.stop()

if st.sidebar.button("Nueva conversación"):
    try:
        _new_conversation()
    except EstimationStreamError as exc:
        st.session_state.session_id = None
        st.error(str(exc))
        st.stop()
    st.rerun()

with st.form("estimation_form"):
    description = st.text_area(
        "Descripción del proyecto o mensaje",
        max_chars=MAX_DESCRIPTION_CHARS,
        placeholder=(
            "Qué debe hacer el sistema, para quién y con qué restricciones "
            f"(mínimo {MIN_DESCRIPTION_CHARS} caracteres), o pega una transcripción larga. "
            "Los mensajes siguientes se interpretan dentro de la misma conversación."
        ),
    )
    transcript_file = st.file_uploader(
        "…o carga una transcripción (.txt, sustituye a la descripción)", type="txt"
    )
    attachments = st.file_uploader(
        "Adjuntos (PDF o Word, varios a la vez; su texto se añade a la transcripción)",
        type=["pdf", "docx"],
        accept_multiple_files=True,
    )
    project_type = st.selectbox("Tipo de proyecto", [t.value for t in ProjectType], format_func=_label)
    left, right = st.columns(2)
    detail_level = left.selectbox(
        "Nivel de detalle", [d.value for d in DetailLevel], index=DEFAULT_DETAIL_INDEX, format_func=_label
    )
    output_format = right.selectbox(
        "Formato de salida", [f.value for f in OutputFormat], format_func=_label
    )
    prompt_version = st.selectbox("Versión del prompt", PROMPT_VERSIONS)
    submitted = st.form_submit_button("Estimar")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if "result" in msg:
            _show_result(msg["result"])
            if "elapsed" in msg:
                st.caption(f"Tiempo: {msg['elapsed']:.1f} s")
        else:
            st.markdown(msg["content"])

if submitted:
    text = description
    upload_error = None
    if transcript_file is not None:
        try:
            text = decode_transcript(transcript_file.getvalue())
        except ValueError as exc:
            upload_error = str(exc)
    text = text.strip()
    try:
        if upload_error:
            raise ValueError(upload_error)
        if attachments:
            # Con adjuntos el texto puede ser corto: el servidor valida la longitud del conjunto.
            if len(text) > MAX_DESCRIPTION_CHARS:
                raise ValueError(RANGE_MESSAGE)
        else:
            # Opciones tipadas y longitud, con las mismas reglas que el servicio.
            EstimationRequest(
                description=text, project_type=project_type,
                detail_level=detail_level, output_format=output_format,
            )
    except ValueError as exc:
        # ValidationError de pydantic es una subclase de ValueError.
        st.error(_validation_message(exc) if isinstance(exc, ValidationError) else str(exc))
    else:
        st.session_state.last_metrics = None
        st.session_state.last_prompt = (
            EstimationRequest(
                description=PREVIEW_DESCRIPTION, project_type=project_type,
                detail_level=detail_level, output_format=output_format,
            ),
            prompt_version,
        )
        files = [(file.name, file.getvalue()) for file in attachments]
        summary = _request_summary(
            text, project_type, detail_level, output_format, prompt_version, [name for name, _ in files]
        )
        st.session_state.messages.append({"role": "user", "content": summary})
        with st.chat_message("user"):
            st.markdown(summary)

        with st.chat_message("assistant"):
            started = time.monotonic()
            try:
                with st.spinner("Estimando… las transcripciones largas pueden tardar un par de minutos."):
                    response = request_session_estimation(
                        api_url, st.session_state.session_id, transcript=text, attachments=files,
                        project_type=project_type, detail_level=detail_level,
                        output_format=output_format, prompt_version=prompt_version,
                    )
            except SessionExpiredError:
                # El servidor perdió la sesión (reinicio o caducidad): se abre otra y se avisa.
                try:
                    _new_conversation()
                    st.warning(EXPIRED_MESSAGE)
                except EstimationStreamError as exc:
                    st.session_state.session_id = None
                    st.error(str(exc))
            except EstimationStreamError as exc:
                st.error(str(exc))
            else:
                result = response.result.model_dump(mode="json")
                elapsed = time.monotonic() - started
                _show_result(result)
                st.caption(f"Tiempo: {elapsed:.1f} s")
                st.session_state.messages.append(
                    {"role": "assistant", "result": result, "elapsed": elapsed}
                )
                st.session_state.last_metrics = (
                    response.metrics.model_dump() | {"prompt_version": response.prompt_version}
                    if response.metrics else None
                )
                st.session_state.project_metadata = response.project_metadata.model_dump()

# La barra lateral se dibuja al final para reflejar la solicitud recién enviada.
prompt_request, prompt_request_version = st.session_state.last_prompt
# Es el prompt que recibirá el modelo en el siguiente turno: incluye los metadatos ya conocidos.
system_prompt = render_system_prompt(
    prompt_request, prompt_request_version, ProjectMetadata.model_validate(st.session_state.project_metadata)
)

st.sidebar.header("Metadatos del proyecto")
_show_project_metadata(st.session_state.project_metadata)

st.sidebar.header("Contexto del prompt")
st.sidebar.text_area("System prompt", value=system_prompt, height=300, disabled=True)
st.sidebar.caption(
    f"Plantillas {prompt_request_version} de esta versión del cliente, "
    "renderizadas para la última solicitud."
)

st.sidebar.subheader("Ejemplos few-shot")
for title, example_description in few_shot_examples(system_prompt):
    st.sidebar.markdown(f"**{title}**")
    st.sidebar.caption(example_description)

st.sidebar.subheader("Última llamada")
last_metrics = st.session_state.last_metrics
if last_metrics:
    usage = last_metrics.get("usage", {})
    st.sidebar.metric("Modelo", last_metrics.get("model", "Desconocido"))
    st.sidebar.metric("Versión del prompt", last_metrics.get("prompt_version", "—"))
    st.sidebar.metric("Tokens de entrada", usage.get("input_tokens", 0))
    st.sidebar.metric("Tokens de salida", usage.get("output_tokens", 0))
    st.sidebar.metric("Latencia (ms)", last_metrics.get("latency_ms", 0))
    cost = last_metrics.get("request_cost_usd")
    st.sidebar.metric("Coste de solicitud (USD)", "Sin tarifa" if cost is None else f"{cost:.6f}")
    st.sidebar.caption("Respuesta de caché" if last_metrics.get("cache_hit") else "Respuesta generada")
else:
    st.sidebar.caption("Aún no se ha generado ninguna estimación.")
