# estimator/web-backend-go Specification

## Purpose
Definir el backend HTTP de aplicación en Go: API REST y SSE pública con rutas explícitas, frontera de autorización denegada por defecto, historial del Chunking Lab y desarrollo, pruebas y ejecución únicamente con Docker. No sirve HTML.

## Requirements

### Requirement: Chunking Lab con historial persistido
Go SHALL coordinar el Chunking Lab por contratos explícitos, conservar el corpus de presupuestos embebido, estrategias válidas únicas y ordenadas, consultas sin vacíos ni duplicados y `top_k` entre 1 y 10, con 3 si se omite (DA-28). Go SHALL aplicar `ESTIMATOR_COMPARE_TIMEOUT` solo a esa llamada y guardar cada ejecución en la tabla existente `chunking_comparisons` sin cambiar el esquema, tipo, precisión o valor de los IDs (DA-27) y listar las últimas 20 en orden descendente. Si el guardado falla SHALL devolver el resultado con aviso y si falla el listado SHALL indicar indisponibilidad. SHALL preservar el mapeo de errores del Lab de su capacidad específica.

#### Scenario: Ejecución guardada
- **WHEN** una comparación válida finaliza con PostgreSQL disponible
- **THEN** se guarda el resultado completo y Go devuelve el identificador

#### Scenario: Sin estrategias
- **WHEN** no se envía ninguna estrategia válida
- **THEN** se responde 422 sin invocar la API interna

#### Scenario: Errores del servicio
- **WHEN** la comparación recibe un rechazo, indisponibilidad, fallo interno o timeout
- **THEN** se aplica el mapeo del Lab con un mensaje saneado

#### Scenario: Base de datos caída
- **WHEN** se consulta el listado con PostgreSQL indisponible
- **THEN** se informa de la indisponibilidad

### Requirement: Ajustes de modelos y barra de navegación
Go SHALL ofrecer operaciones explícitas de lectura y escritura de ajustes a operadores autorizados, reutilizando `GET` y `PUT /api/v1/config/models` internos. SHALL preservar los siete knobs, aplicar null al restablecer, limitar chunkers a su proveedor y omitir escrituras sin campos reconocidos. SHALL ofrecer un indicador de modelo primario cacheado durante 15 s incluso ante fallo, con plazo corto configurable mediante `ESTIMATOR_BADGE_TIMEOUT` (2 s por defecto) e invalidación al guardar.

#### Scenario: Restablecimiento
- **WHEN** un operador restablece un override permitido
- **THEN** el servicio interno recibe null y se invalida el indicador

#### Scenario: Servicio caído
- **WHEN** IA no responde a la consulta breve
- **THEN** React sigue operativo sin indicador y el fallo se cachea durante la ventana

#### Scenario: Cambio guardado
- **WHEN** un operador guarda cambios válidos
- **THEN** Go actualiza en Python y React muestra el resultado y el indicador vigente

### Requirement: Frontera con la API de IA
Go SHALL ser el único consumidor de aplicación de la API de IA y SHALL usar clientes HTTP por contexto hacia `ESTIMATOR_API_URL` y conservar los contratos de la API de IA. SHALL NOT actuar como proxy genérico, recibir claves de proveedor ni duplicar lógica de IA. SHALL propagar a Python la cancelación recibida desde React mediante Nginx o Vite. Python SHALL detener el trabajo cancelable y liberar recursos. Ninguna capa SHALL reintentar automáticamente una solicitud cancelada ni un POST. Los resultados parciales SHALL NOT persistirse. Una escritura confirmada antes de la cancelación puede permanecer en PostgreSQL. Los presupuestos configurables de conexión, cabeceras, operación total e inactividad SHALL distinguirse y coordinarse con Vite, Nginx, React y Python.

#### Scenario: Cancelación antes de persistir
- **WHEN** React cancela por Nginx o Vite mientras Python está detenido por un fake antes de iniciar la escritura
- **THEN** Python y su fake observan la cancelación, no se crea una fila y se observa un único POST

#### Scenario: Cancelación después de confirmar una escritura
- **WHEN** el flujo de prueba confirma la escritura completa en PostgreSQL y retiene la respuesta hasta que React cancela
- **THEN** Python observa la cancelación, el historial conserva exactamente esa fila confirmada y se observa un único POST

#### Scenario: Generación lenta válida
- **WHEN** la respuesta tarda más que una operación habitual pero cabe en el plazo de generación
- **THEN** los intermediarios y el cliente permiten completarla

#### Scenario: Timeout
- **WHEN** se supera el presupuesto antes de confirmar cabeceras
- **THEN** Go devuelve 504 saneado sin duplicar la operación

#### Scenario: Sin Rails
- **WHEN** se verifica el Compose raíz y su flujo de aplicación
- **THEN** React funciona con Go y el servicio interno de IA sin dependencia de Rails

### Requirement: Desarrollo y pruebas en Docker
El servicio SHALL compilarse, probarse y ejecutarse solo con Docker: `web-test` (`go test` con PostgreSQL efímero) y `web-lint` (`gofmt` y `go vet`) en `docker-compose.verify.yml`, y una imagen de producción mínima, sin privilegios y con healthcheck sobre `/up`. Las pruebas SHALL NOT llamar a la API real ni usar claves reales.

#### Scenario: Pruebas
- **WHEN** se ejecuta `docker compose -f docker-compose.verify.yml run --rm web-test`
- **THEN** las pruebas unitarias, de endpoints, de persistencia y de integración con una API simulada pasan.

#### Scenario: Stack completo
- **WHEN** se ejecuta `docker compose up --build`
- **THEN** `estimator-web` llega a `healthy` y responde a la sonda local sin publicar su puerto en integración.

### Requirement: Contratos JSON de Ajustes y Chunking Lab
Go SHALL exponer GET y PUT `/api/v1/ai/settings`, GET `/api/v1/ai/primary-model`, GET `/api/v1/rag/chunking-comparisons/options`, GET y POST `/api/v1/rag/chunking-comparisons` y GET `/api/v1/rag/chunking-comparisons/{id}`. Los contratos SHALL ser explícitos y devolver JSON. Go SHALL intermediar configuración y cálculo hacia IA y resolver por sí mismo las opciones y el almacenamiento del Lab. Configuración, catálogo y Lab SHALL quedar reservados a admin. La proyección general del indicador SHALL limitarse al nombre primario efectivo o null.

#### Scenario: Contratos explícitos
- **WHEN** se ejercitan las siete operaciones en Docker con fakes y autorización de prueba
- **THEN** se observan los esquemas y estados de la matriz HTTP y ninguna lectura de historial o detalle del Lab llama a IA

#### Scenario: Intento de acceso administrativo
- **WHEN** se llama directamente a cualquier operación administrativa en la composición normal, incluso con UUID conversacional, cookie HTML o cabecera de rol
- **THEN** Go devuelve 403 saneado sin llamada a IA ni al repositorio y sin entregar datos

#### Scenario: Imagen normal
- **WHEN** se inspecciona y ejerce la imagen normal con variables de entorno y solicitudes manipuladas
- **THEN** no existe modo de activar una autorización de pruebas, aceptar credenciales predeterminadas ni suplantar identidad o rol mediante cabeceras

### Requirement: Retirada del servidor HTML de aplicación
El despliegue consolidado SHALL servir la experiencia web únicamente desde React. La retirada de vistas, plantillas, formularios y sesión HTML Go SHALL quedar condicionada a evidencia de paridad funcional de estimaciones, conversación, historial, vista previa, Ajustes y Chunking Lab demostrada con fakes exclusivos de pruebas y a evidencia de que la composición normal deniega todas las operaciones administrativas. La retirada SHALL preservar las funciones compartidas y los datos.

#### Scenario: Corte de cliente
- **WHEN** se activa la arquitectura consolidada
- **THEN** React presenta las capacidades verificadas y Go devuelve contratos HTTP sin servir páginas de aplicación independientes

### Requirement: Contratos públicos de aplicación y salud
Go SHALL exponer explícitamente `POST /api/v1/sessions`, `POST /api/v1/sessions/{session_id}/estimate`, `GET /api/v1/prompts/estimation`, `GET /api/v1/estimations`, `GET /api/v1/estimations/{estimation_id}`, `POST /api/v1/estimate`, `POST /api/v1/estimate/stream`, `POST /api/v1/transcription/estimate/stream` y `GET /health`. SHALL preservar métodos, parámetros, tipos de contenido, códigos funcionales y formas de éxito, incluidos campos opcionales y nulos. SHALL mantener `/up` como sonda local e independiente. `/health` SHALL devolver el JSON saludable compatible con la sonda interna cuando Go pueda alcanzarla y 503 saneado cuando esté indisponible o sea inválida, sin invocar proveedores ni verificar todos los almacenes. `GET /up` SHALL responder 200 sin consultar IA ni PostgreSQL.

#### Scenario: Compatibilidad JSON y multipart
- **WHEN** se envían las mismas solicitudes válidas a ambas fronteras en pruebas
- **THEN** se conservan el 201 con UUID, las respuestas de estimación y sesión con campos opcionales, los defaults y las respuestas de historial y de vista previa

#### Scenario: Salud
- **WHEN** se detiene el upstream mientras Go sigue operativo
- **THEN** por Nginx se recibe 503 saneado en /health y la sonda local /up sigue respondiendo 200

#### Scenario: Superficie controlada
- **WHEN** se solicita una ruta de IA ajena al catálogo público o un método incorrecto
- **THEN** Go responde 404 o 405 respectivamente sin llamar a IA

### Requirement: Seguridad de sesión, origen y administración
Las sesiones conversacionales de la API pública SHALL referenciarse mediante el identificador en la ruta y SHALL NOT depender de cookies Go. Go SHALL rechazar mutaciones de navegador con origen cruzado o nulo. Tras retirar la interfaz HTML, Go SHALL NOT emitir cookies ni mantener estado de navegación, avisos flash ni token CSRF de formulario. Si el navegador envía la cookie legada `_estimator_web_session`, Go SHALL expirarla (`Max-Age=0`, `Path=/`, `HttpOnly`) sin interpretar ni validar su contenido, de modo que no existe sesión que firmar ni sesión vacía que tratar. La protección de las mutaciones del navegador SHALL basarse en la validación de origen. Go SHALL decidir la autorización de cada operación administrativa, incluidas las lecturas, antes de consultar cachés administrativas o acceder a IA o PostgreSQL. La composición normal SHALL devolver 403 saneado por ausencia, denegación o fallo de la decisión. Las sesiones conversacionales SHALL ser independientes de las futuras sesiones de identidad. La integración de identidad, sesiones de autenticación, roles admin y user y aislamiento por usuario queda en homelab-authentication-authorization.

#### Scenario: Sesión sin cookie
- **WHEN** React crea sesión y envía un turno desde el mismo origen
- **THEN** la respuesta no depende de cookies HTML y un identificador caducado obtiene 404

#### Scenario: Cookie legada
- **WHEN** un navegador envía la cookie `_estimator_web_session` a cualquier ruta de Go, con o sin firma válida
- **THEN** Go no la interpreta, responde con su expiración y ninguna respuesta emite cookies nuevas

#### Scenario: Mutación cruzada
- **WHEN** otro origen envía un formulario de estimación o una mutación administrativa
- **THEN** se rechaza antes de llamar a IA

### Requirement: Validación de transporte y errores de estimación
Go SHALL controlar tamaño total, tipo y sintaxis del cuerpo y límites de transporte de multipart incluyendo un máximo de cinco adjuntos de hasta 10 MiB. SHALL conservar partes repetidas y opciones compatibles. Python conserva la extracción y las validaciones de negocio. Go SHALL preservar 400 de guardrails con `reason` y `message` saneados, 404 de sesión, 413, 415 y 422 compatibles con React. Los errores públicos SHALL NOT revelar trazas, URL internas, secretos, entradas del usuario ni cuerpos crudos upstream.

#### Scenario: Adjuntos válidos
- **WHEN** se envía una estimación con varios PDF/DOCX dentro del límite o solo adjuntos con texto suficiente
- **THEN** Python recibe todos los adjuntos y procesa la entrada

#### Scenario: Tamaño excesivo
- **WHEN** el cuerpo multipart desborda el límite incluidos cuerpos sin Content-Length
- **THEN** la frontera devuelve 413 y no invoca la generación

#### Scenario: Rechazo seguro
- **WHEN** IA rechaza un guardrail o un documento ilegible
- **THEN** la respuesta conserva 400 con reason/message o 422 con un detail saneado

#### Scenario: Sin historial
- **WHEN** la persistencia de IA está desactivada
- **THEN** se devuelve el resultado con estimation_id nulo

#### Scenario: Sesión caducada
- **WHEN** Python devuelve 404 de sesión
- **THEN** Go conserva el 404 y React crea otra sesión y avisa sin reenviar el turno

#### Scenario: Error sin filtraciones
- **WHEN** la respuesta upstream trae una traza con un secreto ficticio
- **THEN** Go devuelve un error saneado sin reproducir la entrada ni la respuesta cruda
