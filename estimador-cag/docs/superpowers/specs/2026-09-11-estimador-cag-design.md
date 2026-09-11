# Design: estimador-cag — Software Estimation CAG API

**Date:** 2026-09-11  
**Status:** Approved

---

## 1. Purpose

A FastAPI backend that takes a meeting transcription and returns a structured software-project estimate. Estimation is driven by CAG (Context-Augmented Generation): historical estimation examples are injected verbatim into the LLM system prompt — no embeddings, no vector store, no retrieval step.

---

## 2. Constraints

- Python 3.11 (existing venv; all required typing features available on this version)
- Package manager: `uv` (existing uv.lock and uv_build backend retained)
- No LangChain, no RAG, no database
- No secrets in responses, logs, or repository
- `.env` git-ignored; `.env.example` versioned

---

## 3. Architecture

```
POST /api/v1/estimate
        │
        ▼
EstimationRequest (Pydantic) — validates transcription (min 20 chars)
        │
        ▼
llm_service.generate_estimation(transcription)
        │
        ├── build_system_prompt()
        │       └── role + rules + format spec + all ESTIMATION_EXAMPLES
        │
        ├── dispatch to OpenAI  (if LLM_PROVIDER=openai)
        │       └── AsyncOpenAI.chat.completions.create()
        │
        └── dispatch to Anthropic  (if LLM_PROVIDER=anthropic)
                └── AsyncAnthropic.messages.create()
        │
        ▼
LLMEstimationResult (dataclass)
  estimation, model, provider, input_tokens, output_tokens,
  total_tokens, estimated_cost_usd (null), generated_at, latency_ms
        │
        ▼
EstimationResponse (Pydantic) — JSON to caller
```

---

## 4. File Structure

```
estimador-cag/
├── app/
│   ├── __init__.py
│   ├── main.py               — FastAPI app, /health, router mount
│   ├── config.py             — BaseSettings + lru_cache + cross-field validation
│   ├── routers/
│   │   ├── __init__.py
│   │   └── estimations.py   — POST /api/v1/estimate, request/response schemas
│   ├── services/
│   │   ├── __init__.py
│   │   └── llm_service.py   — build_system_prompt(), generate_estimation()
│   └── context/
│       ├── __init__.py
│       └── examples.py      — ESTIMATION_EXAMPLES (2 few-shot entries)
├── docs/superpowers/specs/   — this file
├── src/estimador_cag/        — REMOVE (replaced by app/)
├── .env                      — git-ignored, placeholders
├── .env.example              — versioned
├── .gitignore
├── pyproject.toml            — updated deps + build config
└── README.md
```

---

## 5. Configuration (`app/config.py`)

`BaseSettings` via `pydantic-settings`. Fields:

| Variable | Type | Default | Notes |
|---|---|---|---|
| `openai_api_key` | `str \| None` | `None` | Required when provider=openai |
| `anthropic_api_key` | `str \| None` | `None` | Required when provider=anthropic |
| `llm_provider` | `Literal["openai","anthropic"]` | `"openai"` | Selects SDK path |
| `llm_model` | `str` | `"gpt-4o-mini"` | User override; per-provider default applied if this is the OpenAI default and provider=anthropic |
| `app_env` | `str` | `"development"` | |
| `log_level` | `str` | `"DEBUG"` | |

Cross-field `@model_validator`: raises `ValueError` if the active provider's API key is `None`.

Model default logic: if `llm_provider=anthropic` and `llm_model` is still the OpenAI default (`gpt-4o-mini`), substitute `claude-haiku-4-5`.

Exposed via `@lru_cache get_settings()`.

---

## 6. CAG Context (`app/context/examples.py`)

`ESTIMATION_EXAMPLES`: list of dicts with `meeting_summary` and `estimation` keys.

- Example 1: web inventory management platform (UI/UX, backend, auth, inventory, dashboard, testing, deploy)
- Example 2: online appointment/reservation system (booking flow, calendar, notifications, payments, admin panel)

Both entries contain realistic task breakdowns, hour tables, team profiles, risks.

---

## 7. System Prompt (`app/services/llm_service.py → build_system_prompt()`)

Structure injected as system role:

```
[Role declaration — Senior Software Estimation Architect]
[Rules: distinguish explicit requirements vs assumptions, no false precision,
        include forgotten tasks (QA, docs, DevOps, observability),
        identify risks, estimates are orientative not contractual]
[Output format specification — Markdown with defined sections]
[Historical examples — all ESTIMATION_EXAMPLES injected verbatim]
```

User message: raw transcription only.

---

## 8. LLM Service Dispatch

**OpenAI:** `AsyncOpenAI`, `chat.completions.create()`, model from config, temperature 0.3. Token usage from `response.usage`.

**Anthropic:** `AsyncAnthropic`, `messages.create()`, model from config (defaulted as above), `max_tokens=4096`. Token usage from `response.usage`.

Result normalised into `LLMEstimationResult` dataclass. `estimated_cost_usd` always `None` (documented as extension point).

---

## 9. Endpoint

```
POST /api/v1/estimate
Content-Type: application/json

{"transcription": "..."}   # min 20 chars, max 50 000 chars
```

Response:
```json
{
  "estimation": "## Estimación: ...",
  "model": "gpt-4o-mini",
  "provider": "openai",
  "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
  "estimated_cost_usd": null,
  "latency_ms": 0,
  "generated_at": "2026-09-11T..."
}
```

---

## 10. Health Check

```
GET /health
→ {"status":"healthy","environment":"...","provider":"...","model":"..."}
```

No LLM call. No secrets in response.

---

## 11. Error Handling

| Scenario | HTTP |
|---|---|
| Validation error (short/empty transcription) | 422 |
| Missing API key at startup | 500 on first request (config fails fast at startup) |
| Auth failure from provider | 502 |
| Provider timeout | 504 |
| Empty LLM response | 502 |
| Unknown provider | 500 |

Stack traces logged internally; never returned to caller.

---

## 12. Logging

Level from `LOG_LEVEL`. Logs: provider, model, transcription length (chars, not content), latency, token counts, outcome. Never logs: API keys, full transcription, auth headers.

---

## 13. `pyproject.toml` Changes

Add: `pydantic-settings>=2.0`, pin `openai>=1.0` (fix `>=3.13.0` typo).  
Entry point script removed (app runs via uvicorn directly).  
Build backend kept as `uv_build`.

---

## 14. Open Points / Limitations

- `estimated_cost_usd` always `null`; pricing table is a documented extension point
- No authentication on the API (out of scope for this exercise)
- All examples injected into every request; if examples grow large, context window pressure increases (acceptable for this exercise)
