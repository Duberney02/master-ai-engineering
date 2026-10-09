# Spec Delta

## MODIFIED Requirements

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
