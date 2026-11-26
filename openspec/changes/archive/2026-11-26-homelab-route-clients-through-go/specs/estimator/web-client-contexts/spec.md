# Spec Delta

## MODIFIED Requirements

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

### Requirement: Navegación por contexto
React SHALL ofrecer navegación accesible entre nueva estimación, historial y las capacidades administrativas según autorización aplicada por Go. SHALL conservar inicio y enlaces a nueva estimación, historial, RAG con acceso al Lab y Ajustes, con las convenciones visuales actuales de React. El panel inicial SHALL presentar los contextos sin depender de consultas de IA o PostgreSQL para renderizarse. SHALL identificar la vista activa con `aria-current="page"` y mantener la navegación disponible si falla el indicador del modelo.

#### Scenario: Sección activa
- **WHEN** un operador autorizado abre Chunking Lab
- **THEN** la navegación React identifica su sección activa

#### Scenario: Layout sin servicio
- **WHEN** el servicio de IA no responde
- **THEN** se conservan la navegación y la vista sin el indicador del modelo

## ADDED Requirements

### Requirement: Estados de navegación administrativa
React SHALL representar la denegación administrativa sin mostrar datos de Ajustes o Lab y SHALL conservar el acceso a las demás vistas.

#### Scenario: Acceso directo sin permiso
- **WHEN** se abre mediante enlace directo una vista administrativa en integración
- **THEN** React presenta un estado de acceso restringido sin datos administrativos y permite regresar a estimaciones
