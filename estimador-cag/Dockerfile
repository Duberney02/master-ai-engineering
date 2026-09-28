# Imágenes separadas para servidor y cliente a partir de un único Dockerfile:
#
#   docker build --target api -t estimador-cag-api .   # FastAPI (objetivo por defecto)
#   docker build --target ui  -t estimador-cag-ui  .   # Streamlit (solo cliente HTTP)
#
# La imagen `ui` no contiene el backend (`app/`), ni SDK de proveedores, ni Redis,
# ni credenciales: solo `estimator_client/`, `streamlit_app.py`, streamlit y httpx.

# Versión de uv: ARG global para poder usarla en el FROM de la etapa `uv`
# (COPY --from no admite variables). Se puede cambiar con --build-arg UV_VERSION=...
ARG UV_VERSION=0.12

# Etapa auxiliar: solo aporta el binario de uv.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# =============================================================================
# Builders — resuelven e instalan solo las dependencias de producción de cada rol
# =============================================================================
FROM python:3.11-slim AS builder-base

# uv (gestor de paquetes) solo vive en las etapas builder: no llega a la imagen final.
COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Primero solo los manifiestos: mientras no cambien, Docker reutiliza estas capas.
COPY pyproject.toml uv.lock ./


FROM builder-base AS builder-api
# --frozen: respeta uv.lock (build reproducible). --no-dev: sin pytest/ruff.
RUN uv sync --frozen --no-dev --extra api --no-install-project


FROM builder-base AS builder-ui
RUN uv sync --frozen --no-dev --extra ui --no-install-project


# =============================================================================
# Base de ejecución: imagen mínima y usuario sin privilegios
# =============================================================================
FROM python:3.11-slim AS runtime-base

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Usuario de sistema sin shell de login ni directorio home: el proceso no corre como root.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app


# =============================================================================
# ui — interfaz Streamlit (cliente HTTP de la API)
# =============================================================================
FROM runtime-base AS ui

COPY --from=builder-ui /app/.venv /app/.venv
COPY estimator_client/ ./estimator_client/
COPY streamlit_app.py ./streamlit_app.py

# Streamlit necesita un HOME escribible para su configuración; sin telemetría.
ENV HOME=/tmp \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true \
    ESTIMATOR_API_BASE_URL=http://api:8000

USER app

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"]

CMD ["streamlit", "run", "streamlit_app.py", "--server.address", "0.0.0.0", "--server.port", "8501"]


# =============================================================================
# api — servidor FastAPI (objetivo por defecto: última etapa)
# =============================================================================
FROM runtime-base AS api

COPY --from=builder-api /app/.venv /app/.venv
COPY app/ ./app/

USER app

EXPOSE 8000

# Sonda sin curl (no existe en -slim): falla si /health no responde 2xx en 3 s.
# /health responde aunque Redis no esté disponible (modo degradado sin caché).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# Las claves NO van en la imagen: se inyectan en tiempo de ejecución (--env-file / Compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
