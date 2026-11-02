# Spec Delta

## Purpose

Definir el servicio web en Go que sustituye al cliente Rails: debe ser funcionalmente equivalente, hablar solo con la API de IA por HTTP y poder desarrollarse, probarse y ejecutarse únicamente con Docker.

## ADDED Requirements

### Requirement: Equivalencia de rutas y respuestas
El servicio SHALL exponer las mismas rutas y métodos que el cliente Rails: `GET /` (inicio), `GET /up` (salud), `GET /estimations/new`, `GET /estimations`, `POST /estimations`, `GET /estimations/{id}`, `POST /conversation`, `GET /rag/chunking_comparisons`, `GET /rag/chunking_comparisons/new`, `POST /rag/chunking_comparisons`, `GET /rag/chunking_comparisons/{id}`, `GET /ai_settings` y `PATCH|PUT /ai_settings`. Las pantallas SHALL ser HTML renderizado en servidor con los mismos identificadores de elementos, textos en español y estados HTTP que el servicio Rails. Una ruta o recurso inexistente SHALL responder 404.

#### Scenario: Rutas heredadas
- **WHEN** un navegador abre cualquiera de las rutas anteriores
- **THEN** recibe la misma pantalla que con Rails, con los mismos enlaces entre pantallas.

#### Scenario: Sonda de salud
- **WHEN** se hace `GET /up`
- **THEN** responde 200 sin consultar la API de IA ni la base de datos.

#### Scenario: Recurso inexistente
- **WHEN** se abre `/rag/chunking_comparisons/0` o una ruta desconocida
- **THEN** responde 404.

#### Scenario: Formulario con método PATCH
- **WHEN** el formulario de Ajustes se envía con `_method=patch` por POST
- **THEN** se trata como `PATCH /ai_settings`.

### Requirement: Sesión de conversación y CSRF
El servicio SHALL conservar el `session_id` de la API y los metadatos compactados del proyecto en una cookie de sesión firmada con `SECRET_KEY_BASE`, `HttpOnly` y `SameSite=Lax`, y SHALL compactar los metadatos (nombre 80 caracteres, 10 tecnologías de 40, alcance 300) para no superar el límite de la cookie. Los avisos `flash` SHALL sobrevivir a una redirección y mostrarse una vez. Toda petición `POST`, `PATCH`, `PUT` o `DELETE` SHALL exigir un token CSRF válido (campo `authenticity_token` o cabecera `X-CSRF-Token`) y SHALL responder 422 si falta o no coincide; los formularios y la etiqueta `csrf-token` SHALL incluirlo. Una cookie manipulada SHALL tratarse como sesión vacía.

#### Scenario: Conversación persistente
- **WHEN** el usuario abre el formulario varias veces
- **THEN** se crea una sola sesión en la API y se reutiliza.

#### Scenario: Metadatos enormes
- **WHEN** la API devuelve metadatos muy largos
- **THEN** la cookie guarda la versión truncada y la página se sigue renderizando.

#### Scenario: Petición sin token
- **WHEN** llega un `POST` sin token CSRF válido
- **THEN** responde 422 y no llama a la API de IA.

#### Scenario: Cookie manipulada
- **WHEN** la cookie de sesión tiene una firma inválida
- **THEN** se ignora y la conversación empieza de cero.

### Requirement: Formulario de estimación y mapeo de errores
El servicio SHALL validar el formulario de estimación antes de llamar a la API con las mismas reglas y mensajes que Rails (descripción de 20 a 80 000 caracteres o vacía con adjuntos; `.txt` UTF-8 de hasta 400 000 bytes que sustituye a la descripción; hasta 5 adjuntos `.pdf`/`.docx` de hasta 10 MB) y SHALL enviar la estimación a `POST /api/v1/sessions/{id}/estimate` como `multipart/form-data` con `transcript`, `project_type`, `detail_level`, `output_format`, `prompt_version` y un campo `attachments` por archivo. SHALL traducir los errores de la API: sesión caducada abre otra conversación y avisa (200); cualquier otro fallo de la API en el envío se muestra como error del formulario con 422; en la pantalla de resultado, 404 si la estimación no existe y 502 en el resto.

#### Scenario: Envío válido
- **WHEN** el usuario envía una descripción válida y la API devuelve `estimation_id`
- **THEN** el servicio redirige a `/estimations/{id}`.

#### Scenario: Sin historial
- **WHEN** la API no devuelve `estimation_id`
- **THEN** se renderiza el resultado directamente con las métricas en la barra lateral.

#### Scenario: Entrada rechazada localmente
- **WHEN** la descripción es corta o el archivo no es válido
- **THEN** responde 422 con el error en el formulario, conserva lo escrito y no llama a la API.

#### Scenario: Sesión caducada
- **WHEN** la API responde 404 a la estimación de una sesión
- **THEN** se crea otra sesión, se muestra «La conversación anterior expiró en el servidor…» y el formulario conserva lo escrito.

#### Scenario: Error sin filtraciones
- **WHEN** la API responde 5xx con una traza o una clave, o no se puede conectar
- **THEN** el HTML contiene solo el mensaje genérico en español, sin traza, clave ni URL interna.

### Requirement: Chunking Lab con historial persistido
El servicio SHALL ejecutar la comparación llamando a `POST /embeddings/compare` con el corpus de presupuestos embebido, las estrategias válidas elegidas (únicas, en el orden recibido, ignorando nombres desconocidos), las consultas (marcadas más las propias, sin vacías ni repetidas) y `top_k` limitado a 1–10, con el tiempo de espera ampliado `ESTIMATOR_COMPARE_TIMEOUT` solo en esa llamada. SHALL guardar cada ejecución en la tabla `chunking_comparisons` existente (sin cambios de esquema) y redirigir a su detalle; si el guardado falla SHALL mostrar igualmente el resultado con un aviso. SHALL listar las últimas 20 ejecuciones, la más reciente primero, y SHALL seguir mostrando la pantalla si la base de datos no está disponible.

#### Scenario: Ejecución guardada
- **WHEN** se envían estrategias válidas y la API responde
- **THEN** se inserta una fila con estrategias, consultas, `top_k`, corpus, carga completa y duración, y se redirige a su detalle.

#### Scenario: Sin estrategias
- **WHEN** no se marca ninguna estrategia
- **THEN** responde 422 con «Selecciona al menos una estrategia.» sin llamar a la API.

#### Scenario: Errores del servicio
- **WHEN** la API responde 400, 503, 5xx, agota el tiempo o no responde
- **THEN** el servicio responde respectivamente 422, 503, 502, 504 y 503 con mensajes saneados.

#### Scenario: Base de datos caída
- **WHEN** PostgreSQL no está disponible
- **THEN** el historial muestra «El historial no está disponible en este momento.» y una ejecución recién calculada se muestra sin guardarse.

### Requirement: Ajustes de modelos y barra de navegación
El servicio SHALL leer y actualizar los modelos con `GET`/`PUT /api/v1/config/models`, enviar solo los siete knobs conocidos (los vacíos como `null`), limitar a los chunkers a los modelos de su proveedor y no llamar a la API si no hay cambios. SHALL mostrar en la barra el modelo primario vigente consultando la API con un tiempo de espera de `ESTIMATOR_BADGE_TIMEOUT` y cacheando el resultado, incluido el fallo, 15 segundos; guardar Ajustes SHALL invalidar esa caché; un servicio caído SHALL omitir el indicador sin impedir el renderizado.

#### Scenario: Cambio guardado
- **WHEN** el usuario guarda un modelo
- **THEN** se envía el `PUT`, se redirige a Ajustes con «Modelos actualizados…» y la barra muestra ya el nuevo modelo.

#### Scenario: Servicio caído
- **WHEN** la API no responde en la barra
- **THEN** la página se renderiza sin indicador y el fallo se cachea.

### Requirement: Frontera con la API de IA
El servicio SHALL comunicarse con el servicio de IA solo por HTTP hacia `ESTIMATOR_API_URL`, con los mismos tiempos de espera que Rails (`ESTIMATOR_OPEN_TIMEOUT` 5 s, `ESTIMATOR_READ_TIMEOUT` 300 s, `ESTIMATOR_COMPARE_TIMEOUT` 600 s, `ESTIMATOR_BADGE_TIMEOUT` 2 s), SHALL NOT recibir claves de proveedores y SHALL NOT modificar los contratos de la API Python. Ningún otro cliente del repositorio SHALL depender de un servicio Rails.

#### Scenario: Sin Rails
- **WHEN** se levanta el Compose raíz
- **THEN** ningún servicio ni configuración ejecuta Rails y las pantallas del flujo funcionan contra la API Python.

### Requirement: Desarrollo y pruebas en Docker
El servicio SHALL compilarse, probarse y ejecutarse solo con Docker: `web-test` (`go test` con PostgreSQL efímero) y `web-lint` (`gofmt` y `go vet`) en `docker-compose.verify.yml`, y una imagen de producción mínima, sin privilegios y con healthcheck sobre `/up`. Las pruebas SHALL NOT llamar a la API real ni usar claves reales.

#### Scenario: Pruebas
- **WHEN** se ejecuta `docker compose -f docker-compose.verify.yml run --rm web-test`
- **THEN** las pruebas unitarias, de endpoints, de persistencia y de integración con una API simulada pasan.

#### Scenario: Stack completo
- **WHEN** se ejecuta `docker compose up --build`
- **THEN** `estimator-web` llega a `healthy` y responde en el puerto 3000.
