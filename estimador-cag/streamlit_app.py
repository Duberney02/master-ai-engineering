"""Cliente HTTP del estimador; no necesita claves de proveedores."""

import os

import streamlit as st
from dotenv import load_dotenv

from app.context.examples import select_examples
from app.schemas.estimation import DEFAULT_NUM_EXAMPLES
from app.services.llm_service import build_system_prompt
from app.streamlit_client import EstimationStreamError, stream_estimation

load_dotenv()
try:
    api_url = os.getenv("ESTIMATOR_API_BASE_URL") or st.secrets.get("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
except Exception:
    api_url = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Estimador CAG")
st.title("Estimador CAG")

st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_metrics", None)

if st.sidebar.button("Borrar historial"):
    st.session_state.messages = []
    st.session_state.last_metrics = None
    st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Pega aquí la transcripción de la reunión...")
if prompt:
    st.session_state.last_metrics = None
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        metrics = {}
        try:
            response = st.write_stream(stream_estimation(prompt, api_url, metrics))
        except EstimationStreamError as exc:
            st.error(str(exc))
            st.caption("El texto parcial, si aparece, no es una estimación completa.")
        else:
            st.session_state.messages.append({"role": "assistant", "content": response})
            st.session_state.last_metrics = metrics

st.sidebar.header("Contexto CAG")
st.sidebar.text_area("System prompt", value=build_system_prompt(), height=300, disabled=True)
st.sidebar.caption("Plantilla predeterminada de esta versión del cliente.")

st.sidebar.subheader("Ejemplos históricos")
for ex in select_examples(DEFAULT_NUM_EXAMPLES):
    st.sidebar.markdown(f"**{ex.title}**")
    st.sidebar.caption(ex.meeting_summary)

st.sidebar.subheader("Última llamada")
last_metrics = st.session_state.last_metrics
if last_metrics:
    usage = last_metrics.get("usage", {})
    st.sidebar.metric("Modelo", last_metrics.get("model", "Desconocido"))
    st.sidebar.metric("Tokens de entrada", usage.get("input_tokens", 0))
    st.sidebar.metric("Tokens de salida", usage.get("output_tokens", 0))
    st.sidebar.metric("Latencia (ms)", last_metrics.get("latency_ms", 0))
    cost = last_metrics.get("request_cost_usd")
    st.sidebar.metric("Coste de solicitud (USD)", "Sin tarifa" if cost is None else f"{cost:.6f}")
    st.sidebar.caption("Respuesta de caché" if last_metrics.get("cache_hit") else "Respuesta generada")
else:
    st.sidebar.caption("Aún no se ha generado ninguna estimación.")
