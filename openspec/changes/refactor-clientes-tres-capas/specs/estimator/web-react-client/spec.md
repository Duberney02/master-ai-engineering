## ADDED Requirements

### Requirement: Backend Go como única dependencia de red
La aplicación SHALL llamar solo a rutas relativas `/api/...` de su propio origen, que el proxy nginx reenvía al backend `estimator-web` (`API_UPSTREAM=http://estimator-web:3000`). La aplicación, su configuración de nginx y su Compose SHALL NOT contener ninguna referencia de red al servicio de IA (`estimador-cag`, el puerto 8000 ni rutas `/api/v1/`).

#### Scenario: Proxy hacia el backend
- **WHEN** se abre `http://localhost:3001/estimations`
- **THEN** la aplicación se sirve desde su origen y sus llamadas a `/api/...` llegan a `estimator-web` sin exponer direcciones internas ni requerir CORS.

#### Scenario: Sin referencias al servicio de IA
- **WHEN** se inspeccionan `nginx.conf.template`, el código de `src/` y el servicio del Compose
- **THEN** ninguno menciona `estimador-cag`, `:8000` ni `/api/v1/`.

### Requirement: Chunking Lab en React
La aplicación SHALL ofrecer `/rag/chunking_comparisons` (historial de las últimas 20 ejecuciones, la más reciente primero), `/rag/chunking_comparisons/new` (formulario) y `/rag/chunking_comparisons/:id` (resultado). El formulario SHALL mostrar las ocho estrategias con etiqueta, descripción y nivel de coste, con solo las gratuitas marcadas por defecto, aviso de coste y de la clave de proveedor requerida en las de pago (y un aviso al marcarlas), las consultas predefinidas, un campo de consultas propias (una por línea) y `top_k` entre 1 y 10, y SHALL mostrar un indicador de carga con el tiempo de espera máximo al enviar. SHALL rechazar sin llamar al backend una selección vacía con «Selecciona al menos una estrategia.». El resultado SHALL mostrar la tabla de estadísticas por estrategia (chunks, mínimo, p50, p95, máximo, huérfanos, obesos, llamadas extra y segundos), barras de coste proporcionales al mayor (o un mensaje si todas son gratuitas) y, si hubo consultas, el top-k de cada estrategia con su similitud y, en la jerárquica, la marca «padre» o el padre del hijo. Los errores del backend (422, 503, 504, 502) SHALL mostrarse como avisos saneados manteniendo el formulario con lo elegido, y un historial no disponible SHALL mostrarse vacío con un aviso. Si el resultado llega con `saved: false`, SHALL mostrarse con el aviso de que no se guardó.

#### Scenario: Selección por defecto
- **WHEN** se abre el formulario
- **THEN** solo las estrategias gratuitas están marcadas y la contextual indica que requiere `ANTHROPIC_API_KEY`.

#### Scenario: Ejecución correcta
- **WHEN** el usuario envía estrategias válidas y el backend responde 201
- **THEN** la aplicación navega a `/rag/chunking_comparisons/{id}` y muestra estadísticas, costes y, si hubo consultas, el playground.

#### Scenario: Sin estrategias
- **WHEN** no se marca ninguna estrategia
- **THEN** se muestra «Selecciona al menos una estrategia.» y no se llama al backend.

#### Scenario: Error del servicio
- **WHEN** el backend responde 504
- **THEN** se muestra el aviso que sugiere probar con menos estrategias y el formulario conserva lo elegido.

#### Scenario: Historial no disponible
- **WHEN** el backend responde 503 al listar
- **THEN** se muestra el historial vacío con «El historial no está disponible en este momento.».

### Requirement: Ajustes de IA en React
La aplicación SHALL ofrecer `/ai_settings` con los siete knobs de modelo, su descripción, su valor por defecto, su valor vigente (marcando los que tienen override) y un selector con los modelos del catálogo; los chunkers SHALL ofrecer solo modelos de su proveedor, un selector vacío SHALL significar «usar el valor por defecto» y el modelo de embeddings SHALL mostrarse de solo lectura con su nota. Guardar SHALL enviar `PUT /api/ai-settings` con todos los knobs (vacíos como `null`), mostrar un aviso de confirmación y refrescar el indicador del modelo primario; un rechazo (422) SHALL mostrar el detalle del backend y un servicio caído (503) un aviso sin formulario.

#### Scenario: Override visible
- **WHEN** el crítico tiene un override
- **THEN** su fila lo marca y el selector lo tiene preseleccionado.

#### Scenario: Restablecer
- **WHEN** el usuario deja vacío el selector de un knob con override y guarda
- **THEN** se envía `null` para ese knob.

#### Scenario: Servicio caído
- **WHEN** el backend responde 503 al abrir los ajustes
- **THEN** se muestra un aviso y no el formulario.

### Requirement: Indicador del modelo primario
La barra de navegación SHALL mostrar el modelo primario vigente obtenido de `GET /api/primary-model`. Si el valor llega vacío o la llamada falla, el indicador SHALL omitirse sin afectar a la página. Tras guardar los ajustes SHALL volver a consultarse.

#### Scenario: Con modelo
- **WHEN** el backend devuelve un modelo
- **THEN** la barra lo muestra.

#### Scenario: Sin modelo
- **WHEN** el backend devuelve `primary_model` vacío o falla
- **THEN** la barra se renderiza sin indicador.

## MODIFIED Requirements

### Requirement: Rutas equivalentes a la web Rails
La aplicación SHALL ofrecer las rutas `/` (nueva estimación), `/estimations` (historial), `/estimations/:id` (detalle), `/rag/chunking_comparisons`, `/rag/chunking_comparisons/new`, `/rag/chunking_comparisons/:id` y `/ai_settings`, con la navegación «Nueva estimación», «Historial», «Chunking Lab» y «Ajustes» presente en todas las pantallas. Una ruta desconocida SHALL mostrar un mensaje de página no encontrada en español.

#### Scenario: Navegación
- **WHEN** el usuario abre cualquier pantalla
- **THEN** ve los enlaces «Nueva estimación», «Historial», «Chunking Lab» y «Ajustes» y llevan a `/`, `/estimations`, `/rag/chunking_comparisons` y `/ai_settings`.

#### Scenario: Ruta desconocida
- **WHEN** el usuario abre una ruta que no existe
- **THEN** se muestra un mensaje de página no encontrada con enlaces de vuelta.

### Requirement: Formulario de estimación con carga de `.txt`
La aplicación SHALL presentar un formulario con descripción (20–80 000 caracteres) y contador de caracteres, tipo de proyecto, nivel de detalle, formato de salida y versión de prompt (`v3` por defecto), la opción de adjuntar un `.txt` cuyo contenido sustituye a la descripción y la selección de varios adjuntos PDF o Word. SHALL crear una conversación con `POST /api/conversations` al cargar la página, conservar su `conversation_id` mientras la página siga abierta, y enviar cada estimación como multipart a `POST /api/conversations/{conversation_id}/estimations`. SHALL mostrar los `project_metadata` en la barra lateral y un botón «Nueva conversación» que cree otra conversación y reinicie el estado. Si el backend responde 404 por conversación desconocida, SHALL iniciar una conversación nueva e informar al usuario. SHALL rechazar sin llamar al backend: descripciones fuera de rango (tras recortar espacios), archivos de transcripción que no sean `.txt`, que no sean UTF-8 válido o de más de 400 000 bytes, y adjuntos que no sean PDF o Word, con los mismos mensajes en español. Al enviar, SHALL deshabilitar el botón y mostrar un indicador de carga con un temporizador de segundos transcurridos, y SHALL restaurarlos al terminar con éxito o con error.

#### Scenario: Descripción válida
- **WHEN** el usuario envía una descripción válida
- **THEN** la aplicación llama a `POST /api/conversations/{conversation_id}/estimations` como multipart con `description`, `project_type`, `detail_level`, `output_format` y `prompt_version`.

#### Scenario: Sesión al cargar
- **WHEN** se carga la página
- **THEN** la aplicación crea una conversación y reutiliza su identificador en todos los envíos hasta crear una nueva.

#### Scenario: Carga de un archivo
- **WHEN** el usuario adjunta un `.txt` UTF-8 válido de hasta 400 000 bytes
- **THEN** su contenido sustituye a la descripción y el contador se actualiza.

#### Scenario: Adjuntos múltiples
- **WHEN** el usuario selecciona varios PDF o Word
- **THEN** el envío incluye todos como `attachments`.

#### Scenario: Metadatos y nueva conversación
- **WHEN** la estimación devuelve `project_metadata` y el usuario pulsa «Nueva conversación»
- **THEN** la barra los muestra y después se crea otra conversación con los metadatos vacíos y el formulario reiniciado.

#### Scenario: Archivo inválido
- **WHEN** el archivo no es `.txt`, no es UTF-8 válido o supera 400 000 bytes
- **THEN** se muestra «El archivo debe ser de texto plano (.txt).», «El archivo debe estar codificado en UTF-8.» o «El archivo supera el máximo de 400 KB.» y no se llama al backend.

#### Scenario: Descripción fuera de rango
- **WHEN** la descripción tiene menos de 20 o más de 80 000 caracteres
- **THEN** se muestra «La descripción debe tener entre 20 y 80000 caracteres.» y no se llama al backend.

#### Scenario: Indicador y temporizador
- **WHEN** se envía el formulario y el backend aún no ha respondido
- **THEN** el botón queda deshabilitado y aparecen el indicador de carga y un temporizador que avanza por segundos.

#### Scenario: Conservación de datos tras un error
- **WHEN** el backend responde con un error
- **THEN** el formulario conserva lo que el usuario había escrito y elegido, muestra el mensaje saneado y rehabilita el botón.

### Requirement: Barra lateral de contexto del prompt
La aplicación SHALL mostrar a la izquierda el prompt de sistema renderizado (solo lectura), los ejemplos few-shot y las métricas de la última llamada (modelo, versión del prompt, tokens de entrada y salida, latencia, coste de solicitud y si la respuesta fue de caché o generada). SHALL obtener el prompt de `GET /api/prompt-preview` para las opciones vigentes y las métricas del campo `metrics` de la estimación; sin métricas SHALL mostrar «Aún no se ha generado ninguna estimación.». En el formulario, la barra SHALL actualizarse cuando el usuario cambie tipo, nivel, formato o versión. Si el backend no puede renderizar el prompt, la página SHALL seguir funcionando con el aviso «El contexto del prompt no está disponible en este momento.». La barra SHALL poder ocultarse y mostrarse, y SHALL NOT aparecer en la pantalla de error.

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
- **WHEN** el backend falla al renderizar el prompt
- **THEN** la barra muestra el aviso y el resto de la página funciona.

#### Scenario: Ocultar la barra
- **WHEN** el usuario pulsa el botón de la barra
- **THEN** la barra se oculta, el botón refleja el estado con `aria-expanded` y puede volver a mostrarse.

### Requirement: Historial de estimaciones
La aplicación SHALL listar las últimas 10 estimaciones de `GET /api/estimations?limit=10` (fecha en formato `dd/mm/aaaa hh:mm UTC`, tipo, confianza, coste, procedencia y extracto truncado a 90 caracteres) con enlace a la vista de cada una, que se carga con `GET /api/estimations/{id}`. Una estimación `out_of_scope` SHALL mostrar «No estimable» en lugar del coste.

#### Scenario: Listado
- **WHEN** el usuario abre el historial
- **THEN** ve las estimaciones devueltas por el backend, en el orden recibido, cada una con enlace a su detalle.

#### Scenario: Historial vacío
- **WHEN** el backend devuelve una lista vacía
- **THEN** se muestra «Todavía no hay estimaciones.» con enlace para crear la primera.

#### Scenario: Historial no disponible
- **WHEN** el backend responde 503 en el listado
- **THEN** se muestra un aviso explicativo y no un error técnico.

#### Scenario: Identificador inválido
- **WHEN** el usuario abre `/estimations/abc`
- **THEN** se muestra el error de «no encontrada» sin llamar al backend.

### Requirement: Manejo de errores del cliente HTTP
El cliente SHALL llamar al backend solo por rutas relativas del propio origen, con un tiempo de espera de 300 segundos para estimar, de 600 para el Chunking Lab y acotado para el resto, y SHALL traducir los fallos a mensajes saneados en español: fallo de conexión o de tiempo, 422 con el `detail` del backend (acotado a 300 caracteres), 404, 503 del historial y otros 5xx. SHALL NOT mostrar cuerpos de respuesta crudos, trazas ni URLs internas. Un cuerpo no JSON o fuera de contrato SHALL tratarse como respuesta inválida.

#### Scenario: API caída
- **WHEN** el backend no acepta la conexión o excede el tiempo
- **THEN** se muestra «No se pudo conectar con la API del estimador.» sin detalles internos.

#### Scenario: Rechazo de guardrails
- **WHEN** el backend responde 422 con `{detail}`
- **THEN** se muestra ese `detail` como error del formulario.

#### Scenario: Error del servidor
- **WHEN** el backend responde 5xx
- **THEN** se muestra un mensaje genérico y no el cuerpo de la respuesta.

#### Scenario: Respuesta inválida
- **WHEN** el backend responde 200 con un cuerpo que no es JSON o sin `result`
- **THEN** se muestra un mensaje de respuesta inválida.

#### Scenario: Pantalla de error
- **WHEN** falla la carga de una estimación (404 o error del backend)
- **THEN** se muestra «No se pudo completar la operación» con el mensaje saneado y enlaces al historial y a nueva estimación.
