# Interfaz conversacional con Streamlit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `streamlit_app.py`, a chat UI where a user pastes a meeting transcript and watches the CAG estimation stream in token-by-token, reusing the existing prompt/LLM logic (no new estimation logic, no duplicated prompt/example source).

**Architecture:** A new streaming entry point (`generate_estimation_stream`) is added to `app/services/llm_service.py` next to the existing `generate_estimation`, sharing `build_system_prompt`, `_resolve_model`, `_estimation_user_message` and the provider error mapping. Two small framework-agnostic helpers (`app/streamlit_support.py`) bridge async streaming into Streamlit's sync world and load API keys from `st.secrets` into `os.environ`. `streamlit_app.py` is thin: session-state chat history + sidebar, wired to those pieces.

**Tech Stack:** Python 3.11, FastAPI project conventions, `streamlit==1.64.0` (already added via `uv add streamlit`), `pytest` + `pytest-asyncio` + `pytest-mock`, `streamlit.testing.v1.AppTest`.

**Spec:** `estimador-cag/docs/superpowers/specs/streamlit-chat.md`

## Global Constraints

- Single prompt builder and single example source: `app/services/llm_service.build_system_prompt` and `app/context/examples.py` — `streamlit_app.py` never redefines prompt or example logic.
- `generate_estimation()` and its 27 existing tests in `tests/test_llm_service.py` must not change.
- API keys come only from `get_settings()` (env / `.env`) or `st.secrets`, merged into `os.environ` before `get_settings()` is called; never hardcoded.
- `.env` stays in `.gitignore` (already confirmed present).
- `streamlit` is a normal (non-dev) dependency, added via `uv add streamlit` (already done; `pyproject.toml`/`uv.lock` are dirty in the working tree and get committed in Task 3, Step 1).
- No `preprocessing`/`example_format`/`num_examples`/`model`/`max_tokens` controls in the UI — out of scope for this plan.
- Full suite (141 tests today) must stay green after every task.

---

### Task 1: Streaming support in `llm_service.py`

**Files:**
- Modify: `app/services/llm_service.py` (add `StreamMetrics`, `generate_estimation_stream`, `_stream_openai`, `_stream_anthropic`)
- Modify: `tests/_fakes.py` (add streaming fake helpers)
- Create: `tests/test_llm_service_streaming.py`

**Interfaces:**
- Produces: `StreamMetrics` dataclass — `model: str = ""`, `input_tokens: int = 0`, `output_tokens: int = 0`, `latency_ms: int = 0`.
- Produces: `async def generate_estimation_stream(transcription: str, metrics: StreamMetrics, options: GenerationOptions | None = None) -> AsyncIterator[str]` — yields text fragments of the **estimation** phase only (no `two_phase` preprocessing support; `options` only controls `example_format`/`num_examples`/`use_examples`/`model`/`max_tokens`, matching `GenerationOptions` defaults when omitted). Mutates `metrics` in place with the final model/tokens/latency once the stream is exhausted — callers must fully consume the generator before reading `metrics` (an async generator can't `return` a value per PEP 525).
- Consumes (from existing code): `GenerationOptions`, `_resolve_model`, `build_system_prompt`, `_estimation_user_message`, `_raise_provider_http_error`, `_OPENAI_ERRORS`, `_ANTHROPIC_ERRORS`, `get_settings`, `AsyncOpenAI`, `AsyncAnthropic`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/_fakes.py` (below the existing `patch_anthropic`):

```python
class _AsyncIterFromList:
    def __init__(self, items: list):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def openai_stream_chunks(
    deltas: list[str],
    *,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> list:
    """Fake ChatCompletionChunk sequence: one chunk per delta, then a final usage-only chunk."""
    chunks = [
        SimpleNamespace(
            model=model,
            choices=[SimpleNamespace(delta=SimpleNamespace(content=d), finish_reason=None)],
            usage=None,
        )
        for d in deltas
    ]
    chunks.append(
        SimpleNamespace(
            model=model,
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
    )
    return chunks


def patch_openai_stream(mocker, chunks: list) -> AsyncMock:
    """Parchea AsyncOpenAI para que `create(..., stream=True)` devuelva un stream fake."""
    create = AsyncMock(return_value=_AsyncIterFromList(chunks))
    client = MagicMock()
    client.chat.completions.create = create
    mocker.patch("app.services.llm_service.AsyncOpenAI", return_value=client)
    return create


def anthropic_final_message(
    text: str,
    *,
    model: str = "claude-haiku-4-5",
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
        model=model,
    )


class _FakeAnthropicStream:
    def __init__(self, deltas: list[str], final_message):
        self._deltas = deltas
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    @property
    def text_stream(self):
        return _AsyncIterFromList(list(self._deltas))

    async def get_final_message(self):
        return self._final_message


def patch_anthropic_stream(mocker, deltas: list[str], final_message) -> MagicMock:
    """Parchea AsyncAnthropic para que `messages.stream(...)` devuelva un context manager fake."""
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=_FakeAnthropicStream(deltas, final_message))
    mocker.patch("app.services.llm_service.AsyncAnthropic", return_value=client)
    return client
```

Create `tests/test_llm_service_streaming.py`:

```python
import pytest

from app.services.llm_service import StreamMetrics, generate_estimation_stream
from tests._fakes import (
    LONG_TRANSCRIPTION,
    anthropic_final_message,
    anthropic_settings,
    openai_settings,
    openai_stream_chunks,
    patch_anthropic_stream,
    patch_openai_stream,
    patch_settings,
)


@pytest.mark.asyncio
async def test_stream_openai_yields_deltas_in_order(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai_stream(mocker, openai_stream_chunks(["Hola ", "mundo"]))

    metrics = StreamMetrics()
    chunks = [c async for c in generate_estimation_stream(LONG_TRANSCRIPTION, metrics)]

    assert chunks == ["Hola ", "mundo"]


@pytest.mark.asyncio
async def test_stream_openai_populates_metrics(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai_stream(
        mocker,
        openai_stream_chunks(["Hola"], model="gpt-4o-mini", prompt_tokens=120, completion_tokens=30),
    )

    metrics = StreamMetrics()
    async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, metrics):
        pass

    assert metrics.model == "gpt-4o-mini"
    assert metrics.input_tokens == 120
    assert metrics.output_tokens == 30
    assert metrics.latency_ms >= 0


@pytest.mark.asyncio
async def test_stream_anthropic_yields_deltas_and_metrics(mocker):
    patch_settings(mocker, anthropic_settings())
    final = anthropic_final_message("Hola mundo", model="claude-haiku-4-5", input_tokens=150, output_tokens=40)
    patch_anthropic_stream(mocker, ["Hola ", "mundo"], final)

    metrics = StreamMetrics()
    chunks = [c async for c in generate_estimation_stream(LONG_TRANSCRIPTION, metrics)]

    assert chunks == ["Hola ", "mundo"]
    assert metrics.model == "claude-haiku-4-5"
    assert metrics.input_tokens == 150
    assert metrics.output_tokens == 40


@pytest.mark.asyncio
async def test_stream_uses_shared_system_prompt(mocker):
    patch_settings(mocker, openai_settings())
    create = patch_openai_stream(mocker, openai_stream_chunks(["ok"]))

    metrics = StreamMetrics()
    async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, metrics):
        pass

    kwargs = create.call_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["messages"][0]["role"] == "system"
    assert "Senior Software Estimation Architect" in kwargs["messages"][0]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_service_streaming.py -v`
Expected: FAIL (`ImportError`/`AttributeError`: `StreamMetrics`/`generate_estimation_stream` not defined, and `_fakes.py` helpers missing before that).

- [ ] **Step 3: Implement `StreamMetrics`, `generate_estimation_stream`, `_stream_openai`, `_stream_anthropic`**

In `app/services/llm_service.py`:

- Add `StreamMetrics` as a `@dataclass` right after `PhaseResult` (same four fields as the interface above, all with defaults so `StreamMetrics()` is valid).
- Add `async def generate_estimation_stream(transcription, metrics, options=None)`:
  - `options = options or GenerationOptions()`, `settings = get_settings()`, `model = _resolve_model(settings, options)`.
  - Build `system_prompt` via `build_system_prompt(example_format=options.example_format, num_examples=options.num_examples, use_examples=options.use_examples, inline_cleaning=options.preprocessing == "inline_cleaning")` — same call shape as `generate_estimation`, no `two_phase` branch.
  - `user_message = _estimation_user_message(transcription, None)`.
  - `start = time.monotonic()`; dispatch to `_stream_openai(...)` or `_stream_anthropic(...)` based on `settings.llm_provider` (raise the same `HTTPException(500, "Unsupported LLM provider")` for anything else, mirroring `_complete`); `async for chunk in <dispatched stream>: yield chunk`; after the loop, set `metrics.latency_ms = int((time.monotonic() - start) * 1000)`.
- Add `async def _stream_openai(system_prompt, user_message, settings, model, max_tokens, metrics) -> AsyncIterator[str]`:
  - Build the same `messages`/`kwargs` (`max_completion_tokens`) as `_call_openai`, plus `stream=True, stream_options={"include_usage": True}`.
  - Wrap only the `await client.chat.completions.create(...)` call in `try/except Exception as exc: _raise_provider_http_error("OpenAI", exc, _OPENAI_ERRORS)` (same as `_call_openai` — mid-stream network errors are out of scope, matching the existing non-streaming coverage level).
  - `async for chunk in stream:` — set `metrics.model = chunk.model or metrics.model`; if `chunk.choices` and `chunk.choices[0].delta.content`, `yield` it; if `chunk.usage`, set `metrics.input_tokens = chunk.usage.prompt_tokens` and `metrics.output_tokens = chunk.usage.completion_tokens`.
- Add `async def _stream_anthropic(system_prompt, user_message, settings, model, max_tokens, metrics) -> AsyncIterator[str]`:
  - `client = AsyncAnthropic(api_key=settings.anthropic_api_key)`.
  - `try: async with client.messages.stream(model=model, max_tokens=max_tokens or _ANTHROPIC_DEFAULT_MAX_TOKENS, system=system_prompt, messages=[{"role": "user", "content": user_message}]) as stream:` — inside, `async for text in stream.text_stream: yield text`, then `final = await stream.get_final_message()`, set `metrics.model = final.model`, `metrics.input_tokens = final.usage.input_tokens`, `metrics.output_tokens = final.usage.output_tokens`. `except Exception as exc: _raise_provider_http_error("Anthropic", exc, _ANTHROPIC_ERRORS)` around the whole `async with` block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_service_streaming.py tests/test_llm_service.py -v`
Expected: all PASS (new streaming tests + all 27 pre-existing `test_llm_service.py` tests unchanged).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: `141 + <new count> passed`.

- [ ] **Step 6: Commit**

```bash
git add app/services/llm_service.py tests/_fakes.py tests/test_llm_service_streaming.py
git commit -m "feat(estimador-cag): add streaming estimation with per-provider metrics"
```

---

### Task 2: Streamlit support utilities (env secrets + async→sync bridge)

**Files:**
- Create: `app/streamlit_support.py`
- Create: `tests/test_streamlit_support.py`

**Interfaces:**
- Produces: `def sync_secrets_to_env(secrets: Mapping[str, str], environ: MutableMapping[str, str]) -> None` — copies `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` from `secrets` into `environ` **only** for keys not already present in `environ` (env wins over `st.secrets`), ignoring any other key in `secrets`.
- Produces: `def iter_sync(async_gen: AsyncIterator[str]) -> Iterator[str]` — drives an async generator to completion on a private event loop, yielding each item synchronously (for `st.write_stream`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_streamlit_support.py`:

```python
from app.streamlit_support import iter_sync, sync_secrets_to_env


def test_sync_secrets_to_env_copies_known_keys():
    secrets = {"OPENAI_API_KEY": "sk-from-secrets", "SOME_OTHER_KEY": "ignored"}
    environ: dict = {}

    sync_secrets_to_env(secrets, environ)

    assert environ == {"OPENAI_API_KEY": "sk-from-secrets"}


def test_sync_secrets_to_env_does_not_override_existing_env():
    secrets = {"OPENAI_API_KEY": "sk-from-secrets"}
    environ = {"OPENAI_API_KEY": "sk-from-env"}

    sync_secrets_to_env(secrets, environ)

    assert environ["OPENAI_API_KEY"] == "sk-from-env"


def test_sync_secrets_to_env_handles_empty_secrets():
    environ: dict = {"PATH": "/usr/bin"}

    sync_secrets_to_env({}, environ)

    assert environ == {"PATH": "/usr/bin"}


async def _fake_stream():
    yield "Hola "
    yield "mundo"


def test_iter_sync_yields_chunks_in_order():
    assert list(iter_sync(_fake_stream())) == ["Hola ", "mundo"]


async def _empty_stream():
    return
    yield  # pragma: no cover - makes this an async generator


def test_iter_sync_empty_generator_yields_nothing():
    assert list(iter_sync(_empty_stream())) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_streamlit_support.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.streamlit_support'`).

- [ ] **Step 3: Implement `app/streamlit_support.py`**

- `sync_secrets_to_env`: iterate over `("OPENAI_API_KEY", "ANTHROPIC_API_KEY")`; for each name, if `name not in environ` and `name in secrets`, set `environ[name] = secrets[name]`.
- `iter_sync`: create `loop = asyncio.new_event_loop()`; in a `try/finally` (closing the loop in `finally`), loop calling `loop.run_until_complete(async_gen.__anext__())` inside a `try/except StopAsyncIteration: return`, yielding each result.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_streamlit_support.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/streamlit_support.py tests/test_streamlit_support.py
git commit -m "feat(estimador-cag): add streamlit support utilities for secrets and async streaming"
```

---

### Task 3: `streamlit_app.py` chat UI

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (already updated in the working tree by `uv add streamlit`; committed here)
- Create: `streamlit_app.py`
- Create: `tests/test_streamlit_app.py`

**Interfaces:**
- Consumes: `generate_estimation_stream`, `StreamMetrics`, `build_system_prompt` from `app.services.llm_service`; `select_examples` from `app.context.examples`; `DEFAULT_NUM_EXAMPLES` from `app.schemas.estimation`; `sync_secrets_to_env`, `iter_sync` from `app.streamlit_support`.
- Produces: nothing importable — `streamlit_app.py` is a script run by `streamlit run` / `AppTest.from_file`. Tests patch `app.services.llm_service.AsyncOpenAI` (as in Task 1), since `generate_estimation_stream` is called through, not reimplemented.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_streamlit_app.py`:

```python
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests._fakes import openai_settings, openai_stream_chunks, patch_openai_stream, patch_settings

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def _fresh_app(mocker):
    patch_settings(mocker, openai_settings())
    return AppTest.from_file(APP_PATH)


def test_empty_chat_shows_no_messages(mocker):
    at = _fresh_app(mocker).run()

    assert at.exception == []
    assert len(at.chat_message) == 0


def test_sending_message_shows_estimation(mocker):
    patch_openai_stream(mocker, openai_stream_chunks(["## Estimación: Demo"]))
    at = _fresh_app(mocker).run()

    at.chat_input[0].set_value("Transcripción de prueba suficientemente larga para pasar validación").run()

    assert at.exception == []
    assert len(at.chat_message) == 2
    assert at.chat_message[0].markdown[0].value == (
        "Transcripción de prueba suficientemente larga para pasar validación"
    )
    assert "Estimación" in at.chat_message[1].markdown[0].value


def test_history_persists_across_turns(mocker):
    patch_openai_stream(mocker, openai_stream_chunks(["Respuesta 1"]))
    at = _fresh_app(mocker).run()
    at.chat_input[0].set_value("Primera pregunta suficientemente larga para el test").run()

    patch_openai_stream(mocker, openai_stream_chunks(["Respuesta 2"]))
    at.chat_input[0].set_value("Segunda pregunta suficientemente larga para el test").run()

    assert at.exception == []
    assert len(at.chat_message) == 4
    assert at.chat_message[1].markdown[0].value == "Respuesta 1"
    assert at.chat_message[3].markdown[0].value == "Respuesta 2"


def test_sidebar_shows_prompt_examples_and_metrics(mocker):
    patch_openai_stream(
        mocker,
        openai_stream_chunks(["## Estimación: Demo"], prompt_tokens=111, completion_tokens=22),
    )
    at = _fresh_app(mocker).run()
    at.chat_input[0].set_value("Transcripción de prueba suficientemente larga para pasar validación").run()

    assert at.exception == []
    prompt_text_areas = [ta.value for ta in at.sidebar.text_area]
    assert any("Senior Software Estimation Architect" in v for v in prompt_text_areas)

    sidebar_markdown = " ".join(m.value for m in at.sidebar.markdown)
    assert "Plataforma de Gestión de Inventario" in sidebar_markdown  # first catalog example

    metric_values = {m.label: m.value for m in at.sidebar.metric}
    assert metric_values["Tokens de entrada"] == "111"
    assert metric_values["Tokens de salida"] == "22"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_streamlit_app.py -v`
Expected: FAIL (`streamlit_app.py` does not exist yet — `AppTest.from_file` raises `FileNotFoundError`).

- [ ] **Step 3: Implement `streamlit_app.py`**

Structure (top to bottom):

1. Imports: `os`, `streamlit as st`, `app.services.llm_service.{generate_estimation_stream, StreamMetrics, build_system_prompt}`, `app.context.examples.select_examples`, `app.schemas.estimation.DEFAULT_NUM_EXAMPLES`, `app.streamlit_support.{sync_secrets_to_env, iter_sync}`.
2. Best-effort secrets sync, guarded — `st.secrets` raises when no `secrets.toml` exists: `try: sync_secrets_to_env(st.secrets, os.environ) \n except Exception: pass`.
3. `st.set_page_config(page_title="Estimador CAG")`; `st.title("Estimador CAG")`.
4. Session state init: `st.session_state.setdefault("messages", [])`, `st.session_state.setdefault("last_metrics", None)`.
5. Render history: loop `st.session_state.messages`, `with st.chat_message(msg["role"]): st.markdown(msg["content"])`.
6. `prompt = st.chat_input("Pega aquí la transcripción de la reunión...")`.
7. `if prompt:` — append `{"role": "user", "content": prompt}` to `st.session_state.messages` and render it via `st.chat_message("user")`; then `with st.chat_message("assistant"): metrics = StreamMetrics(); response = st.write_stream(iter_sync(generate_estimation_stream(prompt, metrics)))`; append `{"role": "assistant", "content": response}`; set `st.session_state.last_metrics = metrics`.
8. Sidebar (rendered **after** step 7 so it reflects the metrics from the message just handled, without needing `st.rerun()`):
   - `st.sidebar.header("Contexto CAG")`.
   - `st.sidebar.text_area("System prompt", value=build_system_prompt(), height=300, disabled=True)`.
   - `st.sidebar.subheader("Ejemplos históricos")`; loop `select_examples(DEFAULT_NUM_EXAMPLES)`, for each `ex`: `st.sidebar.markdown(f"**{ex.title}**")` and `st.sidebar.caption(ex.meeting_summary)`.
   - `st.sidebar.subheader("Última llamada")`; `if st.session_state.last_metrics:` four `st.sidebar.metric(...)` calls with labels `"Modelo"`, `"Tokens de entrada"`, `"Tokens de salida"`, `"Latencia (ms)"` and the corresponding `StreamMetrics` fields; `else: st.sidebar.caption("Aún no se ha generado ninguna estimación.")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_streamlit_app.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests passed (baseline 141 + Task 1 + Task 2 + Task 3 new tests), 0 failed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock streamlit_app.py tests/test_streamlit_app.py
git commit -m "feat(estimador-cag): add Streamlit chat UI with streaming and CAG sidebar"
```

---

### Task 4: README + manual verification

**Files:**
- Modify: `README.md` (add a short "Interfaz conversacional (Streamlit)" section)

**Interfaces:** none (docs + manual verification only).

- [ ] **Step 1: Update `README.md`**

Add a new section after "## Ejecución local" (before "## Ejecución con Docker") titled `## Interfaz conversacional (Streamlit)` covering:
- One command to launch it: `uv run streamlit run streamlit_app.py`.
- What it does: paste a transcript in the chat, watch the estimation stream in; history persists for the session.
- API key resolution: `.env` (same `get_settings()` as the API) or `st.secrets` (`.streamlit/secrets.toml`, not committed) — never hardcoded.
- Sidebar contents: active system prompt, the CAG historical examples in use, and metrics (model, input/output tokens, latency) from the last call.
- One line noting it calls the same `generate_estimation_stream`/`build_system_prompt` used by `/api/v1/estimate`, so behavior stays in sync with the API.

- [ ] **Step 2: Full verification run**

Run: `uv run pytest -q`
Expected: all tests pass, no regressions vs. the Task 3 count.

Run: `uv run streamlit run streamlit_app.py --server.headless true &` then check it serves (`curl -sf http://localhost:8501/_stcore/health`), then stop it. Requires a real `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in `.env` to actually send a message — if none is configured in this environment, verify at least that the app boots and the chat/sidebar render (empty-state), and note in the final summary that live-provider streaming needs manual confirmation with real credentials.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(estimador-cag): document the Streamlit chat interface"
```
