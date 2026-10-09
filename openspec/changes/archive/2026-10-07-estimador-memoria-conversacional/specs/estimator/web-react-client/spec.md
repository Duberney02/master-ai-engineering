# Spec Delta

## MODIFIED Requirements

### Requirement: Formulario de estimación con carga de `.txt`
La aplicación SHALL presentar un formulario con descripción (20–80 000 caracteres) y contador de caracteres, tipo de proyecto, nivel de detalle, formato de salida y versión de prompt (`v3` por defecto), la opción de adjuntar un `.txt` cuyo contenido sustituye a la descripción y la selección de varios adjuntos PDF o Word. SHALL crear una sesión con `POST /api/v1/sessions` al cargar la página, conservar su `session_id` mientras la página siga abierta, y enviar cada estimación como multipart a `POST /api/v1/sessions/{session_id}/estimate`. SHALL mostrar los `project_metadata` en la barra lateral y un botón «Nueva conversación» que cree otra sesión y reinicie el estado. Si la API responde 404 por sesión desconocida, SHALL iniciar una conversación nueva e informar al usuario. SHALL rechazar sin llamar a la API: descripciones fuera de rango (tras recortar espacios), archivos de transcripción que no sean `.txt`, que no sean UTF-8 válido o de más de 400 000 bytes, y adjuntos que no sean PDF o Word, con los mismos mensajes en español que la web Rails. Al enviar, SHALL deshabilitar el botón y mostrar un indicador de carga con un temporizador de segundos transcurridos, y SHALL restaurarlos al terminar con éxito o con error.

#### Scenario: Descripción válida
- **WHEN** el usuario envía una descripción válida
- **THEN** la aplicación llama a `POST /api/v1/sessions/{session_id}/estimate` como multipart con `transcript`, `project_type`, `detail_level`, `output_format` y `prompt_version`.

#### Scenario: Sesión al cargar
- **WHEN** se carga la página
- **THEN** la aplicación crea una sesión y reutiliza su identificador en todos los envíos hasta crear una nueva conversación.

#### Scenario: Carga de un archivo
- **WHEN** el usuario adjunta un `.txt` UTF-8 válido de hasta 400 000 bytes
- **THEN** su contenido sustituye a la descripción y el contador se actualiza.

#### Scenario: Adjuntos múltiples
- **WHEN** el usuario selecciona varios PDF o Word
- **THEN** el envío incluye todos como `attachments`.

#### Scenario: Metadatos y nueva conversación
- **WHEN** la estimación devuelve `project_metadata` y el usuario pulsa «Nueva conversación»
- **THEN** la barra los muestra y después se crea otra sesión con los metadatos vacíos y el formulario reiniciado.

#### Scenario: Archivo inválido
- **WHEN** el archivo no es `.txt`, no es UTF-8 válido o supera 400 000 bytes
- **THEN** se muestra «El archivo debe ser de texto plano (.txt).», «El archivo debe estar codificado en UTF-8.» o «El archivo supera el máximo de 400 KB.» y no se llama a la API.

#### Scenario: Descripción fuera de rango
- **WHEN** la descripción tiene menos de 20 o más de 80 000 caracteres
- **THEN** se muestra «La descripción debe tener entre 20 y 80000 caracteres.» y no se llama a la API.

#### Scenario: Indicador y temporizador
- **WHEN** se envía el formulario y la API aún no ha respondido
- **THEN** el botón queda deshabilitado y aparecen el indicador de carga y un temporizador que avanza por segundos.

#### Scenario: Conservación de datos tras un error
- **WHEN** la API responde con un error
- **THEN** el formulario conserva lo que el usuario había escrito y elegido, muestra el mensaje saneado y rehabilita el botón.
