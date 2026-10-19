# Spec Delta

## Purpose

Ejecutar la ingesta de una fuente incluida del catálogo en segundo plano y exponer su seguimiento, sin indexar los documentos ni conectar limpieza o seudonimización.

## ADDED Requirements

### Requirement: Orquestador de ingesta
`ingest_source` SHALL validar la fuente contra el catálogo (lanzando `IngestionRejected` si no existe o su decisión no es `include`), marcar el trabajo en ejecución, seleccionar el parser del registro según el formato, cargar los archivos con el cargador, generar los documentos y marcar el trabajo como completado con su cantidad o como fallido con el mensaje de error. El orquestador SHALL registrar la cantidad de documentos pero no los almacena en un índice, no genera embeddings ni ejecuta limpieza o seudonimización. Los logs SHALL ser estructurados y asociados al trabajo y a la fuente. (Referencia: `app/ingestion/orchestrator.py`.)

#### Scenario: Ingesta correcta
- **WHEN** se ingiere `presupuestos_json`
- **THEN** el trabajo termina `completed` con 6 documentos.

#### Scenario: Fallo de carga
- **WHEN** la ubicación de la fuente no existe
- **THEN** el trabajo queda `failed` con el error registrado y la excepción se propaga.

#### Scenario: Fuente no admitida
- **WHEN** la fuente tiene decisión `review` o `exclude`
- **THEN** se lanza `IngestionRejected` y el trabajo no pasa a `running`.

### Requirement: Iniciar una ingesta
`POST /api/v1/ingestion/runs` con `{"source_name": "..."}` SHALL validar la fuente, registrar el trabajo, ejecutarlo mediante `BackgroundTasks` y responder HTTP 202 con `job_id`, `source_name` y `status`. SHALL responder 404 `{"reason": "unknown_source"}` para una fuente desconocida y 400 `{"reason": "source_not_included", "decision", "decision_reason"}` para fuentes `review` o `exclude`. La tarea en segundo plano SHALL usar su propia sesión de base de datos. (Referencia: `app/routers/ingestion.py`, `app/schemas/ingestion.py`.)

#### Scenario: Aceptada
- **WHEN** se solicita una fuente incluida
- **THEN** la respuesta es 202 con estado `pending` e identificador del trabajo.

#### Scenario: Fuente desconocida
- **WHEN** se solicita una fuente que no está en el catálogo
- **THEN** la respuesta es 404.

#### Scenario: Fuente en revisión o excluida
- **WHEN** se solicita `transcripciones_txt` o `rate_card_xlsx`
- **THEN** la respuesta es 400 con la decisión y su justificación.

### Requirement: Consultar un trabajo
`GET /api/v1/ingestion/jobs/{job_id}` SHALL devolver estado (`pending`, `running`, `completed` o `failed`), cantidad de documentos, error y fechas de inicio y fin, y responder 404 para un trabajo desconocido. La API de ingesta SHALL exponer únicamente estos dos endpoints y no usar colas externas.

#### Scenario: Trabajo completado
- **WHEN** el trabajo ha terminado
- **THEN** la respuesta indica `completed`, `documents_count` y `finished_at`.

#### Scenario: Trabajo desconocido
- **WHEN** el identificador no existe
- **THEN** la respuesta es 404.

#### Scenario: Endpoints existentes
- **WHEN** se consultan `/health` y los endpoints de estimación y sesiones
- **THEN** su comportamiento no cambia.
