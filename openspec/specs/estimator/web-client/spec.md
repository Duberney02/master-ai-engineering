# estimator/web-client Specification

## Purpose
Ofrecer una aplicación web Rails (`estimator-web`) que consuma la API del estimador por HTTP para enviar transcripciones, consultar el historial y visualizar resultados.

## Requirements

### Requirement: Formulario de estimación con carga de `.txt`
`estimator-web` SHALL presentar un formulario con descripción (20–80 000 caracteres), tipo de proyecto, nivel de detalle, formato de salida y versión de prompt, la opción de adjuntar un archivo `.txt` cuyo contenido sustituye a la descripción y la selección de varios adjuntos PDF o Word. SHALL crear una sesión con `POST /api/v1/sessions` al abrir el formulario, conservar su `session_id` en la sesión del navegador, y enviar cada estimación a `POST /api/v1/sessions/{session_id}/estimate`. SHALL mostrar en la barra lateral los `project_metadata` de la conversación y un botón «Nueva conversación» que cree otra sesión y reinicie el estado. Si la API responde 404 por sesión desconocida, SHALL iniciar una conversación nueva e informar al usuario. SHALL rechazar sin llamar a la API: descripciones fuera de rango, archivos de transcripción que no sean `.txt`, que no sean UTF-8 válido o de más de 400 KB, y adjuntos que no sean PDF o Word, con mensajes en español. Al enviar, SHALL mostrar un indicador de carga y un temporizador que cuenta los segundos transcurridos.

#### Scenario: Descripción válida
- **WHEN** el usuario envía una descripción válida
- **THEN** la aplicación llama a `POST /api/v1/sessions/{session_id}/estimate` como multipart con la solicitud tipada.

#### Scenario: Sesión al abrir
- **WHEN** el usuario abre el formulario por primera vez
- **THEN** la aplicación crea una sesión y la reutiliza en los envíos siguientes.

#### Scenario: Carga de un archivo
- **WHEN** el usuario adjunta un `.txt` válido
- **THEN** el contenido del archivo se usa como descripción.

#### Scenario: Adjuntos múltiples
- **WHEN** el usuario selecciona varios PDF o Word
- **THEN** el envío incluye todos como `attachments`.

#### Scenario: Metadatos y nueva conversación
- **WHEN** la estimación devuelve `project_metadata` y el usuario pulsa «Nueva conversación»
- **THEN** la barra muestra los metadatos y después se crea otra sesión con la barra de metadatos vacía.

#### Scenario: Archivo inválido
- **WHEN** el archivo no es `.txt`, no es UTF-8 o supera 400 KB
- **THEN** se muestra un error y no se llama a la API.

#### Scenario: Descripción fuera de rango
- **WHEN** la descripción tiene menos de 20 o más de 80 000 caracteres
- **THEN** se muestra «La descripción debe tener entre 20 y 80000 caracteres.» y no se llama a la API.

#### Scenario: Indicador y temporizador
- **WHEN** se envía el formulario
- **THEN** el botón se deshabilita, aparece un indicador de carga y un temporizador de segundos transcurridos.

### Requirement: Visualización del resultado
La vista de una estimación SHALL mostrar el resumen, la confianza, la duración total en semanas, el coste total en EUR, la tabla de fases (nombre, descripción, semanas y coste), la versión del prompt y la procedencia (generada, caché exacta o caché semántica). Si el resultado es `out_of_scope` SHALL mostrar «No estimable» con el resumen y SHALL NOT mostrar cifras de duración ni coste.

#### Scenario: Resultado estimable
- **WHEN** se muestra una estimación con confianza ≥ 30
- **THEN** la vista contiene confianza, duración, coste y una fila por cada fase.

#### Scenario: Baja confianza
- **WHEN** el resultado tiene `out_of_scope=true`
- **THEN** se muestra «No estimable» y ninguna cifra de coste o duración.

### Requirement: Barra lateral de contexto del prompt
La web SHALL mostrar a la izquierda, como el cliente Streamlit, el prompt de sistema renderizado (solo lectura), los ejemplos few-shot y las métricas de la última llamada (modelo, versión del prompt, tokens de entrada y salida, latencia, coste de solicitud y si la respuesta fue de caché o generada). SHALL obtener el prompt y los ejemplos de `GET /api/v1/prompts/estimation` y las métricas del campo `metrics` de la estimación; sin métricas SHALL mostrar «Aún no se ha generado ninguna estimación.». Si la API no puede renderizar el prompt, la página SHALL seguir funcionando con un aviso. La barra SHALL poder ocultarse.

#### Scenario: Formulario
- **WHEN** el usuario abre el formulario
- **THEN** la barra muestra el prompt de sistema y los ejemplos few-shot de las opciones por defecto, y el estado vacío de métricas.

#### Scenario: Resultado con métricas
- **WHEN** se muestra una estimación con `metrics`
- **THEN** la barra muestra modelo, tokens, latencia y coste, y el prompt de las opciones de esa estimación.

#### Scenario: Prompt no disponible
- **WHEN** la API falla al renderizar el prompt
- **THEN** la barra muestra un aviso y el resto de la página funciona.

### Requirement: Historial de estimaciones
`estimator-web` SHALL listar las últimas estimaciones obtenidas de `GET /api/v1/estimations` (fecha, tipo, confianza, coste, procedencia y extracto) con enlace a la vista de cada una, que se carga con `GET /api/v1/estimations/{id}`. Tras una estimación con `estimation_id` SHALL redirigir a su vista; sin `estimation_id` SHALL mostrar el resultado directamente.

#### Scenario: Listado
- **WHEN** el usuario abre el historial
- **THEN** ve las estimaciones devueltas por la API, la más reciente primero.

#### Scenario: Historial vacío o desactivado
- **WHEN** la API devuelve una lista vacía o 503
- **THEN** se muestra un mensaje explicativo y no un error técnico.

### Requirement: Manejo de errores del cliente HTTP
El cliente Faraday SHALL usar la URL `ESTIMATOR_API_URL`, tiempos de espera acotados y SHALL traducir los fallos a mensajes saneados en español: fallo de conexión o de tiempo, 400 con el `message` del guardrail, 422, 404 y 5xx. SHALL NOT mostrar cuerpos de respuesta crudos, trazas ni la URL interna. Un cuerpo no JSON o fuera de contrato SHALL tratarse como respuesta inválida.

#### Scenario: API caída
- **WHEN** la API no acepta la conexión o excede el tiempo
- **THEN** se muestra «No se pudo conectar con la API del estimador.» sin detalles internos.

#### Scenario: Rechazo de guardrails
- **WHEN** la API responde 400 con `{reason, message}`
- **THEN** se muestra ese `message` como error del formulario.

#### Scenario: Error del servidor
- **WHEN** la API responde 5xx
- **THEN** se muestra un mensaje genérico y no el cuerpo de la respuesta.

#### Scenario: Respuesta inválida
- **WHEN** la API responde 200 con un cuerpo que no es JSON o sin `result`
- **THEN** se muestra un mensaje de respuesta inválida.
