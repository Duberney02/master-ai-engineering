# Design

## Context

La API (`estimador-cag`) expone `POST /api/v1/estimate`, sin estado: `EstimationPipeline` renderiza `(system, user)` desde plantillas Jinja2 versionadas, llama al LLM a través de `LLMWrapper` (caché, reintentos, fallback) y valida con `validate_text`. Los SDK son asíncronos y los errores de proveedor se saneán. Los tres clientes (Streamlit, Rails y React) consumen esa API por HTTP; solo Streamlit y React usan `/api/v1/*` desde el navegador a través de nginx. Ver `proposal.md` para la motivación.

## Goals / Non-Goals

**Goals:**
- Memoria conversacional en el proceso con ventana deslizante y hechos del proyecto.
- Reutilizar el esquema, las validaciones, los guardrails y el wrapper de proveedor existentes.
- Adjuntos PDF/Word con extracción local y acotada.

**Non-Goals:**
- Persistencia, Redis, resumen acumulativo, anclas, tier dinámico, búsqueda web, function calling o Actor-Critic-Boss.
- Compartir sesiones entre procesos o réplicas.
- Streaming de la estimación de sesión (el endpoint devuelve JSON).

## Decisions

**Rutas bajo `/api/v1`.** `POST /api/v1/sessions` y `POST /api/v1/sessions/{id}/estimate`, como el resto de routers y como el proxy nginx de la web React (`/api/`). Alternativa: rutas en la raíz; descartada por romper el prefijo común y el proxy.

**Módulo `app/services/sessions.py`** con `ConversationHistory`, `ProjectMetadata`, `Session` y `SessionStore`. `ProjectMetadata` es un modelo Pydantic y vive allí porque es parte del estado de sesión; `schemas/sessions.py` solo define los contratos HTTP. El almacén es un `dict` con `time.monotonic()` para caducidad (TTL de inactividad) y tope de sesiones (expulsa primero caducadas, luego la menos reciente); se accede desde el bucle de eventos único sin hilos, y cada sesión lleva un `asyncio.Lock` para serializar peticiones concurrentes. La volatilidad se acepta porque la memoria es un acelerador de contexto, no un registro: el historial de estimaciones durable ya existe en PostgreSQL, y perder una sesión solo obliga a reexplicar el contexto.

**Ventana deslizante contando el turno en curso.** `ConversationHistory` guarda pares completos (`add_turn(user, assistant)`) con `max_turns` (6 por defecto, configurable con `SESSION_MAX_TURNS`). `Session.to_messages_list(render_system, user_message)` devuelve `[system] + últimos (max_turns-1) pares + user_message`, de modo que el LLM nunca ve más de `max_turns` turnos contando el actual; tras guardar el turno el historial conserva `max_turns` pares. El system prompt no forma parte de los pares, así que nunca se descarta y se regenera en cada llamada con los metadatos vigentes. Alternativa: enviar `max_turns` pares previos más el actual (7 turnos); descartada porque contradice «máximo de turnos».

**Mensajes multi-turno en `llm_service` con cambio mínimo.** El parámetro `user_message` de `_call_openai`, `_call_anthropic` y `LLMWrapper` admite `str` o una lista de `{role, content}`; `generate_from_messages(messages, accept)` separa el system prompt y delega en `_complete`. La clave de caché de completions incorpora la lista completa de mensajes, de modo que no se mezclan conversaciones distintas. Las cachés exacta y semántica del pipeline se omiten en sesiones porque su resultado depende del historial. Alternativa: reescribir los adaptadores a mensajes; descartada por tocar rutas de streaming y pruebas existentes sin necesidad.

**Orquestación en `SessionEstimationService`** (inyectable con `Depends`, sustituible en pruebas): construye la `EstimationRequest` con el texto combinado, aplica `InputGuardrails`, renderiza el prompt de sistema con metadatos y el mensaje de usuario con `user.j2`, llama al LLM con corrección automática en la misma conversación (la respuesta inválida y el mensaje de corrección se añaden solo a la llamada, no al historial), valida con `validate_text`, aplica el filtro de fuera de alcance, extrae metadatos, guarda el turno y persiste en el historial PostgreSQL si está habilitado. Todo ocurre bajo el lock de la sesión y el estado solo se modifica al final: un fallo no deja la sesión a medias. Un fallo de la llamada de metadatos nunca falla la estimación.

**Plantillas.** Un parcial compartido `project_metadata.j2` se incluye desde `system.j2` de v1, v2 y v3 y se renderiza solo cuando el contexto trae `project_metadata` (en sesión, aunque esté vacío). Sin metadatos el prompt es byte a byte el actual, de modo que las cachés y los tests existentes no cambian. Los valores se normalizan en `ProjectMetadata` (una línea, sin `<`, `>` ni caracteres de control, longitudes acotadas), porque los metadatos los produce el LLM a partir de entrada del usuario y se reinyectan en el prompt de sistema: sin esa normalización una transcripción podría persistir instrucciones en el system prompt de turnos posteriores.

**Extracción de metadatos con una llamada LLM** (plantilla `metadata_extraction.j2`, JSON validado con `ProjectMetadata`) en lugar de regex sobre la respuesta: la información está en lo que dice el usuario y en matices («creo que seremos unos cinco») que un patrón no captura; el JSON validado da un contrato verificable; el coste es una llamada corta y no bloquea el resultado si falla. La fusión es determinista en código (listas unidas sin duplicados, valores nuevos no nulos sustituyen), de modo que el modelo no puede borrar hechos conocidos. Se documenta en el README.

**Adjuntos con extracción local** (`pypdf` y `python-docx`) en `app/services/attachments.py`: el texto resultante pasa por los mismos guardrails (PII, inyección, moderación) y el mismo límite de longitud que una transcripción pegada, funciona igual con cualquier proveedor y no depende de capacidades de archivos de OpenAI o Anthropic ni de enviar documentos completos a un tercero. Coste: se pierde la información visual (imágenes, tablas escaneadas). La extracción es síncrona y se ejecuta con `asyncio.to_thread`. Defensas: tamaño máximo por archivo y número máximo de archivos, comprobación de firma (`%PDF-`, `PK`), tope de páginas, tope de tamaño descomprimido de `.docx`, rechazo de PDF cifrados y de contenido sin texto, nombre saneado para que no pueda falsificar separadores.

**Clientes.** Streamlit usa `httpx` síncrono con multipart y guarda `session_id` y metadatos en `st.session_state`; React guarda el estado en un contexto a nivel de `App` (sobrevive a la navegación entre pantallas, se reinicia al recargar) y envía `FormData`; Rails guarda `session_id` y los metadatos en la cookie de sesión de Rails. Los tres tratan 404 de sesión creando una conversación nueva. La sesión se crea de forma perezosa en el primer render, no en cada recarga de componente.

## Risks / Trade-offs

- [Pérdida de sesiones al reiniciar o con varias réplicas] → documentado; el cliente detecta el 404 y abre una conversación nueva; despliegue de un único proceso en Compose.
- [Crecimiento de memoria] → tope de sesiones, TTL de inactividad y tope de turnos por sesión.
- [Inyección persistente vía metadatos] → normalización, tope de longitud y marcado como datos en la plantilla.
- [Coste y latencia de la llamada adicional] → prompt corto, `max_tokens` acotado, ejecución tras la estimación y fallo tolerado.
- [Transcripciones largas repetidas en el historial] → la ventana acota el contexto a 6 turnos; el límite de 80 000 caracteres por turno se mantiene.
- [Los turnos cortos (< 20 caracteres) se rechazan] → hereda el mínimo de la solicitud estructurada; aceptado para no duplicar validaciones.
