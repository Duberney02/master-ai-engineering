# Spec Delta

## Purpose

Reutilizar estimaciones de solicitudes semánticamente equivalentes sin mezclar versión de prompt, tipo de proyecto, nivel de detalle ni formato de salida.

## ADDED Requirements

### Requirement: Búsqueda semántica por similitud coseno
El sistema SHALL calcular un embedding del texto de la solicitud (descripción y proyectos de referencia) y buscarlo con `redisvl` por similitud coseno. SHALL devolver un acierto solo si la similitud es mayor o igual que `SEMANTIC_CACHE_THRESHOLD` (por defecto 0,92). La respuesta SHALL indicar `cached=true`.

#### Scenario: Acierto por similitud
- **WHEN** existe una entrada con similitud ≥ umbral y los mismos atributos
- **THEN** se devuelve su resultado con `cached=true` sin llamar al proveedor de generación.

#### Scenario: Similitud insuficiente
- **WHEN** la entrada más cercana está por debajo del umbral
- **THEN** se genera una estimación nueva y se almacena.

### Requirement: Aislamiento por atributos
Cada entrada SHALL almacenarse con `prompt_version`, `project_type`, `detail_level` y `output_format`, y cada consulta SHALL filtrar por igualdad de los cuatro. El índice SHALL incluir modelo y dimensiones de embedding en su nombre.

#### Scenario: Atributo distinto
- **WHEN** existe una entrada idéntica en texto pero con otro `detail_level`
- **THEN** no se devuelve como acierto.

### Requirement: TTL y modo log_only
La caché semántica SHALL aplicar `SEMANTIC_CACHE_TTL` (por defecto 86400 s) a las entradas. Con `SEMANTIC_CACHE_MODE=log_only` SHALL consultar y registrar el acierto potencial con su similitud, pero tratar la consulta como fallo y seguir almacenando. El modo `active` SHALL devolver aciertos y el modo `off` SHALL desactivarla.

#### Scenario: log_only
- **WHEN** hay una entrada por encima del umbral y el modo es `log_only`
- **THEN** se registra el acierto potencial, se genera una estimación nueva y `cached=false`.

### Requirement: Tolerancia a fallos
Cualquier error de Redis o de embeddings SHALL registrarse y tratarse como fallo de caché sin afectar a la respuesta. Sin `REDIS_URL` o sin clave de embeddings la caché semántica SHALL quedar desactivada.

#### Scenario: Embeddings caídos
- **WHEN** el servicio de embeddings falla
- **THEN** la solicitud se resuelve generando la estimación.
