"""Interfaz conversacional del estimador CAG: `streamlit run streamlit_app.py`.

Es un cliente HTTP de la API (variable `ESTIMATOR_API_BASE_URL`): no importa el
backend, no construye prompts, no necesita claves de proveedores ni acceso a Redis.
"""

import streamlit as st

from estimator_client import api
from estimator_client.presentation import (
    PREPROCESSING_LABELS,
    detail_lines,
    is_truncated,
    summary_metrics,
)

st.set_page_config(page_title="Estimador CAG")
st.title("Estimador CAG")

st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_metadata", None)
st.session_state.setdefault("prompt_cache", {})

try:
    client = api.build_client()
except ValueError as exc:
    st.error(f"Configuración del cliente no válida: {exc}")
    st.stop()


def _load_context(params: dict) -> tuple[dict | None, str | None]:
    """Contexto público del servidor (prompt, ejemplos, modelos), cacheado por sesión."""
    key = tuple(sorted(params.items()))
    cache = st.session_state.prompt_cache
    if key not in cache:
        try:
            cache[key] = client.context(params)
        except api.ApiError as exc:
            return None, exc.message
    return cache[key], None


# --- Opciones de la solicitud --------------------------------------------------------
st.sidebar.header("Opciones")
preprocessing = st.sidebar.selectbox(
    "Preprocesamiento",
    list(PREPROCESSING_LABELS),
    format_func=PREPROCESSING_LABELS.get,
)
example_format = st.sidebar.selectbox("Formato de ejemplos", ["markdown", "json", "narrative"])
use_examples = st.sidebar.checkbox("Incluir ejemplos históricos", value=True)
num_examples = st.sidebar.slider("Número de ejemplos", 0, 5, 2, disabled=not use_examples)

options = {
    "preprocessing": preprocessing,
    "example_format": example_format,
    "num_examples": num_examples,
    "use_examples": use_examples,
}
context, context_error = _load_context(options)


# --- Historial -----------------------------------------------------------------------
def _render_status(message: dict) -> None:
    status = message.get("status", "completed")
    if status == "error":
        st.error(message.get("error") or "La generación falló.")
    elif status == "interrupted":
        st.warning(message.get("error") or "La generación se interrumpió.")
    elif status == "truncated":
        st.warning("La respuesta se truncó por el límite de tokens: la estimación está incompleta.")


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("content"):
            st.markdown(msg["content"])
        if msg["role"] == "assistant":
            _render_status(msg)

prompt = st.chat_input("Pega aquí la transcripción de la reunión...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        entry: dict = {"role": "assistant", "content": "", "status": "error"}
        try:
            stream = client.open_stream({"transcription": prompt, **options})
        except api.ApiValidationError as exc:
            entry["error"] = "Solicitud no válida: " + ("; ".join(exc.details) or exc.message)
        except api.ApiConnectionError as exc:
            entry["error"] = f"No se pudo contactar con la API: {exc.message}"
        except api.ApiServerError as exc:
            entry["error"] = f"La API devolvió un error (HTTP {exc.status}): {exc.message}"
        else:
            st.write_stream(stream.text_chunks())
            outcome = stream.outcome
            entry["content"] = outcome.text
            if outcome.completed:
                entry["status"] = "truncated" if is_truncated(outcome.metadata) else "completed"
                st.session_state.last_metadata = outcome.metadata
            elif outcome.status == "error":
                err = outcome.error or {}
                partial = " Lo mostrado es una respuesta parcial, no una estimación válida." if outcome.text else ""
                entry["error"] = f"Error durante la generación: {err.get('message', 'desconocido')}.{partial}"
            else:
                partial = " Lo mostrado es parcial." if outcome.text else ""
                entry["status"] = "interrupted"
                entry["error"] = f"Generación interrumpida: {outcome.interruption_reason}.{partial}"
            if outcome.extracted_requirements:
                with st.expander("Requisitos extraídos (fase 1)"):
                    st.markdown(outcome.extracted_requirements)
        _render_status(entry)
    st.session_state.messages.append(entry)

client.close()

# --- Contexto CAG (servido por la API) ---------------------------------------------
st.sidebar.header("Contexto CAG")
if context_error:
    st.sidebar.error(context_error)
elif context:
    models = context.get("models", {})
    st.sidebar.caption(
        f"Modelo primario: {models.get('primary')} · secundario: {models.get('fallback') or 'ninguno'}"
    )
    st.sidebar.text_area("System prompt", value=context["system_prompt"], height=300, disabled=True)
    st.sidebar.subheader("Ejemplos históricos")
    if not context["examples"]:
        st.sidebar.caption("Sin ejemplos en el prompt.")
    for ex in context["examples"]:
        st.sidebar.markdown(f"**{ex['title']}**")
        st.sidebar.caption(ex["meeting_summary"])

st.sidebar.subheader("Última llamada")
last = st.session_state.last_metadata
if last:
    for label, value in summary_metrics(last):
        st.sidebar.metric(label, value)
    for line in detail_lines(last):
        st.sidebar.caption(line)
else:
    st.sidebar.caption("Aún no se ha generado ninguna estimación.")
