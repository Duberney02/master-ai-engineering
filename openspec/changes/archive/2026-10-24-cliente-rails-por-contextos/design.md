# Design

## Context

`estimator-web` es una app Rails 8 mínima: sin base de datos, HTML con CSS y JS en línea, un servicio monolítico `EstimatorApi` (Faraday + mensajes saneados) y 97 pruebas Minitest + WebMock. La referencia usa un cliente base con errores tipados y un cliente por contexto, contratos POROs, Tailwind/Stimulus/importmap y PostgreSQL con JSONB.

## Decisions

**Persistencia: PostgreSQL propio.** El historial del Lab necesita guardar JSONB con el payload completo. Opciones: (a) SQLite con volumen, (b) PostgreSQL como servicio nuevo de Compose. Se elige (b): es el motor del resto del stack, soporta JSONB nativo y no se pierde al reconstruir el contenedor (volumen propio). Es una base **distinta** de la de la API (`estimator-web-db`, usuario y contraseña propios) para no acoplar el esquema del cliente al del servicio. El `Dockerfile` instala `libpq5`, y un entrypoint ejecuta `db:prepare` solo si hay `DATABASE_URL` y se arranca el servidor; sin base de datos todo funciona salvo el guardado del Lab.

**Degradación sin base de datos.** Una ejecución del Lab con estrategias de pago cuesta dinero: si el historial no puede guardarla, se muestra igualmente el resultado con un aviso en lugar de perderla; el índice del historial muestra «no disponible» sin romper la página.

**Capa HTTP: migración completa, no fachada.** Se partió `EstimatorApi` en `EstimationsClient` y `SessionsClient` (métodos movidos sin cambiar de comportamiento) sobre un `BaseClient` que conserva la lógica y los mensajes. Los controllers usan los clientes y las dos suites de `EstimatorApi` se movieron a la suite de cada cliente cambiando solo el nombre de clase y de constantes. Se descartó mantener `EstimatorApi` como fachada: habría dejado código muerto. `EstimationForm` y la sesión de conversación se dejan como estaban (solo cambian sus llamadas).

**Taxonomía de errores tipados.** `EstimatorAi::Error` con hijos por causa (`ConnectionFailed`, `RequestTimeout`, `InvalidRequest`, `GuardrailViolation`, `NotFound`, `SessionExpired`, `ServiceUnavailable`, `ServerError`, `InvalidResponse`), un archivo por clase (Zeitwerk) y mensajes siempre en español y saneados. Los timeouts conservan el mensaje de conexión de antes para no cambiar el comportamiento existente. Los clientes de configuración y embeddings muestran el `detail` del servicio (lo redacta la API sin datos del usuario), lo que permite avisos accionables («requiere ANTHROPIC_API_KEY»). La referencia deja que los controllers capturen también errores de Faraday; aquí la capa HTTP traduce todo y los controllers solo ven `EstimatorAi::Error`.

**Sin Tailwind, Stimulus ni importmap.** El cliente actual usa CSS y JS en línea; introducir un pipeline de assets sería un cambio de estilo ajeno al alcance. El Lab y Ajustes usan el mismo CSS en línea del layout (ampliado) y un pequeño script en el formulario (aviso de pago, indicador de carga).

**Navegación.** `/` pasa a ser un panel con una tarjeta por contexto; el formulario de estimación se mueve a `/estimations/new` (ruta con nombre `new_estimation`). Es un cambio de ruta del cliente, no del servicio; los tests del formulario se actualizaron a la ruta nueva. La barra marca la sección activa con `aria-current`.

**Indicador del modelo primario.** Un helper consulta `GET /config/models` con un tiempo de espera de 2 s y cachea el resultado 15 s (también el fallo, para no reintentar en cada página con el servicio caído). Guardar en Ajustes borra la entrada. Captura `StandardError`: decoración pura que jamás rompe una página. Las pruebas simulan siempre ese endpoint para renderizar el layout sin el servicio.

**Estrategias de pago opt-in.** El formulario marca solo las gratuitas; las de pago llevan etiqueta de coste y de clave y un aviso al marcarlas. El servicio ejecuta solo las gratuitas si no recibe estrategias, y el cliente siempre envía las seleccionadas. La referencia marcaba por defecto tres gratuitas y dejaba el resto desmarcado, igual que aquí.

**Corpus.** Los 15 presupuestos de ejemplo y los 3 casos límite viajan con el cliente (`lib/estimator_ai/data/`), como en la referencia. Duplica datos del servicio; se documenta que hay que recopiarlos si cambian. Alternativa descartada: un endpoint del servicio que sirva el corpus (aumentaría la superficie de la API sin evidencia en la referencia).

**Lint.** Se añade RuboCop omakase (la referencia lo usa). El código existente ya lo cumplía; solo hizo falta fijar `TargetRubyVersion`.

**Diferencias con la referencia.** (1) Un archivo por error y errores propios en vez de capturar Faraday en controllers. (2) Contratos con atributos desconocidos ignorados. (3) `TopChunk` usa `level` y `parent_chunk_id` explícitos del servicio en vez de deducirlos del `chunk_id`. (4) Los knobs usan nombres en minúsculas (`primary_model`). (5) Estados HTTP diferenciados (422/503/504/502) para el Lab.

## Risks / Trade-offs

- Dos bases PostgreSQL en el stack (una de la API y otra del cliente); es deliberado, a costa de un contenedor más.
- El corpus duplicado puede desincronizarse del servicio.
- La comparación es síncrona: una petición de Rails puede estar bloqueada hasta 10 minutos con estrategias de pago (un worker de Puma con 3 hilos); aceptable para una herramienta de laboratorio y documentado.
- Cambiar la raíz a un panel rompe marcadores al formulario; se mitiga porque `/estimations` y `/estimations/:id` siguen igual.
