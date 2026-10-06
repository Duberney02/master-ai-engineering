# estimator/web-react-client Specification

## Purpose
Ofrecer una aplicación web React (`estimator-web-react`) con paridad funcional con la web Rails: enviar transcripciones, ver resultados, consultar el historial y el contexto del prompt, consumiendo solo la API del estimador por HTTP.

## Requirements

### Requirement: Rutas equivalentes a la web Rails
La aplicación SHALL ofrecer las rutas `/` (nueva estimación), `/estimations` (historial) y `/estimations/:id` (detalle), con la navegación «Nueva estimación» e «Historial» presente en todas las pantallas. Una ruta desconocida SHALL mostrar un mensaje de página no encontrada en español.

#### Scenario: Navegación
- **WHEN** el usuario abre cualquier pantalla
- **THEN** ve los enlaces «Nueva estimación» e «Historial» y ambos llevan a `/` y `/estimations`.

#### Scenario: Ruta desconocida
- **WHEN** el usuario abre una ruta que no existe
- **THEN** se muestra un mensaje de página no encontrada con enlaces de vuelta.

### Requirement: Formulario de estimación con carga de `.txt`
La aplicación SHALL presentar un formulario con descripción (20–80 000 caracteres) y contador de caracteres, tipo de proyecto, nivel de detalle, formato de salida y versión de prompt (`v3` por defecto), y la opción de adjuntar un `.txt` cuyo contenido sustituye a la descripción. SHALL rechazar sin llamar a la API: descripciones fuera de rango (tras recortar espacios), archivos que no sean `.txt`, archivos que no sean UTF-8 válido y archivos de más de 400 000 bytes, con los mismos mensajes en español que la web Rails. Al enviar, SHALL deshabilitar el botón y mostrar un indicador de carga con un temporizador de segundos transcurridos, y SHALL restaurarlos al terminar con éxito o con error.

#### Scenario: Descripción válida
- **WHEN** el usuario envía una descripción válida
- **THEN** la aplicación llama a `POST /api/v1/estimate?prompt_version=<versión>` con `description`, `project_type`, `detail_level` y `output_format`.

#### Scenario: Carga de un archivo
- **WHEN** el usuario adjunta un `.txt` UTF-8 válido de hasta 400 000 bytes
- **THEN** su contenido sustituye a la descripción y el contador se actualiza.

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

### Requirement: Visualización del resultado
La vista de una estimación SHALL mostrar el resumen, la confianza, la duración total en semanas, el coste total en EUR, la tabla de fases (nombre, descripción, semanas y coste), las opciones usadas, la versión del prompt, la procedencia (generada, caché exacta o caché semántica) y la fecha cuando exista. Los importes SHALL usar formato español (separador de miles `.` y decimal `,`). Si el resultado es `out_of_scope` SHALL mostrar «No estimable» con el motivo (sin el prefijo `Out of scope:`) y la confianza, y SHALL NOT mostrar cifras de duración ni coste. La descripción original SHALL mostrarse truncada a 2 000 caracteres con el total de caracteres cuando lo supere.

#### Scenario: Resultado estimable
- **WHEN** se muestra una estimación con confianza ≥ 30
- **THEN** la vista contiene confianza, duración, coste y una fila por cada fase.

#### Scenario: Baja confianza
- **WHEN** el resultado tiene `out_of_scope=true`
- **THEN** se muestra «No estimable» y ninguna cifra de coste o duración.

#### Scenario: Descripción larga
- **WHEN** la descripción tiene más de 2 000 caracteres
- **THEN** se muestran los primeros 2 000 y el total de caracteres con separador de miles.

### Requirement: Flujo tras estimar
Tras una estimación con `estimation_id`, la aplicación SHALL navegar a `/estimations/:id`. Sin `estimation_id` (historial desactivado o no disponible) SHALL mostrar el resultado directamente, con la descripción y opciones enviadas y sin enlace permanente.

#### Scenario: Con historial
- **WHEN** la API devuelve `estimation_id`
- **THEN** la URL pasa a `/estimations/<id>` y se muestra esa estimación.

#### Scenario: Sin historial
- **WHEN** la API devuelve el resultado sin `estimation_id`
- **THEN** se muestra el resultado en pantalla con las métricas de la llamada y sin enlace permanente.

### Requirement: Barra lateral de contexto del prompt
La aplicación SHALL mostrar a la izquierda el prompt de sistema renderizado (solo lectura), los ejemplos few-shot y las métricas de la última llamada (modelo, versión del prompt, tokens de entrada y salida, latencia, coste de solicitud y si la respuesta fue de caché o generada). SHALL obtener el prompt de `GET /api/v1/prompts/estimation` para las opciones vigentes y las métricas del campo `metrics` de la estimación; sin métricas SHALL mostrar «Aún no se ha generado ninguna estimación.». En el formulario, la barra SHALL actualizarse cuando el usuario cambie tipo, nivel, formato o versión. Si la API no puede renderizar el prompt, la página SHALL seguir funcionando con el aviso «El contexto del prompt no está disponible en este momento.». La barra SHALL poder ocultarse y mostrarse, y SHALL NOT aparecer en la pantalla de error.

#### Scenario: Formulario
- **WHEN** el usuario abre el formulario
- **THEN** la barra muestra el prompt de sistema y los ejemplos few-shot de las opciones por defecto y el estado vacío de métricas.

#### Scenario: Cambio de opciones
- **WHEN** el usuario cambia el tipo de proyecto, el nivel de detalle, el formato o la versión del prompt
- **THEN** la barra solicita y muestra el prompt de las nuevas opciones.

#### Scenario: Resultado con métricas
- **WHEN** se muestra una estimación con `metrics`
- **THEN** la barra muestra modelo, tokens, latencia y coste, y el prompt de las opciones de esa estimación.

#### Scenario: Prompt no disponible
- **WHEN** la API falla al renderizar el prompt
- **THEN** la barra muestra el aviso y el resto de la página funciona.

#### Scenario: Ocultar la barra
- **WHEN** el usuario pulsa el botón de la barra
- **THEN** la barra se oculta, el botón refleja el estado con `aria-expanded` y puede volver a mostrarse.

### Requirement: Historial de estimaciones
La aplicación SHALL listar las últimas 10 estimaciones de `GET /api/v1/estimations?limit=10` (fecha en formato `dd/mm/aaaa hh:mm UTC`, tipo, confianza, coste, procedencia y extracto truncado a 90 caracteres) con enlace a la vista de cada una, que se carga con `GET /api/v1/estimations/{id}`. Una estimación `out_of_scope` SHALL mostrar «No estimable» en lugar del coste.

#### Scenario: Listado
- **WHEN** el usuario abre el historial
- **THEN** ve las estimaciones devueltas por la API, en el orden recibido, cada una con enlace a su detalle.

#### Scenario: Historial vacío
- **WHEN** la API devuelve una lista vacía
- **THEN** se muestra «Todavía no hay estimaciones.» con enlace para crear la primera.

#### Scenario: Historial no disponible
- **WHEN** la API responde 503 en el listado
- **THEN** se muestra un aviso explicativo y no un error técnico.

#### Scenario: Identificador inválido
- **WHEN** el usuario abre `/estimations/abc`
- **THEN** se muestra el error de «no encontrada» sin llamar a la API.

### Requirement: Manejo de errores del cliente HTTP
El cliente SHALL llamar a la API solo por rutas relativas del propio origen, con un tiempo de espera de 300 segundos para estimar y acotado para el resto, y SHALL traducir los fallos a mensajes saneados en español, idénticos a los de la web Rails: fallo de conexión o de tiempo, 400 con el `message` del guardrail (acotado a 300 caracteres), 422, 404, 503 del historial y otros 5xx. SHALL NOT mostrar cuerpos de respuesta crudos, trazas ni URLs internas. Un cuerpo no JSON o fuera de contrato SHALL tratarse como respuesta inválida.

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

#### Scenario: Pantalla de error
- **WHEN** falla la carga de una estimación (404 o error de la API)
- **THEN** se muestra «No se pudo completar la operación» con el mensaje saneado y enlaces al historial y a nueva estimación.

### Requirement: Presentación accesible y adaptable
La aplicación SHALL usar `lang="es"`, respetar `prefers-color-scheme` (claro y oscuro), adaptarse a pantallas de menos de 800 px apilando la barra lateral sobre el contenido, y marcar los errores con `role="alert"` y el estado de carga con `role="status"` y `aria-live="polite"`.

#### Scenario: Pantalla estrecha
- **WHEN** el ancho es inferior a 800 px
- **THEN** la barra lateral y el contenido se muestran en una sola columna.

#### Scenario: Anuncio de estados
- **WHEN** aparece un error de formulario o comienza la carga
- **THEN** el error tiene `role="alert"` y la carga `role="status"`.
