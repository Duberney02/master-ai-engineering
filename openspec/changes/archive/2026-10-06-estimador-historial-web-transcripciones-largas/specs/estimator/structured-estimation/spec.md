# Spec Delta

## Purpose

Ofrecer un contrato tipado y compartido entre clientes y servicio IA para pedir estimaciones a partir de la descripción del proyecto, incluidas transcripciones largas.

## MODIFIED Requirements

### Requirement: Contrato de estimación estructurada
`POST /api/v1/estimate` SHALL aceptar un cuerpo con `description` (20–80000 caracteres), `project_type` (`mobile_app`, `web_saas`, `internal_tool`, `data_pipeline`), `detail_level` (`summary`, `medium`, `detailed`), `output_format` (`phases_table`, `line_items`, `narrative`) y `reference_projects` opcional. SHALL responder `{result, prompt_version, cached, cache_source, estimation_id, metrics}`, donde `result` es un `EstimationResult`, `cache_source` es `none`, `exact` o `semantic`, `estimation_id` es el id del registro de historial o `null` si no se guardó y `metrics` son las métricas de la llamada (modelo, proveedor, finalización, tokens de entrada, salida y total, latencia, acierto de caché y costes). Las entradas inválidas SHALL rechazarse con 422 y las rechazadas por guardrails con 400, ambas antes de llamar al proveedor. Los metadatos del stream SHALL incluir también `cache_source` y `estimation_id`.

#### Scenario: Solicitud válida
- **WHEN** se envía una solicitud válida sin query params
- **THEN** la respuesta es 200 con `result` con la estructura de `EstimationResult`, `prompt_version="v3"`, `cached=false`, `cache_source="none"` y `metrics` con el uso de tokens.

#### Scenario: Transcripción larga
- **WHEN** la descripción tiene 80000 caracteres
- **THEN** la solicitud se acepta y se procesa como cualquier otra.

#### Scenario: Entrada inválida
- **WHEN** la descripción tiene menos de 20 o más de 80000 caracteres, o un enum no es válido
- **THEN** la respuesta es 422 y no se invoca al proveedor.

#### Scenario: Rechazo por guardrails
- **WHEN** la descripción contiene un correo electrónico
- **THEN** la respuesta es 400 con `reason` y `message` y no se invoca al proveedor.

### Requirement: Cliente de formulario tipado
El cliente Streamlit SHALL presentar un formulario con descripción (hasta 80000 caracteres), carga opcional de un archivo `.txt` que sustituye a la descripción, tipo de proyecto, nivel de detalle, formato de salida y versión de prompt. Al enviarlo SHALL construir y validar la misma solicitud tipada que usa el servicio, consumir `/api/v1/estimate/stream` y mostrar el resultado estructurado (resumen, confianza, fases, duración y coste) junto con el tiempo transcurrido, dentro de un historial que se puede borrar. Si el resultado es `out_of_scope` SHALL mostrar «No estimable» con el resumen. Los rechazos 400 de guardrails SHALL mostrarse con su `message`. La barra lateral SHALL mostrar el prompt de sistema, los ejemplos few-shot y las métricas de la última llamada. Los errores SHALL mostrarse sin exponer detalles internos y sin guardarse como estimaciones. El cliente SHALL funcionar sin claves de proveedores.

#### Scenario: Envío válido
- **WHEN** el usuario completa el formulario y lo envía
- **THEN** el cliente hace POST a `/api/v1/estimate/stream`, muestra el resultado estructurado y el tiempo transcurrido, y actualiza las métricas.

#### Scenario: Archivo de texto
- **WHEN** el usuario adjunta un `.txt` UTF-8
- **THEN** su contenido se usa como descripción.

#### Scenario: No estimable
- **WHEN** el servidor devuelve un resultado `out_of_scope`
- **THEN** el cliente muestra «No estimable» y no presenta importes.

#### Scenario: Contexto del prompt
- **WHEN** se abre la aplicación o se envía una solicitud
- **THEN** la barra lateral muestra el prompt de sistema renderizado y los títulos de sus ejemplos few-shot.

#### Scenario: Descripción demasiado corta
- **WHEN** la descripción tiene menos de 20 caracteres
- **THEN** se muestra «La descripción debe tener entre 20 y 80000 caracteres.» y no se hace ninguna solicitud HTTP.

#### Scenario: Descripción demasiado larga
- **WHEN** la descripción pegada supera 80000 caracteres
- **THEN** se muestra el mismo mensaje y no se hace ninguna solicitud HTTP.

#### Scenario: Rechazo de guardrails
- **WHEN** la API responde 400 con `message`
- **THEN** el cliente muestra ese mensaje como error y no lo guarda como estimación.
