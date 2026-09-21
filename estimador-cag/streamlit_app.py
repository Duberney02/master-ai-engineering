"""Interfaz conversacional para el estimador CAG: `streamlit run streamlit_app.py`."""

import os

import streamlit as st

from app.context.examples import select_examples
from app.schemas.estimation import DEFAULT_NUM_EXAMPLES
from app.services.llm_service import StreamMetrics, build_system_prompt, generate_estimation_stream
from app.streamlit_support import iter_sync, sync_secrets_to_env

try:
    sync_secrets_to_env(st.secrets, os.environ)
except Exception:
    pass

st.set_page_config(page_title="Estimador CAG")
st.title("Estimador CAG")

st.session_state.setdefault("messages", [])
st.session_state.setdefault("last_metrics", None)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Pega aquí la transcripción de la reunión...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        metrics = StreamMetrics()
        response = st.write_stream(iter_sync(generate_estimation_stream(prompt, metrics)))

    st.session_state.messages.append({"role": "assistant", "content": response})
    st.session_state.last_metrics = metrics

st.sidebar.header("Contexto CAG")
st.sidebar.text_area("System prompt", value=build_system_prompt(), height=300, disabled=True)

st.sidebar.subheader("Ejemplos históricos")
for ex in select_examples(DEFAULT_NUM_EXAMPLES):
    st.sidebar.markdown(f"**{ex.title}**")
    st.sidebar.caption(ex.meeting_summary)

st.sidebar.subheader("Última llamada")
last_metrics: StreamMetrics | None = st.session_state.last_metrics
if last_metrics:
    st.sidebar.metric("Modelo", last_metrics.model)
    st.sidebar.metric("Tokens de entrada", last_metrics.input_tokens)
    st.sidebar.metric("Tokens de salida", last_metrics.output_tokens)
    st.sidebar.metric("Latencia (ms)", last_metrics.latency_ms)
else:
    st.sidebar.caption("Aún no se ha generado ninguna estimación.")
