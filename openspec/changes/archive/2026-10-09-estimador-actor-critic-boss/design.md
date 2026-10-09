# Design

## Context

`SessionEstimationService.estimate` hace todo bajo el cerrojo de la sesión: guardrails, generación con corrección automática, extracción de metadatos, confirmación del turno, compresión de memoria. Para iterar hay que separar «generar un borrador» (sin efectos sobre la sesión) de «confirmar el turno» (efectos).

## Goals / Non-Goals

**Goals:** una revisión independiente y estructurada; decisiones del Boss deterministas y auditables; un único turno final en la conversación; reutilizar guardrails, validaciones, métricas, fallback y persistencia.

**Non-Goals:** herramientas externas para el crítico, Boss con LLM, streaming del flujo ACB.

## Decisions

**Borrador y confirmación separados.** `SessionEstimationService` expone `draft(...)` (renderiza los mensajes, genera con validación y corrección automática y devuelve un `Draft` con el resultado, el texto y las completions, sin tocar la sesión) y `commit(...)` (extrae metadatos, registra el turno, recuerda la audiencia y ejecuta la política de compresión). `estimate` pasa a ser `draft` + `commit` bajo el cerrojo, con el mismo comportamiento y las mismas pruebas. El orquestador mantiene el cerrojo durante todo el bucle, de modo que el turno siguiente de la sesión espera al final y una excepción en cualquier punto (502 del actor, por ejemplo) deja la sesión intacta.

**Crítico independiente.** `CriticService.review(transcript, metadata, audience, estimation)` renderiza la plantilla `critic/v1` con esos cuatro datos (la estimación como JSON), llama al LLM con `CRITIC_MODEL` mediante la primitiva `generate_structured` (JSON validado con `CriticFeedback`, un reintento con mensaje de corrección) y devuelve el feedback junto a las completions para las métricas. No recibe la sesión: no puede modificarla. La transcripción y los metadatos se presentan como datos delimitados.

**Contrato del crítico.** `CriticFeedback` valida en un `model_validator`: `needs_iteration` requiere al menos un defecto `critical` o `major` (si solo hay menores, el veredicto coherente es `accept`) y `reject` requiere una explicación no vacía. La confianza es un número entre 0 y 1. Los textos libres se normalizan (sin `<`, `>` ni acentos graves, sin caracteres de control) porque se reinyectan en el prompt del actor.

**Boss en código.** `decide(feedback, iteration, max_iterations)` es una función pura: `accept` → aceptar; `reject` → devolver con reservas; `needs_iteration` → regenerar si quedan iteraciones y, si no, devolver con reservas. No consulta la confianza: es informativa en la traza. Si el crítico falla (proveedor caído, JSON inválido tras el reintento), el Boss no puede decidir sobre una revisión que no existe: devuelve el borrador con reservas y la traza marca `critic_error`. Un fallo del crítico no debe convertir una estimación válida en un 502.

**Iteraciones.** `BOSS_MAX_ITERATIONS` (1–5, por defecto 3) es el número máximo de generaciones del actor, contando la primera. Con 1 el flujo es generar, revisar y devolver (con reservas si hay defectos).

**Regeneración con feedback.** La siguiente generación recibe los mismos mensajes base más la respuesta anterior del actor y un mensaje de usuario renderizado desde la plantilla `critic/v1/feedback.j2` con los defectos, sus correcciones sugeridas y la explicación. Es la misma técnica que la corrección de validación: esos mensajes solo viven en la llamada y nunca llegan al historial. Al terminar se confirma una sola vez el turno con el mensaje de usuario original y la respuesta final.

**Métricas y coste.** Las completions de borradores anteriores y del crítico se suman a las del turno (tokens y coste) y la última completion del resultado es la del borrador final, como en el flujo normal.

**Traza.** `AuditTrace` contiene una `AuditIteration` por vuelta (número, veredicto del crítico o `null`, confianza, `DefectSummary` con el recuento por severidad y las categorías, decisión del Boss), `total_iterations`, `final_decision` (`accepted` o `returned_with_reservations`) y `reservations` (descripciones de los defectos pendientes o la explicación del rechazo, vacío si se aceptó). No incluye texto del usuario.

**Endpoint.** `POST /sessions/{id}/estimate-acb` comparte con el endpoint conversacional el análisis del formulario, los adjuntos, la validación y el guardado en PostgreSQL (una única vez, con el resultado final); solo difiere en el servicio invocado y en la respuesta (`AcbEstimationResponse` = `SessionEstimationResponse` + `audit_trace`).

## Risks / Trade-offs

- Latencia y coste: como mínimo una llamada de revisión extra y, por cada regeneración, otra de generación y otra de revisión.
- El crítico puede equivocarse: la traza y las reservas hacen visible la discrepancia en lugar de ocultarla, y el Boss limita las vueltas.
- Un crítico con el mismo modelo que el actor comparte sus sesgos; `CRITIC_MODEL` permite usar otro.
