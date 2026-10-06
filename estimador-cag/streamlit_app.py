"""Cliente HTTP del estimador: formulario tipado con respuesta en streaming; no necesita claves de proveedores."""

import os
import time

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from app.prompts.loader import render_estimation_prompt
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
from app.streamlit_client import PROMPT_VERSIONS, EstimationStreamError, request_structured_estimation
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
# Solo sirve para mostrar el prompt de sistema antes de la primera solicitud.
PREVIEW_REQUEST = EstimationRequest(
    description="Vista previa del prompt con los valores por defecto del formulario.",
    project_type=list(ProjectType)[0],
    detail_level=list(DetailLevel)[DEFAULT_DETAIL_INDEX],
    output_format=list(OutputFormat)[0],
)


def _label(value: str) -> str:
    return next(label for member, label in LABELS.items() if member.value == value)


def _validation_message(exc: ValidationError) -> str:
    if any(error["loc"] == ("description",) for error in exc.errors()):
        return f"La descripción debe tener entre {MIN_DESCRIPTION_CHARS} y {MAX_DESCRIPTION_CHARS} caracteres."
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


def _request_summary(request: EstimationRequest, prompt_version: str) -> str:
    text = request.description
    if len(text) > SUMMARY_PREVIEW_CHARS:
        # Una transcripción de 80 000 caracteres no debe llenar el historial del chat.
        text = f"{text[:SUMMARY_PREVIEW_CHARS].rstrip()}… ({len(request.description):,} caracteres)"
    return (
        f"**{_label(request.project_type.value)}** · detalle {_label(request.detail_level.value).lower()}"
        f" · {_label(request.output_format.value).lower()} · prompt {prompt_version}\n\n{text}"
    )


st.set_page_config(page_title="Estimador de proyectos")
st.title("Estimador de proyectos")

st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_metrics", None)
st.session_state.setdefault("last_prompt", (PREVIEW_REQUEST, PROMPT_VERSIONS[0]))

if st.sidebar.button("Borrar historial"):
    st.session_state.messages = []
    st.session_state.last_metrics = None
    st.rerun()

with st.form("estimation_form"):
    description = st.text_area(
        "Descripción del proyecto",
        max_chars=MAX_DESCRIPTION_CHARS,
        placeholder=(
            "Qué debe hacer el sistema, para quién y con qué restricciones "
            f"(mínimo {MIN_DESCRIPTION_CHARS} caracteres), o pega una transcripción larga."
        ),
    )
    transcript_file = st.file_uploader(
        "…o carga una transcripción (.txt, sustituye a la descripción)", type="txt"
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
    try:
        if upload_error:
            raise ValueError(upload_error)
        request = EstimationRequest(
            description=text.strip(),
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
        )
    except ValueError as exc:
        # ValidationError de pydantic es una subclase de ValueError.
        st.error(_validation_message(exc) if isinstance(exc, ValidationError) else str(exc))
    else:
        st.session_state.last_metrics = None
        st.session_state.last_prompt = (request, prompt_version)
        summary = _request_summary(request, prompt_version)
        st.session_state.messages.append({"role": "user", "content": summary})
        with st.chat_message("user"):
            st.markdown(summary)

        with st.chat_message("assistant"):
            started = time.monotonic()
            try:
                with st.spinner("Estimando… las transcripciones largas pueden tardar un par de minutos."):
                    estimation, metadata = request_structured_estimation(request, api_url, prompt_version)
            except EstimationStreamError as exc:
                st.error(str(exc))
            else:
                result = estimation.model_dump(mode="json")
                elapsed = time.monotonic() - started
                _show_result(result)
                st.caption(f"Tiempo: {elapsed:.1f} s")
                st.session_state.messages.append(
                    {"role": "assistant", "result": result, "elapsed": elapsed}
                )
                st.session_state.last_metrics = metadata.model_dump()

# La barra lateral se dibuja al final para reflejar la solicitud recién enviada.
prompt_request, prompt_request_version = st.session_state.last_prompt
system_prompt, _ = render_estimation_prompt(prompt_request, version=prompt_request_version)

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
