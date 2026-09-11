# estimador-cag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI backend that accepts a meeting transcription and returns a CAG-generated software estimate by injecting all historical examples verbatim into the LLM system prompt.

**Architecture:** `config.py` (Pydantic BaseSettings + lru_cache) → `context/examples.py` (few-shot data) → `services/llm_service.py` (prompt builder + async OpenAI/Anthropic dispatch) → `routers/estimations.py` (HTTP layer, Pydantic schemas) → `main.py` (FastAPI app + /health). No RAG, no vector store, no LangChain.

**Tech Stack:** Python 3.11, FastAPI ≥0.115, Pydantic v2, pydantic-settings v2, openai ≥1.0, anthropic ≥0.40, pytest + pytest-asyncio + pytest-mock + httpx, uv.

**Spec:** `docs/superpowers/specs/2026-09-11-estimador-cag-design.md`

## Global Constraints

- Python 3.11 — do not change `.python-version`
- `uv` is the package manager — use `uv sync` / `uv run`; never bare `pip`
- No LangChain, LlamaIndex, vector stores, or databases
- No secrets (API keys) in HTTP responses, logs, or committed files
- `.env` must remain git-ignored; `.env.example` is versioned
- All LLM calls must be `async`/`await`
- Pydantic v2 syntax throughout: `.model_dump()` not `.dict()`, `model_config` not `class Config`
- `estimated_cost_usd` is always `None` — do not invent prices

---

### Task 1: Project scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `.env`
- Delete: `src/` tree
- Create: `app/__init__.py`, `app/routers/__init__.py`, `app/services/__init__.py`, `app/context/__init__.py`
- Create: `tests/__init__.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `uv sync`-ready project, importable `app` package

- [ ] **Step 1: Replace `pyproject.toml`**

Note: the existing build backend (`uv_build`) is dropped because `app/` is a web app run via uvicorn, not an installable library. `uv` stays as the package manager.

```toml
[project]
name = "estimador-cag"
version = "0.1.0"
description = "CAG-based software project estimation API"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi[standard]>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "openai>=1.0.0",
    "anthropic>=0.40.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Install / sync dependencies**

```bash
uv sync --group dev
```

Expected: uv resolves and installs all packages without errors.

- [ ] **Step 3: Create `.gitignore`**

```
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
.idea/
.vscode/
```

- [ ] **Step 4: Create `.env.example`**

```
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
APP_ENV=development
LOG_LEVEL=DEBUG
```

- [ ] **Step 5: Create `.env` (never commit this file)**

```
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
APP_ENV=development
LOG_LEVEL=DEBUG
```

- [ ] **Step 6: Remove old `src/` tree**

```bash
rm -rf src/
```

- [ ] **Step 7: Create `app/` package skeleton**

Create each file containing only a module docstring:

- `app/__init__.py` → `"""estimador-cag application."""`
- `app/routers/__init__.py` → `"""Routers."""`
- `app/services/__init__.py` → `"""Services."""`
- `app/context/__init__.py` → `"""CAG context data."""`

- [ ] **Step 8: Create `tests/` skeleton**

`tests/__init__.py` → empty file.

`tests/conftest.py`:

```python
from app.config import get_settings


def pytest_runtest_setup(item):
    get_settings.cache_clear()


def pytest_runtest_teardown(item, nextitem):
    get_settings.cache_clear()
```

- [ ] **Step 9: Smoke-test imports**

```bash
uv run python -c "import fastapi, openai, anthropic, pydantic_settings; print('OK')"
```

Expected: prints `OK`.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml .gitignore .env.example app/ tests/
git commit -m "feat: scaffold estimador-cag project structure"
```

Do NOT `git add .env`.

---

### Task 2: Configuration (`app/config.py`)

**Files:**
- Create: `app/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `get_settings() -> Settings`, `Settings.effective_model() -> str`
- Consumed by: Tasks 4, 5, 6, 7

- [ ] **Step 1: Write failing tests — `tests/test_config.py`**

```python
import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def _openai(**kw) -> Settings:
    return Settings(llm_provider="openai", openai_api_key="sk-test", _env_file=None, **kw)


def _anthropic(**kw) -> Settings:
    return Settings(
        llm_provider="anthropic", anthropic_api_key="sk-ant-test", _env_file=None, **kw
    )


def test_openai_requires_key():
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(llm_provider="openai", openai_api_key=None, _env_file=None)


def test_anthropic_requires_key():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(llm_provider="anthropic", anthropic_api_key=None, _env_file=None)


def test_openai_valid():
    s = _openai()
    assert s.llm_provider == "openai"
    assert s.openai_api_key == "sk-test"


def test_anthropic_valid():
    s = _anthropic()
    assert s.llm_provider == "anthropic"


def test_effective_model_openai_default():
    s = _openai()
    assert s.effective_model() == "gpt-4o-mini"


def test_effective_model_anthropic_substitutes_openai_default():
    # When provider is anthropic but model was left at the OpenAI default,
    # effective_model() must return the Anthropic default instead.
    s = _anthropic(llm_model="gpt-4o-mini")
    assert s.effective_model() == "claude-haiku-4-5"


def test_effective_model_anthropic_explicit_override():
    s = _anthropic(llm_model="claude-opus-4-8")
    assert s.effective_model() == "claude-opus-4-8"


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-test")
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Implement `app/config.py`**

```python
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OPENAI_DEFAULT = "gpt-4o-mini"
_ANTHROPIC_DEFAULT = "claude-haiku-4-5"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = _OPENAI_DEFAULT
    app_env: str = "development"
    log_level: str = "DEBUG"

    @model_validator(mode="after")
    def validate_provider_key(self) -> "Settings":
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        return self

    def effective_model(self) -> str:
        """Return the model to use, applying per-provider defaults when needed."""
        if self.llm_provider == "anthropic" and self.llm_model == _OPENAI_DEFAULT:
            return _ANTHROPIC_DEFAULT
        return self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add Pydantic Settings config with per-provider key validation"
```

---

### Task 3: Few-shot examples (`app/context/examples.py`)

**Files:**
- Create: `app/context/examples.py`
- Create: `tests/test_examples.py`

**Interfaces:**
- Produces: `ESTIMATION_EXAMPLES: list[dict[str, str]]`
- Consumed by: Task 4 (prompt builder)

- [ ] **Step 1: Write failing tests — `tests/test_examples.py`**

```python
from app.context.examples import ESTIMATION_EXAMPLES


def test_has_at_least_two_examples():
    assert len(ESTIMATION_EXAMPLES) >= 2


def test_each_example_has_required_keys():
    for i, ex in enumerate(ESTIMATION_EXAMPLES):
        assert "meeting_summary" in ex, f"Example {i} missing meeting_summary"
        assert "estimation" in ex, f"Example {i} missing estimation"


def test_examples_have_substantive_content():
    for i, ex in enumerate(ESTIMATION_EXAMPLES):
        assert len(ex["meeting_summary"]) > 80, f"Example {i} meeting_summary too short"
        assert len(ex["estimation"]) > 200, f"Example {i} estimation too short"
        assert "##" in ex["estimation"], f"Example {i} estimation missing markdown headers"
        text = ex["estimation"].lower()
        assert "hora" in text or "hour" in text, f"Example {i} estimation missing hour references"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_examples.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.context.examples'`

- [ ] **Step 3: Implement `app/context/examples.py`**

```python
ESTIMATION_EXAMPLES: list[dict[str, str]] = [
    {
        "meeting_summary": (
            "El cliente Comercial Andina necesita una plataforma web para gestionar "
            "su inventario de más de 5 000 SKUs. Actualmente usan hojas de cálculo. "
            "Requieren: registro y edición de productos, control de stock con alertas "
            "de mínimo, historial de movimientos, dashboard con métricas clave "
            "(rotación, valorización), autenticación por roles (admin, bodeguero, "
            "gerente), exportación a Excel y despliegue en AWS. Stack preferido: "
            "React + FastAPI + PostgreSQL. Tienen equipo de QA interno. "
            "El plazo deseado es 3 meses."
        ),
        "estimation": """\
## Estimación: Plataforma de Gestión de Inventario — Comercial Andina

### Supuestos
- Diseño UI/UX incluye 2 rondas de revisión; cambios mayores fuera de alcance.
- Autenticación vía JWT; sin SSO ni LDAP.
- Base de datos PostgreSQL en RDS; sin alta disponibilidad multi-región.
- Exportaciones CSV/Excel generadas en el servidor; sin reportes BI complejos.
- El equipo de QA del cliente ejecuta pruebas de aceptación; el equipo dev entrega pruebas unitarias e integración.
- CI/CD básico con GitHub Actions hacia staging y producción en AWS ECS.

### Requisitos identificados
- CRUD de productos y categorías
- Control de stock con alertas de mínimo
- Historial de movimientos de inventario
- Dashboard con métricas (rotación, valorización)
- Autenticación con roles (admin, bodeguero, gerente)
- Exportación a Excel/CSV
- Despliegue en AWS

### Desglose de tareas

| # | Área | Tarea | Horas |
|---|------|-------|------:|
| 1 | Diseño | Wireframes y flujos UX (5 pantallas principales) | 24 |
| 2 | Diseño | Prototipo interactivo y revisiones | 16 |
| 3 | Backend | Modelado de base de datos y migraciones | 12 |
| 4 | Backend | API REST: productos y categorías (CRUD) | 20 |
| 5 | Backend | API REST: movimientos de inventario y alertas | 16 |
| 6 | Backend | API REST: métricas para dashboard | 12 |
| 7 | Backend | Exportación CSV/Excel | 8 |
| 8 | Auth | JWT: login, refresh, roles y permisos | 16 |
| 9 | Frontend | Setup React + routing + estado global | 10 |
| 10 | Frontend | Módulo de productos (listado, formularios) | 24 |
| 11 | Frontend | Módulo de inventario y alertas | 20 |
| 12 | Frontend | Dashboard y gráficas | 16 |
| 13 | Frontend | Páginas de autenticación y sesión | 10 |
| 14 | Testing | Pruebas unitarias backend (≥70% cobertura) | 20 |
| 15 | Testing | Pruebas de integración API | 12 |
| 16 | DevOps | Dockerización y configuración AWS ECS | 16 |
| 17 | DevOps | Pipeline CI/CD (GitHub Actions) | 12 |
| 18 | DevOps | Configuración RDS, variables de entorno, secretos | 8 |
| 19 | PM | Gestión de proyecto, demos, documentación técnica | 20 |

### Resumen

- **Total estimado:** 292 horas
- **Rango recomendado:** 280–340 horas (buffer de riesgo ~15%)
- **Equipo recomendado:** 1 Tech Lead / Full-stack Sr, 1 Frontend Mid, 1 Backend Mid
- **Duración aproximada:** 3–3.5 meses (equipo de 3, ~40 h/semana)

### Riesgos e incertidumbres
- Migración de datos desde Excel puede requerir trabajo adicional no estimado.
- Definición de roles podría expandirse si hay más de 3 perfiles.
- Integración con ERP o facturación fue mencionada informalmente; no está en el alcance.

### Preguntas abiertas
- ¿Se requiere aplicación móvil o solo web responsivo?
- ¿Las alertas de stock son en pantalla o también por email/SMS?
- ¿Qué datos históricos deben migrarse desde las hojas de cálculo?
""",
    },
    {
        "meeting_summary": (
            "La clínica Salud Total quiere digitalizar su proceso de reservas médicas. "
            "Actualmente las citas se gestionan por teléfono. Necesitan: portal web "
            "para pacientes (registro, selección de especialidad, médico y horario), "
            "panel de administración para médicos y recepcionistas, recordatorios "
            "automáticos por email y WhatsApp, historial de citas por paciente, "
            "cancelación y reprogramación, y un módulo básico de pago en línea "
            "(integración con Wompi). Stack: Vue.js + Django + MySQL. "
            "El cliente no tiene equipo técnico interno. Plazo: 4 meses."
        ),
        "estimation": """\
## Estimación: Sistema de Reservas Médicas — Clínica Salud Total

### Supuestos
- Módulo de pago cubre solo Wompi (tarjetas); pagos en efectivo fuera de alcance.
- Recordatorios WhatsApp vía API oficial de WhatsApp Business (Meta); aprobación del número es responsabilidad del cliente.
- Historial de citas es solo lectura; sin expediente clínico.
- Autenticación separada para pacientes (email/contraseña) y personal interno.
- Sin integración con sistemas de historia clínica existentes.
- Infraestructura: VPS o instancia EC2 básica; sin orquestación de contenedores.
- El equipo dev entrega QA completo (cliente sin equipo técnico).

### Requisitos identificados
- Portal web para pacientes: registro, login, selección de cita
- Catálogo de especialidades, médicos y disponibilidad horaria
- Creación, cancelación y reprogramación de citas
- Historial de citas por paciente
- Recordatorios automáticos por email y WhatsApp
- Pago en línea con Wompi
- Panel de administración para médicos y recepcionistas

### Desglose de tareas

| # | Área | Tarea | Horas |
|---|------|-------|------:|
| 1 | Diseño | UX: flujos paciente y admin (8 pantallas) | 28 |
| 2 | Diseño | Prototipo, revisiones y aprobación | 16 |
| 3 | Backend | Modelos de datos (Django ORM, MySQL) | 14 |
| 4 | Backend | API: registro y autenticación de pacientes | 14 |
| 5 | Backend | API: catálogo de especialidades, médicos y disponibilidad | 18 |
| 6 | Backend | API: creación, cancelación y reprogramación de citas | 20 |
| 7 | Backend | API: historial de citas por paciente | 8 |
| 8 | Backend | Integración Wompi (pagos, webhooks, reconciliación) | 24 |
| 9 | Backend | Notificaciones: email (SendGrid) | 10 |
| 10 | Backend | Notificaciones: WhatsApp Business API | 16 |
| 11 | Backend | Panel admin Django + permisos por rol | 16 |
| 12 | Frontend | Setup Vue.js + Vue Router + Pinia | 8 |
| 13 | Frontend | Portal paciente: registro y login | 12 |
| 14 | Frontend | Portal paciente: búsqueda y reserva de citas | 24 |
| 15 | Frontend | Portal paciente: mis citas e historial | 12 |
| 16 | Frontend | Panel recepcionista: agenda y gestión de citas | 20 |
| 17 | Testing | Pruebas unitarias e integración backend | 24 |
| 18 | Testing | Pruebas end-to-end (flujo de reserva y pago) | 16 |
| 19 | DevOps | Dockerización, servidor, SSL, backups | 14 |
| 20 | DevOps | Variables de entorno, secretos, monitoreo básico | 8 |
| 21 | PM | Gestión, demos, manuales de usuario y documentación | 24 |

### Resumen

- **Total estimado:** 346 horas
- **Rango recomendado:** 330–400 horas (buffer ~15%; WhatsApp y Wompi tienen riesgo de demoras externas)
- **Equipo recomendado:** 1 Tech Lead / Backend Sr, 1 Frontend Mid, 1 QA / Dev Jr
- **Duración aproximada:** 3.5–4 meses

### Riesgos e incertidumbres
- Aprobación de cuenta WhatsApp Business (Meta) puede tardar 2–4 semanas; bloquea el módulo de recordatorios.
- Wompi puede requerir documentación empresarial para activar pagos en producción.
- Gestión de disponibilidad en tiempo real puede ser más compleja según reglas de negocio que surjan.

### Preguntas abiertas
- ¿Los médicos gestionan su propia agenda o solo lo hace recepción?
- ¿Hay un sistema de historia clínica con el que eventualmente deba integrarse?
- ¿Se necesita soporte multiidioma?
""",
    },
]
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_examples.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/context/examples.py tests/test_examples.py
git commit -m "feat: add two historical estimation examples for CAG context injection"
```

---

### Task 4: Prompt builder (`app/services/llm_service.py` — part 1)

**Files:**
- Create: `app/services/llm_service.py` (data structures + prompt builder only; no LLM calls yet)
- Create: `tests/test_llm_service.py`

**Interfaces:**
- Produces: `LLMEstimationResult` (dataclass), `build_system_prompt() -> str`
- Consumed by: Task 5 (`generate_estimation`)

- [ ] **Step 1: Write failing tests — `tests/test_llm_service.py`**

```python
from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import build_system_prompt


def test_prompt_contains_role():
    prompt = build_system_prompt()
    assert "Senior Software Estimation Architect" in prompt


def test_prompt_contains_all_example_summaries():
    prompt = build_system_prompt()
    for ex in ESTIMATION_EXAMPLES:
        assert ex["meeting_summary"][:60] in prompt


def test_prompt_contains_all_example_estimations():
    prompt = build_system_prompt()
    for ex in ESTIMATION_EXAMPLES:
        assert ex["estimation"][:60] in prompt


def test_prompt_contains_output_format_markers():
    # The output template uses Spanish headers (output language is Spanish)
    prompt = build_system_prompt()
    assert "Estimación:" in prompt
    assert "Supuestos" in prompt
    assert "Riesgos" in prompt
    assert "Preguntas abiertas" in prompt


def test_prompt_instructs_assumptions_over_invention():
    # Instructions are in English
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "assumption" in lower


def test_prompt_is_substantial():
    prompt = build_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 800
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_llm_service.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.llm_service'`

- [ ] **Step 3: Implement `app/services/llm_service.py`**

```python
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException

from app.context.examples import ESTIMATION_EXAMPLES

logger = logging.getLogger(__name__)

_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class LLMEstimationResult:
    estimation: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    generated_at: datetime
    latency_ms: int


def build_system_prompt() -> str:
    """Build the full system prompt including role, rules, format spec, and all examples."""
    return f"""\
You are a Senior Software Estimation Architect with extensive experience estimating \
software projects across industries and scales.

## Your Responsibility

Analyze the transcript of a client meeting and produce an initial software development \
estimate grounded in the identified requirements, the historical examples provided below, \
explicit assumptions, and technical uncertainty.

## Mandatory Rules

1. **Do not invent requirements** as if they were confirmed. When information is missing, \
declare it explicitly as an assumption.
2. **Always distinguish** between explicit requirements (mentioned in the meeting) and \
assumptions (inferred by you to complete the estimate).
3. **Avoid false precision**: present hour ranges when uncertainty is high.
4. **Include tasks that are commonly forgotten**: testing, QA, technical documentation, \
environment setup, deployment, observability, and basic project management.
5. **Identify risks** and uncertainties that could affect scope or timeline.
6. **Use historical examples as calibration references**, do not copy them mechanically.
7. **Estimates are indicative**, not contractual commitments.

## Expected Output Format (strict Markdown, output in Spanish)

```
## Estimación: [nombre inferido del proyecto]

### Resumen del alcance
[2-3 oraciones describiendo qué se construirá]

### Requisitos identificados
[Lista de requisitos explícitamente mencionados en la reunión]

### Supuestos
[Lista de supuestos que hiciste para completar la estimación]

### Desglose de tareas

| # | Área | Tarea | Horas |
|---|------|-------|------:|
| 1 | ... | ... | ... |

### Resumen

- Total estimado: X horas
- Rango recomendado: X–Y horas
- Equipo recomendado: ...
- Duración aproximada: ...

### Riesgos e incertidumbres
[Lista de riesgos]

### Preguntas abiertas
[Preguntas que el cliente debe responder antes de confirmar el alcance]
```

## Historical Reference Examples

The following projects were previously estimated. Use them to calibrate relative \
complexity, typical hours per area, and deliverable structure. \
Do not copy them; use them as a calibration anchor.

{_format_examples()}
"""


def _format_examples() -> str:
    parts: list[str] = []
    for i, ex in enumerate(ESTIMATION_EXAMPLES, start=1):
        parts.append(
            f"### Historical Example {i}\n\n"
            f"**Meeting Summary:**\n{ex['meeting_summary']}\n\n"
            f"**Generated Estimation:**\n{ex['estimation']}\n"
        )
    return "\n---\n\n".join(parts)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_llm_service.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/llm_service.py tests/test_llm_service.py
git commit -m "feat: add CAG prompt builder with few-shot examples injection"
```

---

### Task 5: LLM dispatch (`app/services/llm_service.py` — part 2)

**Files:**
- Modify: `app/services/llm_service.py` (add `generate_estimation`, `_call_openai`, `_call_anthropic`)
- Modify: `tests/test_llm_service.py` (add async dispatch tests)

**Interfaces:**
- Consumes: `get_settings() -> Settings`, `build_system_prompt() -> str`, `LLMEstimationResult`
- Produces: `async generate_estimation(transcription: str) -> LLMEstimationResult`

- [ ] **Step 1: Append dispatch tests to `tests/test_llm_service.py`**

```python
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.config import Settings
from app.services.llm_service import LLMEstimationResult, generate_estimation


def _openai_settings() -> Settings:
    return Settings(
        llm_provider="openai",
        openai_api_key="sk-test",
        llm_model="gpt-4o-mini",
        _env_file=None,
    )


def _anthropic_settings() -> Settings:
    return Settings(
        llm_provider="anthropic",
        anthropic_api_key="sk-ant-test",
        llm_model="gpt-4o-mini",  # OpenAI default — must be substituted to claude-haiku-4-5
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_generate_estimation_openai(mocker):
    mocker.patch("app.services.llm_service.get_settings", return_value=_openai_settings())

    usage = MagicMock(prompt_tokens=120, completion_tokens=80, total_tokens=200)
    choice = MagicMock()
    choice.message.content = "## Estimación: Test\nContenido"
    mock_response = MagicMock(choices=[choice], usage=usage, model="gpt-4o-mini")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mocker.patch("app.services.llm_service.AsyncOpenAI", return_value=mock_client)

    result = await generate_estimation("Transcripción suficientemente larga para ser válida en el test")

    assert isinstance(result, LLMEstimationResult)
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini"
    assert result.estimation == "## Estimación: Test\nContenido"
    assert result.input_tokens == 120
    assert result.output_tokens == 80
    assert result.total_tokens == 200
    assert result.estimated_cost_usd is None
    assert isinstance(result.generated_at, datetime)
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_generate_estimation_anthropic_substitutes_default_model(mocker):
    mocker.patch("app.services.llm_service.get_settings", return_value=_anthropic_settings())

    usage = MagicMock(input_tokens=150, output_tokens=90)
    content_block = MagicMock()
    content_block.text = "## Estimación: Test Anthropic\nContenido"
    mock_response = MagicMock(content=[content_block], usage=usage, model="claude-haiku-4-5")

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    mocker.patch("app.services.llm_service.AsyncAnthropic", return_value=mock_client)

    result = await generate_estimation("Transcripción suficientemente larga para ser válida en el test")

    assert result.provider == "anthropic"
    assert result.model == "claude-haiku-4-5"
    assert result.estimation == "## Estimación: Test Anthropic\nContenido"
    assert result.input_tokens == 150
    assert result.output_tokens == 90
    assert result.total_tokens == 240
    assert result.estimated_cost_usd is None


@pytest.mark.asyncio
async def test_generate_estimation_raises_502_on_empty_response(mocker):
    mocker.patch("app.services.llm_service.get_settings", return_value=_openai_settings())

    choice = MagicMock()
    choice.message.content = "   "  # whitespace only — counts as empty
    mock_response = MagicMock(
        choices=[choice],
        usage=MagicMock(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        model="gpt-4o-mini",
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mocker.patch("app.services.llm_service.AsyncOpenAI", return_value=mock_client)

    with pytest.raises(HTTPException) as exc_info:
        await generate_estimation("Transcripción suficientemente larga para ser válida en el test")
    assert exc_info.value.status_code == 502
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
uv run pytest tests/test_llm_service.py -v -k "openai or anthropic or empty"
```

Expected: `AttributeError` or `ImportError` (generate_estimation not defined yet).

- [ ] **Step 3: Add imports and dispatch functions to `app/services/llm_service.py`**

Add these imports at the top (after existing imports):

```python
from anthropic import (
    AsyncAnthropic,
    APITimeoutError as AnthropicTimeout,
    AuthenticationError as AnthropicAuthError,
)
from openai import (
    AsyncOpenAI,
    APITimeoutError as OpenAITimeout,
    AuthenticationError as OpenAIAuthError,
)

from app.config import Settings, get_settings
```

Append at the bottom of the file:

```python
async def generate_estimation(transcription: str) -> LLMEstimationResult:
    settings = get_settings()
    system_prompt = build_system_prompt()
    start = time.monotonic()

    logger.info(
        "Generating estimation provider=%s model=%s transcription_chars=%d",
        settings.llm_provider,
        settings.effective_model(),
        len(transcription),
    )

    if settings.llm_provider == "openai":
        result = await _call_openai(system_prompt, transcription, settings)
    elif settings.llm_provider == "anthropic":
        result = await _call_anthropic(system_prompt, transcription, settings)
    else:
        raise HTTPException(status_code=500, detail="Unsupported LLM provider")

    result.latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "Estimation complete provider=%s model=%s tokens=%d latency_ms=%d",
        result.provider,
        result.model,
        result.total_tokens,
        result.latency_ms,
    )
    return result


async def _call_openai(
    system_prompt: str, transcription: str, settings: Settings
) -> LLMEstimationResult:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        response = await client.chat.completions.create(
            model=settings.effective_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcription},
            ],
            temperature=0.3,
        )
    except OpenAIAuthError:
        logger.error("OpenAI authentication failed")
        raise HTTPException(status_code=502, detail="LLM authentication failed")
    except OpenAITimeout:
        logger.error("OpenAI request timed out")
        raise HTTPException(status_code=504, detail="LLM request timed out")
    except Exception as exc:
        logger.error("OpenAI call failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="LLM provider error")

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="LLM returned an empty response")

    usage = response.usage
    return LLMEstimationResult(
        estimation=text,
        model=response.model,
        provider="openai",
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        estimated_cost_usd=None,
        generated_at=datetime.now(tz=timezone.utc),
        latency_ms=0,
    )


async def _call_anthropic(
    system_prompt: str, transcription: str, settings: Settings
) -> LLMEstimationResult:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.effective_model(),
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": transcription}],
        )
    except AnthropicAuthError:
        logger.error("Anthropic authentication failed")
        raise HTTPException(status_code=502, detail="LLM authentication failed")
    except AnthropicTimeout:
        logger.error("Anthropic request timed out")
        raise HTTPException(status_code=504, detail="LLM request timed out")
    except Exception as exc:
        logger.error("Anthropic call failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="LLM provider error")

    text = (response.content[0].text if response.content else "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="LLM returned an empty response")

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    return LLMEstimationResult(
        estimation=text,
        model=response.model,
        provider="anthropic",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=None,
        generated_at=datetime.now(tz=timezone.utc),
        latency_ms=0,
    )
```

- [ ] **Step 4: Run all LLM service tests**

```bash
uv run pytest tests/test_llm_service.py -v
```

Expected: all tests pass (6 prompt tests + 3 dispatch tests = 9 total).

- [ ] **Step 5: Commit**

```bash
git add app/services/llm_service.py tests/test_llm_service.py
git commit -m "feat: add async LLM dispatch for OpenAI and Anthropic providers"
```

---

### Task 6: Router (`app/routers/estimations.py`)

**Files:**
- Create: `app/routers/estimations.py`
- Create: `tests/test_router.py`

**Interfaces:**
- Consumes: `generate_estimation(transcription: str) -> LLMEstimationResult`, `LLMEstimationResult`
- Produces: `router` (APIRouter), `EstimationRequest`, `EstimationResponse`

- [ ] **Step 1: Write failing tests — `tests/test_router.py`**

Note: tests build a standalone FastAPI app from the router to avoid depending on `app/main.py`.

```python
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.estimations import router
from app.services.llm_service import LLMEstimationResult


def _make_result() -> LLMEstimationResult:
    return LLMEstimationResult(
        estimation="## Estimación: Test\nContenido de prueba",
        model="gpt-4o-mini",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost_usd=None,
        generated_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc),
        latency_ms=1200,
    )


@pytest.fixture
def client(mocker) -> TestClient:
    mocker.patch(
        "app.routers.estimations.generate_estimation",
        new=AsyncMock(return_value=_make_result()),
    )
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


def test_estimate_valid_returns_200(client):
    resp = client.post(
        "/estimate",
        json={"transcription": "El cliente solicita una plataforma de e-commerce con pagos y envíos integrados."},
    )
    assert resp.status_code == 200


def test_estimate_response_shape(client):
    resp = client.post(
        "/estimate",
        json={"transcription": "El cliente solicita una plataforma de e-commerce con pagos y envíos integrados."},
    )
    data = resp.json()
    assert data["estimation"].startswith("## Estimación: Test")
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert data["usage"]["input_tokens"] == 100
    assert data["usage"]["output_tokens"] == 50
    assert data["usage"]["total_tokens"] == 150
    assert data["estimated_cost_usd"] is None
    assert data["latency_ms"] == 1200
    assert "generated_at" in data


def test_estimate_rejects_too_short(client):
    resp = client.post("/estimate", json={"transcription": "Corto"})
    assert resp.status_code == 422


def test_estimate_rejects_empty(client):
    resp = client.post("/estimate", json={"transcription": ""})
    assert resp.status_code == 422


def test_estimate_rejects_missing_field(client):
    resp = client.post("/estimate", json={})
    assert resp.status_code == 422


def test_estimate_rejects_too_long(client):
    resp = client.post("/estimate", json={"transcription": "A" * 50_001})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_router.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.routers.estimations'`

- [ ] **Step 3: Implement `app/routers/estimations.py`**

```python
import logging
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.llm_service import LLMEstimationResult, generate_estimation

logger = logging.getLogger(__name__)

router = APIRouter()


class EstimationRequest(BaseModel):
    transcription: str = Field(
        min_length=20,
        max_length=50_000,
        description="Transcripción de la reunión con el cliente.",
    )


class UsageInfo(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
    usage: UsageInfo
    estimated_cost_usd: float | None
    latency_ms: int
    generated_at: datetime


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(request: EstimationRequest) -> EstimationResponse:
    logger.debug(
        "Received estimation request transcription_chars=%d", len(request.transcription)
    )
    result: LLMEstimationResult = await generate_estimation(request.transcription)
    return EstimationResponse(
        estimation=result.estimation,
        model=result.model,
        provider=result.provider,
        usage=UsageInfo(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
        ),
        estimated_cost_usd=result.estimated_cost_usd,
        latency_ms=result.latency_ms,
        generated_at=result.generated_at,
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run pytest tests/test_router.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/routers/estimations.py tests/test_router.py
git commit -m "feat: add POST /estimate router with Pydantic request/response schemas"
```

---

### Task 7: FastAPI main (`app/main.py`) + health check

**Files:**
- Create: `app/main.py`
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes: `estimations.router` (APIRouter), `get_settings() -> Settings`
- Produces: `app` (FastAPI instance) serving `/health` and `/api/v1/estimate`

- [ ] **Step 1: Write failing tests — `tests/test_main.py`**

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fixture")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_response_shape(client):
    data = client.get("/health").json()
    assert data["status"] == "healthy"
    assert "environment" in data
    assert "provider" in data
    assert "model" in data


def test_health_does_not_expose_api_key(client):
    resp_text = client.get("/health").text
    assert "sk-test-fixture" not in resp_text
    assert "api_key" not in resp_text.lower()


def test_swagger_ui_available(client):
    assert client.get("/docs").status_code == 200


def test_openapi_title(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Software Estimation CAG API"


def test_estimate_endpoint_is_registered(client):
    # Just verify the route exists (not calling LLM); 422 means the route is there
    resp = client.post("/api/v1/estimate", json={})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest tests/test_main.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement `app/main.py`**

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import estimations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "Starting estimador-cag env=%s provider=%s model=%s",
        settings.app_env,
        settings.llm_provider,
        settings.effective_model(),
    )
    yield


app = FastAPI(
    title="Software Estimation CAG API",
    description=(
        "Genera estimaciones de proyectos de software a partir de transcripciones "
        "de reuniones con clientes, inyectando ejemplos históricos directamente en "
        "el contexto del LLM (Context-Augmented Generation)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(estimations.router, prefix="/api/v1", tags=["estimations"])


@app.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(
        content={
            "status": "healthy",
            "environment": settings.app_env,
            "provider": settings.llm_provider,
            "model": settings.effective_model(),
        }
    )
```

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass (config + examples + llm_service + router + main = ~25 tests).

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat: add FastAPI app with health check endpoint and Swagger docs"
```

---

### Task 8: README + final validation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# Software Estimation CAG API

FastAPI backend que genera estimaciones iniciales de proyectos de software
a partir de transcripciones de reuniones con clientes, utilizando CAG
(Context-Augmented Generation) con OpenAI o Anthropic.

## ¿Qué es CAG en este proyecto?

CAG inyecta ejemplos históricos de estimaciones **directamente dentro del prompt
del LLM** — sin embeddings, sin vector stores, sin recuperación semántica.
El modelo recibe toda la información de contexto en una sola llamada.

## Arquitectura

```
POST /api/v1/estimate
       │
       ▼
EstimationRequest (Pydantic, validación min/max)
       │
       ▼
generate_estimation(transcription)
       ├── build_system_prompt()   ← inyecta ESTIMATION_EXAMPLES verbatim
       ├── _call_openai()   o   _call_anthropic()
       └── LLMEstimationResult
       │
       ▼
EstimationResponse (JSON)
```

## Estructura del proyecto

```
estimador-cag/
├── app/
│   ├── main.py              — FastAPI app, /health, lifespan, Swagger
│   ├── config.py            — BaseSettings + lru_cache + validación por proveedor
│   ├── routers/
│   │   └── estimations.py  — POST /api/v1/estimate, schemas Pydantic
│   ├── services/
│   │   └── llm_service.py  — build_system_prompt() + dispatch OpenAI/Anthropic
│   └── context/
│       └── examples.py     — ESTIMATION_EXAMPLES (few-shot)
├── tests/
├── .env.example
├── pyproject.toml
└── README.md
```

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) instalado
- API key de OpenAI **o** Anthropic

## Instalación

```bash
cd estimador-cag
uv sync --group dev
```

## Configuración

```bash
cp .env.example .env
# Editar .env con tu API key
```

| Variable | Descripción | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` o `anthropic` | `openai` |
| `LLM_MODEL` | Modelo a usar | `gpt-4o-mini` |
| `OPENAI_API_KEY` | API key de OpenAI | — (requerida si provider=openai) |
| `ANTHROPIC_API_KEY` | API key de Anthropic | — (requerida si provider=anthropic) |
| `APP_ENV` | Entorno | `development` |
| `LOG_LEVEL` | Nivel de logging | `DEBUG` |

### Selección automática de modelo

Si `LLM_MODEL` no se configura explícitamente (o queda en `gpt-4o-mini`) y
`LLM_PROVIDER=anthropic`, el sistema usa automáticamente `claude-haiku-4-5`.
Para usar otro modelo de Anthropic, configura `LLM_MODEL` explícitamente.

## Ejecución

```bash
uv run uvicorn app.main:app --reload
```

La API queda disponible en `http://localhost:8000`.

## Uso

### Health check

```bash
curl http://localhost:8000/health
```

### Generar estimación

```bash
curl -X POST "http://localhost:8000/api/v1/estimate" \
  -H "Content-Type: application/json" \
  -d '{
    "transcription": "El cliente solicita desarrollar un marketplace de servicios profesionales. Los freelancers podrán publicar perfiles y los clientes contratar servicios. Se requiere sistema de pagos con comisión, mensajería interna, valoraciones y un panel de administración. Stack preferido: React, Node.js, PostgreSQL. Plazo deseado: 5 meses."
  }'
```

### Ejemplo de respuesta

```json
{
  "estimation": "## Estimación: Marketplace de Servicios Profesionales\n\n...",
  "model": "gpt-4o-mini",
  "provider": "openai",
  "usage": {
    "input_tokens": 1840,
    "output_tokens": 720,
    "total_tokens": 2560
  },
  "estimated_cost_usd": null,
  "latency_ms": 3200,
  "generated_at": "2026-09-11T15:30:00Z"
}
```

## Swagger

Documentación interactiva en `http://localhost:8000/docs`.

## Tests

```bash
uv run pytest -v
```

## Proveedores soportados

| Proveedor | Config | Modelo por defecto |
|---|---|---|
| OpenAI | `LLM_PROVIDER=openai` | `gpt-4o-mini` |
| Anthropic | `LLM_PROVIDER=anthropic` | `claude-haiku-4-5` |

## Seguridad

- API keys cargadas exclusivamente desde variables de entorno / `.env`
- `.env` está en `.gitignore` — nunca se versiona
- Las API keys no aparecen en respuestas HTTP, logs ni trazas de error
- Los errores del proveedor se normalizan antes de enviarse al cliente

## Limitaciones

- `estimated_cost_usd` siempre es `null` — campo preparado para futura tabla de precios
- Sin autenticación en la API (fuera del alcance)
- Todos los ejemplos históricos se inyectan en cada request; si crecen, aumenta el consumo de tokens
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 3: Verify `.env` is git-ignored**

```bash
git status
```

Confirm `.env` does NOT appear in the output. If it does, the `.gitignore` entry is missing — fix before committing.

- [ ] **Step 4: Smoke-test app startup**

In one terminal:
```bash
uv run uvicorn app.main:app --port 8000
```

In another terminal:
```bash
curl http://localhost:8000/health
```

Expected:
```json
{"status":"healthy","environment":"development","provider":"openai","model":"gpt-4o-mini"}
```

Also verify Swagger loads: open `http://localhost:8000/docs` in a browser.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add comprehensive README with setup, curl examples and limitations"
```

---

## Self-review checklist

**Spec coverage:**
- ✅ File structure matches spec (`app/config.py`, `app/routers/estimations.py`, `app/services/llm_service.py`, `app/context/examples.py`, `app/main.py`)
- ✅ `BaseSettings` + `lru_cache` + `@model_validator` cross-field validation
- ✅ `effective_model()` with OpenAI→Anthropic default substitution
- ✅ 2 realistic ESTIMATION_EXAMPLES with full breakdowns
- ✅ `build_system_prompt()` with role, rules, format spec, all examples verbatim
- ✅ `async generate_estimation()` dispatches to OpenAI or Anthropic
- ✅ `AsyncOpenAI` with `chat.completions.create()`, temperature 0.3, usage tokens
- ✅ `AsyncAnthropic` with `messages.create()`, max_tokens 4096, usage tokens
- ✅ `LLMEstimationResult` dataclass with all required fields; `estimated_cost_usd=None`
- ✅ `POST /api/v1/estimate` with min=20, max=50000 char validation
- ✅ `EstimationResponse` with nested `UsageInfo`
- ✅ Error handling: 502 (auth failure, empty response, provider error), 504 (timeout)
- ✅ Logging: provider, model, transcription length, tokens, latency — never secrets
- ✅ `GET /health` with no LLM call, no API keys in response
- ✅ FastAPI title, description, version; Swagger at `/docs`
- ✅ `.gitignore` excludes `.env`
- ✅ `.env.example` documents all variables
- ✅ README with all required sections

**Type consistency:**
- `LLMEstimationResult` defined in Task 4, imported in Tasks 5 and 6 — consistent
- `generate_estimation` defined in Task 5, patched in Task 6 as `app.routers.estimations.generate_estimation` — consistent
- `Settings.effective_model()` defined in Task 2, called in Tasks 5 and 7 — consistent
- `build_system_prompt()` defined in Task 4, called in Task 5 — consistent
