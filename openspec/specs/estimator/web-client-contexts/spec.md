# estimator/web-client-contexts Specification

## Purpose
Organizar el cliente Rails por contextos con una capa HTTP única, errores tipados, contratos que reflejen los schemas del servicio y navegación por contexto.

## Requirements

### Requirement: Capa HTTP única
Solo la capa `app/services/estimator_ai/` SHALL hablar HTTP con el servicio. Un cliente base SHALL encapsular la conexión, el mapeo de respuestas a errores y los mensajes, y cada contexto (estimaciones, sesiones, embeddings, configuración) SHALL tener su cliente. Ningún controller, helper ni modelo SHALL usar Faraday directamente.

#### Scenario: Cliente por contexto
- **WHEN** un controller necesita comparar chunkers
- **THEN** usa `EstimatorAi::EmbeddingsClient` y no construye peticiones HTTP.

#### Scenario: Sin cliente monolítico
- **WHEN** se carga la aplicación
- **THEN** no existe `EstimatorApi`.

### Requirement: Errores tipados y saneados
La capa HTTP SHALL traducir todo fallo a una subclase de `EstimatorAi::Error` con un mensaje en español apto para el usuario: `ConnectionFailed`, `RequestTimeout`, `InvalidRequest`, `GuardrailViolation`, `NotFound`, `SessionExpired`, `ServiceUnavailable`, `ServerError` e `InvalidResponse`. Los mensajes SHALL NOT contener cuerpos crudos, trazas, claves ni la URL interna del servicio.

#### Scenario: Estados HTTP
- **WHEN** el servicio responde 404, 422, 503 o 500
- **THEN** se lanzan respectivamente `NotFound`, `InvalidRequest`, `ServiceUnavailable` y `ServerError`.

#### Scenario: Cuerpo crudo
- **WHEN** un 500 trae una traza con una clave
- **THEN** el mensaje es el genérico y no contiene ninguno de esos datos.

#### Scenario: Detalle de la API
- **WHEN** un cliente de configuración o embeddings recibe un 400, 422 o 503 con `detail` de texto
- **THEN** el error lleva ese detalle como mensaje.

### Requirement: Contratos por contexto
Cada contexto SHALL tener objetos de contrato que reflejen los schemas del servicio (`Rag::Stats`, `Rag::TopChunk`, `Rag::QueryResult`, `Rag::ComparisonResponse`, `Ai::ModelConfig`, `Ai::Catalog`). Los atributos desconocidos que añada el servicio SHALL ignorarse. Los contextos SHALL NOT importarse entre sí.

#### Scenario: Atributo nuevo del servicio
- **WHEN** la respuesta incluye un campo que el contrato no conoce
- **THEN** el contrato se construye sin error.

### Requirement: Navegación por contexto
La raíz `/` SHALL mostrar un panel de inicio con una tarjeta por contexto (estimaciones, Chunking Lab, Ajustes) sin consultar la API ni la base de datos. La barra de navegación SHALL aparecer en todas las pantallas y marcar la sección activa con `aria-current="page"`. El formulario de estimación SHALL estar en `/estimations/new`.

#### Scenario: Sección activa
- **WHEN** se abre el Chunking Lab
- **THEN** solo el enlace «Chunking Lab» está marcado como activo.

#### Scenario: Layout sin servicio
- **WHEN** el servicio no responde
- **THEN** cualquier página se renderiza igualmente, sin el indicador del modelo primario.

### Requirement: Entorno de pruebas en contenedor
Las pruebas y el lint del cliente SHALL ejecutarse en Docker con una base de datos efímera (`web-test`, `web-lint`) y nunca llamar a la API real.

#### Scenario: Ejecución
- **WHEN** se ejecuta `docker compose -f docker-compose.verify.yml run --rm web-test`
- **THEN** se preparan la base de datos y las pruebas, y todo acceso de red no simulado falla.
