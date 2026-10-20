# estimator/turn-observability Specification

## Purpose
Hacer observable qué ocurre en cada turno de una sesión conversacional (tamaño del contexto, tokens, coste, latencia, memoria) por logs y por HTTP.

## Requirements

### Requirement: Evento turn_observed
Al confirmar un turno de sesión, tras la compresión y antes de devolver, el sistema SHALL emitir un evento structlog `turn_observed` con `turn_index` (1-based por sesión, no limitado por la ventana), `session_id`, `enriched_transcript_chars`, `attachments_total_chars`, `messages_in_window`, `anchors_count`, `summary_chars`, `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `cache_hit_kind` (`none`, `exact` o `semantic`) y `last_resolved_tier`. El evento SHALL NOT incluir texto del usuario ni del modelo.

#### Scenario: Turno completado
- **WHEN** se completa el tercer turno de una sesión con un adjunto de 1 000 caracteres
- **THEN** se emite un `turn_observed` con `turn_index` 3 y `attachments_total_chars` 1000 en el que `messages_in_window` es el de la ventana tras comprimir.

#### Scenario: Índice más allá de la ventana
- **WHEN** se completa el turno 9 de una sesión con ventana de 6 turnos
- **THEN** `turn_index` es 9 y `messages_in_window` es 12.

#### Scenario: Turno fallido
- **WHEN** un turno falla antes de confirmarse
- **THEN** no se emite `turn_observed` y el índice del siguiente turno no se consume.

### Requirement: Último turno en el estado de sesión
`GET /api/v1/sessions/{id}` SHALL incluir `last_turn` con los mismos campos que el evento (nulo antes del primer turno) sin ejecutar ninguna llamada al LLM. Con `include_memory=true` SHALL añadir el resumen y las anclas; sin ese parámetro SHALL NOT devolver texto de la conversación. Los campos existentes SHALL conservar su significado.

#### Scenario: Estado tras un turno
- **WHEN** se consulta una sesión que completó un turno
- **THEN** `last_turn.turn_index` es 1 y los tokens y el coste coinciden con los del evento.

#### Scenario: Sin turnos
- **WHEN** se consulta una sesión recién creada
- **THEN** `last_turn` es nulo.

#### Scenario: Memoria opcional
- **WHEN** se consulta con `include_memory=true`
- **THEN** la respuesta incluye el resumen y los textos de las anclas.
