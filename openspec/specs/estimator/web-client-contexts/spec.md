# estimator/web-client-contexts Specification

## Purpose
Organizar el backend Go por contextos independientes con una capa HTTP única, errores tipados y saneados y navegación por contexto en React.

## Requirements

### Requirement: Capa HTTP única
Solo el paquete de la capa HTTP del servicio web (`internal/estimatorai`) SHALL hablar HTTP con el servicio de IA. Un cliente base SHALL encapsular la conexión, el mapeo de respuestas a errores y los mensajes, y cada contexto (estimaciones, sesiones, embeddings, configuración) SHALL tener su cliente. Ningún handler, plantilla ni paquete de contexto SHALL construir peticiones HTTP hacia la API directamente.

#### Scenario: Cliente por contexto
- **WHEN** un handler necesita comparar chunkers
- **THEN** usa el cliente de embeddings y no construye peticiones HTTP.

#### Scenario: Sin cliente monolítico
- **WHEN** se inspecciona el paquete de la capa HTTP
- **THEN** no existe un cliente único que mezcle todos los contextos.

### Requirement: Errores tipados y saneados
La capa HTTP SHALL traducir todo fallo a un error tipado con un mensaje en español apto para el usuario: `ConnectionFailed`, `RequestTimeout` (un caso de `ConnectionFailed`), `InvalidRequest`, `GuardrailViolation`, `NotFound`, `SessionExpired` (un caso de `NotFound`), `ServiceUnavailable`, `ServerError` e `InvalidResponse`. Los mensajes SHALL NOT contener cuerpos crudos, trazas, claves ni la URL interna del servicio.

#### Scenario: Estados HTTP
- **WHEN** el servicio responde 404, 422, 503 o 500
- **THEN** se produce respectivamente `NotFound`, `InvalidRequest`, `ServiceUnavailable` y `ServerError`.

#### Scenario: Cuerpo crudo
- **WHEN** un 500 trae una traza con una clave
- **THEN** el mensaje es el genérico y no contiene ninguno de esos datos.

#### Scenario: Detalle de la API
- **WHEN** un cliente de configuración o embeddings recibe un 400, 422 o 503 con `detail` de texto
- **THEN** se traduce a un mensaje seguro de catálogo o un detalle específicamente permitido y se descarta cualquier contenido no confiable.

### Requirement: Contratos por contexto
Cada contexto SHALL tener tipos de contrato que reflejen los schemas del servicio (estadísticas, chunks recuperados, resultados por consulta, respuesta de la comparación, configuración de modelo y catálogo). Los atributos desconocidos que añada el servicio SHALL ignorarse. Los contextos SHALL NOT importarse entre sí.

#### Scenario: Atributo nuevo del servicio
- **WHEN** la respuesta incluye un campo que el contrato no conoce
- **THEN** el contrato se construye sin error.

### Requirement: Navegación por contexto
React SHALL ofrecer navegación accesible entre nueva estimación, historial y las capacidades administrativas según autorización aplicada por Go. SHALL conservar inicio y enlaces a nueva estimación, historial, RAG con acceso al Lab y Ajustes, con las convenciones visuales actuales de React. El panel inicial SHALL presentar los contextos sin depender de consultas de IA o PostgreSQL para renderizarse. SHALL identificar la vista activa con `aria-current="page"` y mantener la navegación disponible si falla el indicador del modelo.

#### Scenario: Sección activa
- **WHEN** un operador autorizado abre Chunking Lab
- **THEN** la navegación React identifica su sección activa

#### Scenario: Layout sin servicio
- **WHEN** el servicio de IA no responde
- **THEN** se conservan la navegación y la vista sin el indicador del modelo

### Requirement: Entorno de pruebas en contenedor
Las pruebas y el lint del servicio web SHALL ejecutarse en Docker con una base de datos efímera (`web-test`, `web-lint`) y nunca llamar a la API real.

#### Scenario: Ejecución
- **WHEN** se ejecuta `docker compose -f docker-compose.verify.yml run --rm web-test`
- **THEN** se prepara la base de datos y se ejecutan las pruebas con la API simulada, y todo acceso de red no simulado falla.

### Requirement: Estados de navegación administrativa
React SHALL representar la denegación administrativa sin mostrar datos de Ajustes o Lab y SHALL conservar el acceso a las demás vistas.

#### Scenario: Acceso directo sin permiso
- **WHEN** se abre mediante enlace directo una vista administrativa en integración
- **THEN** React presenta un estado de acceso restringido sin datos administrativos y permite regresar a estimaciones
