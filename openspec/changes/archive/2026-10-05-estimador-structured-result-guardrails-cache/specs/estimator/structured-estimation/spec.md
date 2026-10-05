# Spec Delta

## MODIFIED Requirements

### Requirement: Contrato de estimación estructurada
`POST /api/v1/estimate` SHALL aceptar un cuerpo con `description` (20–2000 caracteres), `project_type` (`mobile_app`, `web_saas`, `internal_tool`, `data_pipeline`), `detail_level` (`summary`, `medium`, `detailed`), `output_format` (`phases_table`, `line_items`, `narrative`) y `reference_projects` opcional. SHALL responder `{result, prompt_version, cached}`, donde `result` es un `EstimationResult`. Las entradas inválidas SHALL rechazarse con 422 y las rechazadas por guardrails con 400, ambas antes de llamar al proveedor.

#### Scenario: Solicitud válida
- **WHEN** se envía una solicitud válida sin query params
- **THEN** la respuesta es 200 con `result` con la estructura de `EstimationResult`, `prompt_version="v3"` y `cached=false`.

#### Scenario: Entrada inválida
- **WHEN** la descripción tiene menos de 20 caracteres o un enum no es válido
- **THEN** la respuesta es 422 y no se invoca al proveedor.

#### Scenario: Rechazo por guardrails
- **WHEN** la descripción contiene un correo electrónico
- **THEN** la respuesta es 400 con `reason` y `message` y no se invoca al proveedor.

### Requirement: Selección de versión de prompt
El endpoint SHALL aceptar el query param opcional `prompt_version`, que por defecto es `v3`, y SHALL usar esa versión para renderizar. Una versión desconocida SHALL rechazarse con 422 sin invocar al proveedor. Con `v1` o `v2` el prompt de sistema SHALL incluir además el contrato JSON del resultado.

#### Scenario: Versión alternativa
- **WHEN** se llama con `?prompt_version=v2`
- **THEN** se usan las plantillas `v2` más el contrato JSON y la respuesta informa `prompt_version="v2"`.

#### Scenario: Versión inexistente
- **WHEN** se llama con `?prompt_version=v9`
- **THEN** la respuesta es 422 sin invocar al proveedor.

### Requirement: Streaming de la estimación estructurada
`POST /api/v1/estimate/stream` SHALL aceptar el mismo cuerpo y `prompt_version` que `/api/v1/estimate`, rechazar con 422 las entradas inválidas y con 400 las rechazadas por guardrails antes de abrir el stream. Como un resultado estructurado solo es válido completo, SHALL emitir el evento SSE `result` con el `EstimationResult` validado, luego `metadata` con versión de prompt, modelo, proveedor, finalización, tokens, latencia, caché y costes, y `done` solo tras el éxito. Un fallo SHALL emitir `error` saneado sin `done`.

#### Scenario: Stream correcto
- **WHEN** se transmite una estimación estructurada válida
- **THEN** el cliente recibe `result`, después `metadata` con `prompt_version`, `cached` y consumo, y por último `done`.

#### Scenario: Acierto de caché
- **WHEN** la respuesta procede de una caché
- **THEN** `metadata` indica `cache_hit=true` con tokens y coste de solicitud en cero.

#### Scenario: Rechazo de guardrails
- **WHEN** la entrada es rechazada
- **THEN** la respuesta es 400 con `reason` y `message`, sin abrir un stream.

#### Scenario: Fallo del proveedor en el stream
- **WHEN** el proveedor falla durante la generación
- **THEN** se emite `error` sin detalles internos y sin `done`.

#### Scenario: Fallo de validación
- **WHEN** se agotan los intentos de validación
- **THEN** se emite `error` sin detalles internos y sin `done`.

### Requirement: Cliente de formulario tipado
El cliente Streamlit SHALL presentar un formulario con descripción, tipo de proyecto, nivel de detalle, formato de salida y versión de prompt. Al enviarlo SHALL construir y validar la misma solicitud tipada que usa el servicio, consumir `/api/v1/estimate/stream` y mostrar el resultado estructurado (resumen, confianza, fases, duración y coste) dentro de un historial que se puede borrar. Si el resultado es `out_of_scope` SHALL mostrar «No estimable» con el resumen. Los rechazos 400 de guardrails SHALL mostrarse con su `message`. La barra lateral SHALL mostrar el prompt de sistema, los ejemplos few-shot y las métricas de la última llamada. Los errores SHALL mostrarse sin exponer detalles internos y sin guardarse como estimaciones. El cliente SHALL funcionar sin claves de proveedores.

#### Scenario: Envío válido
- **WHEN** el usuario completa el formulario y lo envía
- **THEN** el cliente hace POST a `/api/v1/estimate/stream`, muestra el resultado estructurado y actualiza las métricas.

#### Scenario: No estimable
- **WHEN** el servidor devuelve un resultado `out_of_scope`
- **THEN** el cliente muestra «No estimable» y no presenta importes.

#### Scenario: Contexto del prompt
- **WHEN** se abre la aplicación o se envía una solicitud
- **THEN** la barra lateral muestra el prompt de sistema renderizado y los títulos de sus ejemplos few-shot.

#### Scenario: Descripción demasiado corta
- **WHEN** la descripción tiene menos de 20 caracteres
- **THEN** se muestra un error de validación y no se hace ninguna solicitud HTTP.

#### Scenario: Rechazo de guardrails
- **WHEN** la API responde 400 con `message`
- **THEN** el cliente muestra ese mensaje como error y no lo guarda como estimación.
