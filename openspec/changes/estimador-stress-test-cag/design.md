# Design

## Context

El enunciado habla de `EstimationService.estimate_conversational()`, `MAX_ATTACHMENT_CHARS`, `evals/run.py` y cachés exacta/semántica por turno. En el código real de la sesión 5 (`feature/session_5_refined`, base de esta rama porque `master` no contiene ni la memoria con resumen/anclas ni los evals) los equivalentes son:

| Enunciado | Código real |
|---|---|
| `estimate_conversational()` | `SessionEstimationService.commit()` (lo comparten `/estimate` y `/estimate-acb`) |
| `evals/run.py` | `evals/runner.py` (`open_client`, `Client`, `MetricResult`) |
| `MAX_ATTACHMENT_CHARS=60.000` | no existe; el límite es `MAX_DESCRIPTION_CHARS=80_000` sobre transcripción + adjuntos (413 si se supera, **no** se trunca) |
| `last_resolved_tier` | audiencia resuelta (`resolution.audience`) |
| `cache_hit_kind` | las sesiones no usan la caché exacta ni la semántica del pipeline; solo la caché de completions del wrapper (Redis). Se informa `exact` si todas las completions del turno vinieron de ella, `semantic` si `outcome.cache_source == "semantic"` (hoy inalcanzable en sesiones) y `none` en otro caso |

Estas diferencias se documentan en el reporte; no se cambia ninguna constante ni la configuración del CAG.

## Decisions

**Dónde emitir.** `turn_observed` se emite al final de `commit()`, tras la compresión y antes del `return`, de modo que cubre `/estimate` y `/estimate-acb` y refleja ventana, anclas y resumen ya actualizados. Los datos salen de lo existente: `PipelineOutcome` (tokens, coste y latencia sumados sobre estimación, metadatos y compresión), `ConversationHistory` (ventana, anclas, resumen) y el `AudienceResolution`.

**Logs y `GET /sessions/{id}`: ambos.** El log (structlog) es la vía operativa estándar, pero un runner HTTP no puede leer los logs de un servidor remoto. Por eso la misma observación se guarda en `Session.last_turn` y `GET /sessions/{id}` la devuelve (`last_turn`, nulo antes del primer turno). Es aditivo y no ejecuta el LLM. El resumen y las anclas (texto del usuario) solo se devuelven con `?include_memory=true`, para que el estado por defecto siga sin exponer contenido.

**Campos nuevos y plomería mínima.** `Session.turns_total` cuenta los turnos confirmados (el tamaño de la ventana se estanca en `max_turns`, no sirve como índice). `EstimationRequest.attachments_chars` (excluido de la serialización) transporta los caracteres de adjuntos desde el router hasta `commit()` sin tocar las firmas de ACB. `app/logging_config.SAFE_FIELDS` admite los nuevos campos numéricos y el identificador de sesión.

**Escenarios.** Un escenario es una lista de `Turn(turn_index, transcript, fact_to_remember)` de 20 turnos; N ∈ {1, 3, 6, 10, 20} son *checkpoints* (prefijos): una sesión de 20 turnos produce los puntos de todos los N sin repetir llamadas. Los hechos son tokens distintivos (nombres propios, cifras) para que el match exacto no dependa de paráfrasis; `a|b` admite alternativas de formato (convención del dataset de evals).

**Adjuntos.** `build_pdfs.py` genera PDFs deterministas con `fpdf2` (sin compresión de contenido, para que el tamaño del archivo se aproxime al del texto), con hechos identificables al inicio, mitad y final; escribe un manifiesto con tamaño real y caracteres extraídos usando `extract_attachments` real. Se regeneran en cada ejecución del runner en un directorio ignorado por git. El adjunto se envía en el turno 1 (carga única, caso realista) con el mismo transcript corto en todos los tamaños.

**Métricas.** En `evals/stress/metrics.py` (no en `evals/metrics.py`): consumen observaciones y snapshots de sesión, no un `EstimationResult` contra un caso; así `METRIC_NAMES` del dataset de referencia no cambia ni hay importaciones circulares. Se reexportan desde `evals.stress`. Presupuestos por defecto por turno: latencia 30 000 ms (varias llamadas secuenciales al LLM, sin streaming) y coste 0,01 USD; son parámetros del constructor y del CLI. `MemoryDriftMetric` busca el hecho (match exacto, sin mayúsculas, sin LLM) en resumen, anclas y metadatos; la ventana reciente no cuenta porque no es memoria comprimida.

**Runner.** Reutiliza `evals.runner.open_client` y el patrón de reporte; una sesión por escenario × tamaño × repetición; `--workers` ejecuta sesiones en paralelo (cada sesión es secuencial). Una fila por turno, también si falla (`error` poblado).

## Risks / Trade-offs

- Match exacto: una paráfrasis del LLM cuenta como olvido (falso negativo). Se mitiga con hechos distintivos y alternativas, y se documenta.
- Sin Redis las tasas de acierto de caché son 0 por construcción; no se inventan.
- `latency_ms` y `tokens_in` agregan todas las llamadas del turno (estimación + metadatos + compresión), no solo la estimación.
- Con `--workers` > 1 la latencia incluye contención de la API del proveedor; el reporte indica los workers usados.
