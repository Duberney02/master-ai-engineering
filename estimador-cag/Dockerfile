# Versión de uv: ARG global para poder usarla en el FROM de la etapa `uv`
# (COPY --from no admite variables). Se puede cambiar con --build-arg UV_VERSION=...
ARG UV_VERSION=0.12

# Etapa auxiliar: solo aporta el binario de uv.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# =============================================================================
# Etapa 1 — builder: resuelve e instala las dependencias de producción
# =============================================================================
FROM python:3.11-slim AS builder

# uv (gestor de paquetes) solo vive en esta etapa: no llega a la imagen final.
COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Primero solo los manifiestos: mientras no cambien, Docker reutiliza esta capa
# y no reinstala dependencias en cada cambio de código.
COPY pyproject.toml uv.lock ./

# --frozen: respeta uv.lock tal cual (build reproducible).
# --no-dev: sin pytest/httpx. --no-install-project: el código se copia en la etapa final.
RUN uv sync --frozen --no-dev --no-install-project


# =============================================================================
# Etapa de pruebas — dependencias de desarrollo; el código y los tests se montan en ejecución
#   docker build --target test -t estimador-cag:test .
#   docker run --rm -v "$PWD:/app" estimador-cag:test
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

# Usuario de sistema sin shell de login ni directorio home: el proceso no corre como root.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Solo el entorno virtual ya construido y el código de la aplicación.
COPY --from=builder /app/.venv /app/.venv
COPY app/ ./app/
COPY streamlit_app.py ./streamlit_app.py

USER app

EXPOSE 8000 8501

# Sonda sin curl (no existe en -slim): falla si /health no responde 2xx en 3 s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# Las claves NO van en la imagen: se inyectan en tiempo de ejecución (--env-file / Compose).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
