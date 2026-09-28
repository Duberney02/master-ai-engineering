# Spec: Interfaz conversacional con Streamlit (session 3)

Estado: aprobado por el usuario, fase de diseño cerrada. No reabrir discusión de
alcance; solo señalar contradicciones o bloqueos reales encontrados durante la
implementación.

## Objetivo

Pegar una transcripción de reunión en un chat web (Streamlit) y ver la
estimación del LLM generándose en streaming, sin curl/Postman/Swagger.

Fichero de entrada: `estimador-cag/streamlit_app.py`, ejecutado con
`streamlit run streamlit_app.py`.

## Alcance funcional

### Nivel 1 — Chat básico (obligatorio)

- `st.chat_message` + `st.chat_input` para escribir/pegar una transcripción.
- El texto se envía al LLM reutilizando `generate_estimation`/las funciones de
  `app/services/llm_service.py` ya existentes (nueva función de streaming, ver
  abajo) — no se reimplementa la llamada al proveedor.
- Historial visible durante la sesión vía `st.session_state`.
- El system prompt es exactamente `build_system_prompt()` con las opciones por
  defecto (`GenerationOptions()`), igual que usa el endpoint `/api/v1/estimate`
  cuando no se pasan opciones.
- Sin `preprocessing` ni selección de opciones en la UI (fuera de alcance de
  esta sesión) — solo transcripción → estimación.
- API key nunca hardcodeada.

### Nivel 2 — Streaming (obligatorio)

- La respuesta se muestra token a token (`st.write_stream` o placeholder +
  delta).
- Debe funcionar con OpenAI y Anthropic (los dos proveedores ya soportados).
- Nueva función `generate_estimation_stream()` en `llm_service.py`:
  - No modifica ni rompe `generate_estimation()` ni sus tests.
  - Es un generador asíncrono que produce fragmentos de texto (`str`).
  - Al terminar el stream deja disponibles las métricas (modelo, tokens de
    entrada, tokens de salida, latencia) escribiéndolas en un objeto mutable
    que el llamador pasa por parámetro (mismo patrón que `PhaseResult`, ya
    que un generador asíncrono no puede `return` un valor por PEP 525).
  - Reutiliza `build_system_prompt()`, `_resolve_model()` y
    `_estimation_user_message()` — un único prompt builder compartido entre
    endpoint e interfaz.
  - Errores del proveedor se traducen igual que en `_complete` (reutilizar
    `_raise_provider_http_error` con los mismos mapas de excepciones).

### Nivel 3 — Contexto CAG en la interfaz

`st.sidebar` de solo lectura con:

- El system prompt activo (`build_system_prompt()` con defaults).
- El contexto estático inyectado: los ejemplos históricos (desde
  `app/context/examples.py`, misma fuente que usa el prompt — sin duplicar
  datos).
- Métricas de la última llamada: modelo, tokens de entrada, tokens de salida,
  tiempo de respuesta (ms). Vacío/placeholder antes de la primera llamada.

## Restricciones de diseño

- Una sola fuente de prompt builder y de ejemplos: `app/services/llm_service.py`
  y `app/context/examples.py`, sin duplicar lógica en `streamlit_app.py`.
- API key: `get_settings()` (Pydantic Settings, ya lee `.env`) o `st.secrets`.
  Si `st.secrets` trae `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` y no están en el
  entorno, se inyectan en `os.environ` **antes** de llamar a `get_settings()`
  (que cachea con `lru_cache`); nunca se escribe la key en código.
- Confirmar que `.env` sigue en `.gitignore` (ya lo está).
- Añadir `streamlit` a las dependencias del proyecto con `uv add streamlit`.
- Mantener estilo/estructura: Python 3.11, Pydantic Settings, tests con
  pytest y mocks de los SDK (reutilizar helpers de `tests/_fakes.py`).

## Tests

TDD (RED-GREEN-REFACTOR) para lo testeable:

- `generate_estimation_stream()`: SDKs de OpenAI/Anthropic mockeados con
  streaming simulado (iterador async de chunks / `messages.stream`), verifica
  fragmentos emitidos en orden, texto final concatenado, y métricas pobladas
  en el objeto mutable al terminar.
- Cálculo/población de métricas (modelo, input/output tokens, latencia) para
  ambos proveedores.
- Lectura de API key: entorno tiene prioridad, `st.secrets` como fallback,
  nunca hardcodeada.
- Interfaz con `streamlit.testing.v1.AppTest`: chat vacío (estado inicial),
  envío de un mensaje (aparece en historial + respuesta del asistente),
  historial persistente entre turnos, contenido del sidebar (system prompt,
  ejemplos, métricas tras una llamada).

La suite existente (141 tests a día de hoy en esta rama) debe seguir pasando
sin cambios.

## Criterios de aceptación

- [ ] `streamlit run streamlit_app.py` abre una interfaz de chat en el navegador.
- [ ] Al pegar una transcripción se recibe una estimación de software.
- [ ] La conversación persiste en pantalla; se pueden hacer varias preguntas seguidas.
- [ ] La respuesta se muestra en streaming, no de golpe.
- [ ] La API key sale de `.env` o `st.secrets`, no del código.
- [ ] El sidebar muestra el system prompt, los ejemplos y las métricas de la última llamada.
- [ ] Todos los tests pasan (los existentes y los nuevos).

## Fuera de alcance (explícito)

- Selección de `preprocessing`, `example_format`, `num_examples`, `model` o
  `max_tokens` desde la UI.
- Persistencia de la conversación entre sesiones/recargas del navegador.
- Autenticación de usuarios en la interfaz.
- Cálculo de costo (`estimated_cost_usd` sigue `null`, igual que el endpoint).
