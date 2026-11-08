## ADDED Requirements

### Requirement: API JSON bajo /api
El servicio SHALL ser un API JSON y SHALL NOT renderizar HTML ni servir plantillas, ficheros estáticos ni páginas de error HTML. SHALL exponer `GET /up` (salud) y, bajo el prefijo `/api/`, `POST /api/conversations`, `POST /api/conversations/{id}/estimations`, `GET /api/estimations`, `GET /api/estimations/{id}`, `GET /api/prompt-preview`, `GET /api/chunking-comparisons/options`, `GET|POST /api/chunking-comparisons`, `GET /api/chunking-comparisons/{id}`, `GET|PUT /api/ai-settings` y `GET /api/primary-model`. Las rutas SHALL NOT usar el prefijo `/api/v1/` del servicio de IA. Toda respuesta salvo `/up` SHALL ser `application/json`; una ruta o recurso inexistente SHALL responder 404 con `{"detail": "..."}`.

#### Scenario: Sonda de salud
- **WHEN** se hace `GET /up`
- **THEN** responde 200 sin consultar la API de IA ni la base de datos.

#### Scenario: Sin rutas HTML
- **WHEN** se pide `/`, `/estimations`, `/rag/chunking_comparisons`, `/ai_settings` o `/robots.txt`
- **THEN** responde 404 JSON y el repositorio no contiene plantillas ni assets HTML del servicio.

#### Scenario: Recurso inexistente
- **WHEN** se pide `/api/chunking-comparisons/0` o una ruta desconocida
- **THEN** responde 404 con un `detail` en español.

### Requirement: Conversación sin estado de navegador
El servicio SHALL NOT usar cookies, sesión firmada, mensajes flash ni tokens CSRF. `POST /api/conversations` SHALL abrir una sesión en la API de IA y devolver `201` con `{"conversation_id": "<id>"}`; el cliente SHALL conservar ese identificador y enviarlo en cada estimación. Los `project_metadata` SHALL devolverse completos en cada respuesta de estimación. Si la API de IA ya no conoce la sesión, `POST /api/conversations/{id}/estimations` SHALL responder 404 con un `detail` que indique que la conversación expiró.

#### Scenario: Abrir conversación
- **WHEN** un cliente hace `POST /api/conversations`
- **THEN** recibe 201 con un `conversation_id` y la respuesta no incluye `Set-Cookie`.

#### Scenario: Sesión caducada
- **WHEN** la API de IA responde 404 a la estimación de una sesión
- **THEN** el servicio responde 404 con «La conversación anterior expiró en el servidor…» y no crea otra sesión por su cuenta.

#### Scenario: Metadatos extensos
- **WHEN** la API de IA devuelve metadatos largos
- **THEN** la respuesta los incluye completos, sin truncar.

### Requirement: Errores JSON saneados
Todo error SHALL responder `{"detail": "<mensaje en español>"}` con el estado HTTP del mapeo documentado (422 entrada o rechazo de la API, 404, 502, 503, 504). El `detail` SHALL NOT contener trazas, claves, URLs internas ni cuerpos de proveedor; el detalle técnico SHALL registrarse en el log. Un pánico SHALL responder 500 con un mensaje genérico.

#### Scenario: Error sin filtraciones
- **WHEN** la API de IA responde 5xx con una traza o una clave, o no se puede conectar
- **THEN** la respuesta contiene solo el mensaje genérico en español, sin traza, clave ni URL interna.

#### Scenario: Pánico
- **WHEN** un handler entra en pánico
- **THEN** responde 500 JSON genérico y el servicio sigue atendiendo peticiones.

### Requirement: Ajustes de modelos e indicador del modelo primario
El servicio SHALL leer y actualizar los modelos con `GET`/`PUT /api/v1/config/models` de la API de IA a través de `GET`/`PUT /api/ai-settings`, enviar solo los siete knobs conocidos (los vacíos como `null`), limitar a los chunkers a los modelos de su proveedor y no llamar a la API si no hay cambios. `GET /api/primary-model` SHALL devolver el modelo primario vigente consultando la API con un tiempo de espera de `ESTIMATOR_BADGE_TIMEOUT` y cacheando el resultado, incluido el fallo, 15 segundos; guardar ajustes SHALL invalidar esa caché; un servicio caído SHALL devolver `primary_model` vacío con 200.

#### Scenario: Cambio guardado
- **WHEN** un cliente guarda un modelo con `PUT /api/ai-settings`
- **THEN** se envía el `PUT` a la API de IA, la respuesta trae el catálogo actualizado y `GET /api/primary-model` ya devuelve el nuevo modelo.

#### Scenario: Servicio caído
- **WHEN** la API de IA no responde al consultar el modelo primario
- **THEN** responde 200 con `primary_model` vacío y el fallo se cachea.

## MODIFIED Requirements

### Requirement: Formulario de estimación y mapeo de errores
El servicio SHALL validar la estimación antes de llamar a la API con las reglas y mensajes de `internal/estimation` (descripción de 20 a 80 000 caracteres o vacía con adjuntos; `.txt` UTF-8 de hasta 400 000 bytes que sustituye a la descripción; hasta 5 adjuntos `.pdf`/`.docx` de hasta 10 MB) y SHALL enviarla a `POST /api/v1/sessions/{id}/estimate` de la API de IA como `multipart/form-data` con `transcript`, `project_type`, `detail_level`, `output_format`, `prompt_version` y un campo `attachments` por archivo. `POST /api/conversations/{id}/estimations` SHALL aceptar `multipart/form-data` con `description`, `project_type`, `detail_level`, `output_format`, `prompt_version`, `upload` y `attachments`, y devolver el JSON de la estimación con sus `project_metadata`. SHALL traducir los errores de la API: entrada inválida o cualquier rechazo en el envío 422 con el mensaje; sesión caducada 404; en la lectura de una estimación, 404 si no existe y 502 en el resto.

#### Scenario: Envío válido
- **WHEN** un cliente envía una descripción válida y la API devuelve `estimation_id`
- **THEN** el servicio responde 200 con el resultado, `estimation_id` y `project_metadata`.

#### Scenario: Sin historial
- **WHEN** la API no devuelve `estimation_id`
- **THEN** la respuesta incluye el resultado y las métricas, sin `estimation_id`.

#### Scenario: Entrada rechazada localmente
- **WHEN** la descripción es corta o el archivo no es válido
- **THEN** responde 422 con el mensaje de validación y no llama a la API.

#### Scenario: Sesión caducada
- **WHEN** la API responde 404 a la estimación de una sesión
- **THEN** el servicio responde 404 con «La conversación anterior expiró en el servidor…» y el cliente abre otra conversación.

#### Scenario: Error sin filtraciones
- **WHEN** la API responde 5xx con una traza o una clave, o no se puede conectar
- **THEN** la respuesta contiene solo el mensaje genérico en español.

### Requirement: Chunking Lab con historial persistido
El servicio SHALL ejecutar la comparación con `POST /api/chunking-comparisons` (JSON `strategies`, `queries`, `top_k`) llamando a `POST /embeddings/compare` con el corpus de presupuestos embebido, las estrategias válidas elegidas (únicas, en el orden recibido, ignorando nombres desconocidos), las consultas (sin vacías ni repetidas) y `top_k` limitado a 1–10, con el tiempo de espera ampliado `ESTIMATOR_COMPARE_TIMEOUT` solo en esa llamada. SHALL guardar cada ejecución en la tabla `chunking_comparisons` existente (sin cambios de esquema) y responder 201 con la comparación guardada; si el guardado falla SHALL responder 201 con el resultado, `saved: false` y un aviso. `GET /api/chunking-comparisons` SHALL listar las últimas 20, la más reciente primero, y responder 503 con «El historial no está disponible en este momento.» si la base de datos no está disponible. `GET /api/chunking-comparisons/options` SHALL devolver el catálogo de estrategias, las seleccionadas por defecto, las consultas predefinidas y el tiempo de espera.

#### Scenario: Ejecución guardada
- **WHEN** se envían estrategias válidas y la API responde
- **THEN** se inserta una fila con estrategias, consultas, `top_k`, corpus, carga completa y duración, y se responde 201 con su `id`.

#### Scenario: Sin estrategias
- **WHEN** no se envía ninguna estrategia válida
- **THEN** responde 422 con «Selecciona al menos una estrategia.» sin llamar a la API.

#### Scenario: Errores del servicio
- **WHEN** la API responde 400, 503, 5xx, agota el tiempo o no responde
- **THEN** el servicio responde respectivamente 422, 503, 502, 504 y 503 con mensajes saneados.

#### Scenario: Base de datos caída
- **WHEN** PostgreSQL no está disponible
- **THEN** el listado responde 503 con el aviso del historial y una ejecución recién calculada se devuelve con `saved: false`.

### Requirement: Frontera con la API de IA
El servicio SHALL comunicarse con el servicio de IA solo por HTTP hacia `ESTIMATOR_API_URL` mediante `internal/estimatorai`, con los tiempos de espera `ESTIMATOR_OPEN_TIMEOUT` 5 s, `ESTIMATOR_READ_TIMEOUT` 300 s, `ESTIMATOR_COMPARE_TIMEOUT` 600 s y `ESTIMATOR_BADGE_TIMEOUT` 2 s, SHALL NOT recibir claves de proveedores y SHALL NOT modificar los contratos de la API Python. SHALL ser el único componente del repositorio que llama al servicio de IA: ni la web React ni el cliente Streamlit SHALL tener una referencia de red a él.

#### Scenario: Sin Rails
- **WHEN** se levanta el Compose raíz
- **THEN** ningún servicio ni configuración ejecuta Rails y solo `estimator-web` tiene `ESTIMATOR_API_URL` apuntando a `estimador-cag`.

## REMOVED Requirements

### Requirement: Equivalencia de rutas y respuestas
**Reason**: el servicio deja de ser un cliente HTML equivalente a Rails; pasa a ser un API JSON (ver «API JSON bajo /api»).
**Migration**: las pantallas viven en `estimator-web-react` (mismas URL de navegador) y en `estimator-streamlit`; los clientes usan las rutas `/api/...`.

### Requirement: Sesión de conversación y CSRF
**Reason**: la cookie firmada, el flash y el CSRF solo servían para renderizar HTML en servidor.
**Migration**: el cliente conserva el `conversation_id` (ver «Conversación sin estado de navegador»).

### Requirement: Ajustes de modelos y barra de navegación
**Reason**: no hay barra de navegación en el backend; el indicador pasa a un endpoint JSON.
**Migration**: ver «Ajustes de modelos e indicador del modelo primario».
