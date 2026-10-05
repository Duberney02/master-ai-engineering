# Spec Delta

## Purpose

Ofrecer un contrato tipado y compartido entre clientes y servicio IA para pedir estimaciones a partir de una descripción breve del proyecto.

## ADDED Requirements

### Requirement: Contrato de estimación estructurada
`POST /api/v1/estimate` SHALL aceptar un cuerpo con `description` (20–2000 caracteres), `project_type` (`mobile_app`, `web_saas`, `internal_tool`, `data_pipeline`), `detail_level` (`summary`, `medium`, `detailed`), `output_format` (`phases_table`, `line_items`, `narrative`) y `reference_projects` opcional. SHALL responder `{text, prompt_version}`. Las entradas inválidas SHALL rechazarse con 422 antes de llamar al proveedor.

#### Scenario: Solicitud válida
- **WHEN** se envía una solicitud válida sin query params
- **THEN** la respuesta es 200 con el texto generado y `prompt_version="v1"`.

#### Scenario: Entrada inválida
- **WHEN** la descripción tiene menos de 20 caracteres o un enum no es válido
- **THEN** la respuesta es 422 y no se invoca al proveedor.

### Requirement: Selección de versión de prompt
El endpoint SHALL aceptar el query param opcional `prompt_version`, que por defecto es `v1`, y SHALL usar esa versión para renderizar. Una versión desconocida SHALL rechazarse con 422 sin invocar al proveedor.

#### Scenario: Versión alternativa
- **WHEN** se llama con `?prompt_version=v2`
- **THEN** se usan las plantillas `v2` y la respuesta informa `prompt_version="v2"`.

#### Scenario: Versión inexistente
- **WHEN** se llama con `?prompt_version=v9`
- **THEN** la respuesta es 422 sin invocar al proveedor.

### Requirement: Mensajes separados y política de proveedor
El sistema SHALL enviar al modelo el prompt de sistema y el de usuario como mensajes separados, sin concatenarlos. SHALL aplicar la misma política de proveedor que el resto del estimador (caché, reintentos, fallback, costes y errores saneados).

#### Scenario: Llamada al proveedor
- **WHEN** se genera una estimación con OpenAI
- **THEN** la llamada contiene un mensaje `system` y un mensaje `user` distintos, y el de usuario contiene la descripción.

#### Scenario: Fallo del proveedor
- **WHEN** el proveedor falla
- **THEN** la respuesta es un error saneado con el mismo código que en el resto del estimador.

### Requirement: Streaming de la estimación estructurada
`POST /api/v1/estimate/stream` SHALL aceptar el mismo cuerpo y el mismo `prompt_version` que `/api/v1/estimate`, y rechazar con 422 las entradas o versiones inválidas antes de abrir el stream. SHALL emitir eventos SSE `token` con el texto a medida que llega, luego `metadata` con versión de prompt, modelo, proveedor, finalización, tokens, latencia, caché y costes, y `done` solo tras el éxito. Un fallo SHALL emitir `error` saneado sin `done`. SHALL aplicar la misma política de proveedor y los mismos mensajes system/user separados que la respuesta completa.

#### Scenario: Stream correcto
- **WHEN** se transmite una estimación estructurada válida
- **THEN** el cliente recibe uno o más `token`, después `metadata` con `prompt_version` y consumo, y por último `done`.

#### Scenario: Fallo del proveedor en el stream
- **WHEN** el proveedor falla durante la generación
- **THEN** se emite `error` sin detalles internos y sin `done`.

### Requirement: Cliente de formulario tipado
El cliente Streamlit SHALL presentar un formulario con descripción, tipo de proyecto, nivel de detalle, formato de salida y versión de prompt. Al enviarlo SHALL construir y validar la misma solicitud tipada que usa el servicio, consumir `/api/v1/estimate/stream` y mostrar el texto progresivamente dentro de un historial que se puede borrar. La barra lateral SHALL mostrar el prompt de sistema de las plantillas para la última solicitud, los ejemplos few-shot que contiene y las métricas de la última llamada (modelo, tokens, latencia, coste, caché y versión de prompt). Los errores de validación o de red SHALL mostrarse sin exponer detalles internos y sin guardarse como estimaciones. El cliente SHALL funcionar sin claves de proveedores.

#### Scenario: Envío válido
- **WHEN** el usuario completa el formulario y lo envía
- **THEN** el cliente hace POST a `/api/v1/estimate/stream` con el JSON de la solicitud, muestra el texto progresivamente y actualiza las métricas de la barra lateral.

#### Scenario: Contexto del prompt
- **WHEN** se abre la aplicación o se envía una solicitud
- **THEN** la barra lateral muestra el prompt de sistema renderizado y los títulos de sus ejemplos few-shot.

#### Scenario: Descripción demasiado corta
- **WHEN** la descripción tiene menos de 20 caracteres
- **THEN** se muestra un error de validación y no se hace ninguna solicitud HTTP.
