# Proposal

## Why

El estimador valida la forma y las reglas de negocio de su respuesta, pero nadie revisa su contenido: una suma correcta puede ocultar alucinaciones, fases desequilibradas, supuestos que faltan o un enfoque que no encaja con la audiencia. Una segunda lectura independiente, con una decisión explícita y auditable sobre qué hacer con ella, mejora la calidad sin cambiar el endpoint normal.

## What Changes

- **Contrato del crítico**: `CriticIssue` (categoría `math_error`, `hallucination`, `scope_mismatch`, `phase_imbalance`, `missing_assumption`, `unrealistic_estimate` o `tier_mismatch`; severidad `critical`, `major` o `minor`; campo afectado, descripción y corrección sugerida) y `CriticFeedback` (veredicto `accept`, `needs_iteration` o `reject`; confianza de la revisión). `needs_iteration` exige al menos un defecto crítico o mayor y `reject` exige una explicación.
- **Servicio crítico independiente**: recibe transcripción, metadatos, audiencia y la estimación generada, devuelve feedback estructurado y no toca la sesión. Usa `CRITIC_MODEL` y plantillas Jinja2 versionadas.
- **Orquestador Actor–Critic–Boss**: genera una estimación (actor), pide su revisión (crítico) y decide en código (Boss, sin llamada propia al LLM): aceptar, regenerar incorporando el feedback, o devolver el último borrador con reservas cuando se rechaza o se agotan las iteraciones. El máximo de iteraciones es configurable (`BOSS_MAX_ITERATIONS`, por defecto 3).
- **Feedback en la regeneración**: los defectos y sugerencias se incorporan al prompt de la siguiente generación; en la sesión solo se guarda el resultado final como turno.
- **Traza de auditoría**: por iteración, veredicto, confianza, resumen de defectos y decisión del Boss; total de iteraciones y decisión final.
- **`POST /api/v1/sessions/{id}/estimate-acb`**: mismo contrato multipart que el endpoint conversacional (más `tier` opcional); la respuesta añade la traza. El endpoint normal no cambia.

**No incluido**: crítico con herramientas externas o búsqueda web, un Boss basado en LLM, streaming del flujo ACB, cambios en los clientes web.

## Capabilities

### New Capabilities
- `estimator/critic-contract`: modelos del feedback del crítico, validaciones y servicio de revisión independiente.
- `estimator/actor-critic-boss`: orquestación, decisiones del Boss, regeneración con feedback y traza de auditoría.

### Modified Capabilities
- `estimator/session-estimation`: endpoint `estimate-acb`.
- `estimator/prompt-templates`: plantillas del crítico y del feedback de regeneración.
- `estimator/task-model-configuration`: `BOSS_MAX_ITERATIONS`.

## Impact

- Código: `app/schemas/{critic,acb}.py`, `app/services/{critic,boss,acb}.py` (nuevos), `session_estimation.py` (separación en borrador y confirmación), `routers/sessions.py`, `config.py`, `prompts/auxiliary/critic/v1/`.
- API aditiva; el endpoint normal conserva su contrato y comportamiento. El flujo ACB hace como mínimo dos llamadas al LLM adicionales (crítico) por estimación.
- Pruebas con dobles de los proveedores; verificación en contenedores Docker.
