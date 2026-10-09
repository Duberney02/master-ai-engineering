# Spec Delta

## MODIFIED Requirements

### Requirement: Cliente de formulario tipado
El cliente Streamlit SHALL crear una sesión con `POST /api/v1/sessions` al cargar la página y conservar su `session_id` durante la sesión del navegador. SHALL presentar un formulario con transcripción (hasta 80000 caracteres), carga opcional de un archivo `.txt` que sustituye a la transcripción, selección de varios archivos PDF o Word como adjuntos, tipo de proyecto, nivel de detalle, formato de salida y versión de prompt. Al enviarlo SHALL construir y validar la misma solicitud tipada que usa el servicio, enviarla como `multipart/form-data` a `/api/v1/sessions/{session_id}/estimate` y mostrar el resultado estructurado (resumen, confianza, fases, duración y coste) junto con el tiempo transcurrido, dentro del historial de la conversación, que se reinicia con «Nueva conversación». Si el resultado es `out_of_scope` SHALL mostrar «No estimable» con el resumen. Los rechazos 400 de guardrails SHALL mostrarse con su `message`. La barra lateral SHALL mostrar los `project_metadata` de la sesión (nombre, equipo, tecnologías y alcance), el prompt de sistema, los ejemplos few-shot y las métricas de la última llamada. Un botón «Nueva conversación» SHALL crear otra sesión y reiniciar el historial, los metadatos y las métricas. Si la API responde 404 por una sesión desconocida o caducada, el cliente SHALL iniciar una conversación nueva e informar al usuario. Los errores SHALL mostrarse sin exponer detalles internos y sin guardarse como estimaciones. El cliente SHALL funcionar sin claves de proveedores.

#### Scenario: Envío válido
- **WHEN** el usuario completa el formulario y lo envía
- **THEN** el cliente hace POST multipart a `/api/v1/sessions/{session_id}/estimate` con el `session_id` creado al cargar, muestra el resultado estructurado y el tiempo transcurrido, y actualiza las métricas y los metadatos.

#### Scenario: Sesión al cargar
- **WHEN** se abre la aplicación
- **THEN** el cliente crea una sesión y la reutiliza en los envíos siguientes.

#### Scenario: Archivo de texto
- **WHEN** el usuario adjunta un `.txt` UTF-8
- **THEN** su contenido se usa como transcripción.

#### Scenario: Adjuntos múltiples
- **WHEN** el usuario selecciona varios PDF o Word
- **THEN** el envío incluye todos los archivos como `attachments`.

#### Scenario: Panel de metadatos
- **WHEN** la API devuelve `project_metadata`
- **THEN** la barra lateral los muestra y los conserva entre envíos de la misma conversación.

#### Scenario: Nueva conversación
- **WHEN** el usuario pulsa «Nueva conversación»
- **THEN** se crea otra sesión y el historial, los metadatos y las métricas quedan vacíos.

#### Scenario: No estimable
- **WHEN** el servidor devuelve un resultado `out_of_scope`
- **THEN** el cliente muestra «No estimable» y no presenta importes.

#### Scenario: Contexto del prompt
- **WHEN** se abre la aplicación o se envía una solicitud
- **THEN** la barra lateral muestra el prompt de sistema renderizado y los títulos de sus ejemplos few-shot.

#### Scenario: Descripción demasiado corta
- **WHEN** la transcripción y los adjuntos no suman 20 caracteres
- **THEN** se muestra «La descripción debe tener entre 20 y 80000 caracteres.» y no se envía la estimación.

#### Scenario: Descripción demasiado larga
- **WHEN** la transcripción pegada supera 80000 caracteres
- **THEN** se muestra el mismo mensaje y no se envía la estimación.

#### Scenario: Rechazo de guardrails
- **WHEN** la API responde 400 con `message`
- **THEN** el cliente muestra ese mensaje como error y no lo guarda como estimación.

#### Scenario: Sesión caducada
- **WHEN** la API responde 404 a una estimación
- **THEN** el cliente crea una conversación nueva e informa al usuario de que la anterior expiró.
