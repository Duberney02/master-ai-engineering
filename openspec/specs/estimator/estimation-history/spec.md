# estimator/estimation-history Specification

## Purpose
Conservar cada estimación completada en PostgreSQL y permitir consultar las últimas y una concreta, sin que la disponibilidad de la base de datos condicione la estimación.

## Requirements

### Requirement: Persistencia de estimaciones
Tras completar `POST /api/v1/estimate` o `POST /api/v1/estimate/stream` con éxito, el sistema SHALL guardar en PostgreSQL la descripción completa, las opciones (`project_type`, `detail_level`, `output_format` y `reference_projects`), el resultado JSON, `prompt_version`, la procedencia de caché (`none`, `exact` o `semantic`), el modelo, el proveedor y las fechas de solicitud y de finalización. Las estimaciones servidas desde caché SHALL guardarse también. Las solicitudes rechazadas o fallidas SHALL NOT guardarse.

#### Scenario: Estimación generada
- **WHEN** se completa una estimación nueva
- **THEN** se inserta un registro con `cache_source="none"` y la respuesta incluye su `estimation_id`.

#### Scenario: Estimación desde caché
- **WHEN** el resultado procede de la caché exacta o de la semántica
- **THEN** el registro guarda `cache_source="exact"` o `"semantic"` respectivamente.

#### Scenario: Solicitud rechazada
- **WHEN** la entrada es rechazada por validación (422) o por guardrails (400), o la generación falla
- **THEN** no se crea ningún registro.

### Requirement: Métricas de la llamada
El historial SHALL guardar las métricas de la llamada de cada estimación (las mismas que devuelve `POST /api/v1/estimate` en `metrics`) y devolverlas en `GET /api/v1/estimations/{id}`. Un registro sin métricas SHALL devolver `metrics=null`.

#### Scenario: Métricas guardadas
- **WHEN** se completa una estimación y se consulta su registro
- **THEN** `metrics` coincide con las devueltas en la respuesta.

#### Scenario: Registro sin métricas
- **WHEN** un registro no tiene métricas guardadas
- **THEN** la consulta responde 200 con `metrics=null`.

### Requirement: Tolerancia a fallos del historial
El historial SHALL ser opcional: sin `DATABASE_URL` queda desactivado y las estimaciones funcionan igual con `estimation_id=null`. Un fallo al guardar SHALL registrarse sin datos del usuario y SHALL NOT alterar la respuesta de la estimación, que devuelve `estimation_id=null`.

#### Scenario: Historial desactivado
- **WHEN** `DATABASE_URL` no está configurada
- **THEN** la estimación responde 200 con `estimation_id=null`.

#### Scenario: Base de datos caída al guardar
- **WHEN** PostgreSQL no responde al guardar
- **THEN** la estimación responde 200 con `estimation_id=null` y se registra una advertencia saneada.

### Requirement: Listado de las últimas estimaciones
`GET /api/v1/estimations` SHALL devolver las últimas estimaciones ordenadas por fecha de solicitud descendente. Acepta `limit` (1–50, por defecto 10). Cada elemento SHALL contener `id`, `requested_at`, `project_type`, `detail_level`, `output_format`, `prompt_version`, `cache_source`, `confidence_pct`, `total_cost_eur`, `total_duration_weeks`, `out_of_scope` y un extracto de la descripción de como máximo 200 caracteres, y SHALL NOT incluir la descripción completa. Un `limit` fuera de rango SHALL rechazarse con 422.

#### Scenario: Orden y límite
- **WHEN** existen 12 estimaciones y se pide sin parámetros
- **THEN** se devuelven las 10 más recientes, la más reciente primero.

#### Scenario: Límite inválido
- **WHEN** se pide `limit=0` o `limit=51`
- **THEN** la respuesta es 422.

### Requirement: Consulta individual
`GET /api/v1/estimations/{id}` SHALL devolver el registro completo (descripción, opciones, resultado, `prompt_version`, `cached`, `cache_source`, modelo, proveedor, `metrics` y fechas de solicitud y de finalización). Un id inexistente SHALL responder 404.

#### Scenario: Registro existente
- **WHEN** se consulta el id devuelto por una estimación
- **THEN** la respuesta es 200 con la descripción completa y el resultado idéntico al devuelto en su día.

#### Scenario: Registro inexistente
- **WHEN** se consulta un id que no existe
- **THEN** la respuesta es 404.

### Requirement: Lectura sin historial disponible
Si el historial está desactivado o la base de datos no responde, los endpoints de lectura SHALL responder 503 con un mensaje saneado que no revele detalles de conexión.

#### Scenario: Historial desactivado
- **WHEN** no hay `DATABASE_URL` y se pide `GET /api/v1/estimations`
- **THEN** la respuesta es 503 con `detail="History is not configured"`.
