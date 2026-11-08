# Chat Streamlit del estimador (capa 1): cliente HTTP del backend `estimator-web`. Sin claves de proveedores.
#
#   docker build -t estimator-streamlit .
#   docker run --rm -p 8501:8501 -e ESTIMATOR_WEB_URL=http://host.docker.internal:3000 estimator-streamlit

# Versión de uv: ARG global para poder usarla en el FROM de la etapa `uv`.
ARG UV_VERSION=0.12

# Etapa auxiliar: solo aporta el binario de uv.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# =============================================================================
# Etapa 1 — builder: resuelve e instala las dependencias de producción
# =============================================================================
FROM python:3.11-slim AS builder

COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Primero solo los manifiestos: mientras no cambien, Docker reutiliza esta capa.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# =============================================================================
# Etapa de pruebas — dependencias de desarrollo; el código y los tests se montan en ejecución
#   docker compose -f docker-compose.verify.yml run --rm streamlit-test
# Se declara antes de runtime para que `docker build .` siga generando la imagen de producción.
# =============================================================================
FROM python:3.11-slim AS test

COPY --from=uv /uv /bin/uv

# El entorno vive fuera de /app para que el montaje del código no lo oculte.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --group dev --no-install-project

CMD ["pytest", "-q"]

# =============================================================================
# Etapa 3 — runtime: imagen mínima, usuario sin privilegios
# =============================================================================
FROM python:3.11-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY estimator_chat/ ./estimator_chat/
COPY streamlit_app.py ./streamlit_app.py

USER app

EXPOSE 8501

# Sonda sin curl (no existe en -slim): falla si /_stcore/health no responde 2xx en 3 s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"]

# ESTIMATOR_WEB_URL (URL del backend Go) se inyecta en tiempo de ejecución.
ENV ESTIMATOR_WEB_URL=http://localhost:3000

CMD ["streamlit", "run", "streamlit_app.py", "--server.address", "0.0.0.0", "--server.port", "8501", "--browser.gatherUsageStats", "false"]
