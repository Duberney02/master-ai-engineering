"""Cliente HTTP del estimador: formulario tipado con respuesta en streaming; no necesita claves de proveedores."""

import os

import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from app.prompts.loader import render_estimation_prompt
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.streamlit_client import PROMPT_VERSIONS, EstimationStreamError, stream_structured_estimation
from app.streamlit_support import few_shot_examples

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
        return "La descripción debe tener entre 20 y 2000 caracteres."
    return "Revisa los campos del formulario."


def _request_summary(request: EstimationRequest, prompt_version: str) -> str:
    return (
        f"**{_label(request.project_type.value)}** · detalle {_label(request.detail_level.value).lower()}"
        f" · {_label(request.output_format.value).lower()} · prompt {prompt_version}\n\n{request.description}"
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
        max_chars=2000,
        placeholder="Qué debe hacer el sistema, para quién y con qué restricciones (mínimo 20 caracteres).",
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
        st.markdown(msg["content"])

if submitted:
    try:
        request = EstimationRequest(
            description=description.strip(),
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
        )
    except ValidationError as exc:
        st.error(_validation_message(exc))
    else:
        st.session_state.last_metrics = None
        st.session_state.last_prompt = (request, prompt_version)
        summary = _request_summary(request, prompt_version)
        st.session_state.messages.append({"role": "user", "content": summary})
        with st.chat_message("user"):
            st.markdown(summary)

        with st.chat_message("assistant"):
            metrics = {}
            try:
                response = st.write_stream(
                    stream_structured_estimation(request, api_url, metrics, prompt_version)
                )
            except EstimationStreamError as exc:
                st.error(str(exc))
                st.caption("El texto parcial, si aparece, no es una estimación completa.")
            else:
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.session_state.last_metrics = metrics

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
