# Design

## Context

La referencia reorganizó el servicio de una vez (`foundation/domain/generation/ingestion/api`). El repo 1 ya tiene `ingestion/` con la misma estructura, pero el resto está plano y con acoplamientos que una reorganización estricta no puede resolver moviendo archivos: por ejemplo `prompts.loader` importa `schemas` y `services.sessions`, `schemas.sessions` importa `services.audience`, y el wrapper del LLM importa la caché.

## Decisions

**Adaptación progresiva, no reescritura.** Se mueven los módulos con `git mv` y se reescriben los imports; no se toca la lógica. Así los 1105 tests existentes validan la reorganización y el historial de git conserva el origen de cada archivo. Una reorganización con refactor de acoplamientos arriesgaba romper `/api/v1/...` sin aportar funcionalidad.

**Dónde cae cada módulo propio del repo 1.**

| Módulo del repo 1 | Capa | Motivo |
|---|---|---|
| `validation.py`, `audience.py`, `history.py`, `evaluation.py` | `domain/` | reglas de negocio y servicios de dominio sobre los contratos |
| `pipeline.py`, `session_estimation.py`, `acb.py` | `domain/` (conductores) | componen cag + conversación + agentes; la referencia los junta en un único `EstimationService`, aquí se conservan tres porque cada uno es un flujo distinto con sus tests |
| `boss.py`, `critic.py` | `generation/agentic/` | |
| `sessions.py`, `anchors.py`, `compression.py`, `summarizer.py`, `context.py` | `generation/conversation/` | memoria conversacional |
| `streamlit_*.py`, `evals/`, `scripts/` | fuera de las capas | clientes HTTP o herramientas; documentados en `ARCHITECTURE.md` |

**Conductor: tres módulos, no uno.** La referencia concentra `estimate`, `estimate_conversational` y `estimate_with_acb` en una clase. Aquí `pipeline`, `session_estimation` y `acb` ya existen, tienen contratos propios y pruebas; fusionarlos habría sido una reescritura sin beneficio. La regla se mantiene: solo `domain/` importa de varios hermanos de `generation`.

**División de la caché.** `cache.py` mezclaba el almacén Redis (lo usa el wrapper de LLM, fontanería) con la clave y el modelo del resultado validado (lo usa el CAG). Mantenerlos juntos obligaba a `foundation` a importar de `generation`. Se separan: `foundation/llm/cache.py` y `generation/cag/exact.py` (que reexporta `EstimationCache` por comodidad).

**Fábricas fuera de los dominios.** Los factories con `Depends` en los servicios hacían que `domain` importara de FastAPI. Ahora `domain/` no conoce `dependencies`; `get_actor_critic_boss` se compone en `dependencies.py`.

**Deuda registrada, no escondida.** Siete aristas incumplen la regla (contratos que dependen de tipos de servicio y `foundation` que renderiza o valida contratos de `domain/schemas`). Resolverlas implica mover tipos y partir módulos, fuera de alcance. `KNOWN_VIOLATIONS` las lista con su motivo; el test falla si aparece una violación nueva o si una resuelta sigue en la lista.

**Diferencias con la referencia.** (1) Tres conductores en lugar de uno. (2) `foundation/llm/embeddings.py` se conserva (el embedder async ya lo usa la caché semántica). (3) La referencia cumple la regla de capas sin excepciones; aquí hay siete aristas de deuda. (4) El store de sesiones lee `app.config.get_settings()` en vivo (ver `CLAUDE.md`).

## Risks / Trade-offs

- Un parche de prueba con la ruta antigua (`mocker.patch("app.services...")`) falla al ejecutarse; se corrigió con la suite completa.
- `app.dependencies` importa casi todo: cualquier import circular se nota al arrancar. La suite lo cubre.
- Quien tenga ramas con las rutas antiguas verá conflictos de renombrado; el apéndice de `ARCHITECTURE.md` da el mapa.
