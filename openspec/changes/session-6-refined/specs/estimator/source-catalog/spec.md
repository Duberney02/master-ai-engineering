# Spec Delta

## Purpose

Mantener un catálogo versionado y auditable de las fuentes de datos, con decisiones explícitas de inclusión, y un inspector que aporte solo hechos observables.

## ADDED Requirements

### Requirement: Modelos del catálogo
El sistema SHALL definir con Pydantic `DataCatalog`, `CatalogSource`, `QualityScore`, `Sensitivity` y `CatalogDecision` (`include`, `review`, `exclude`) en `app/ingestion/catalog/models.py`. Cada fuente SHALL declarar nombre, descripción, ubicación, formato, responsables, volumen estimado, frecuencia de actualización declarada y observada, linaje y fecha de auditoría. El nombre SHALL ser único en el catálogo y estar en minúsculas con formato snake_case. `QualityScore` SHALL puntuar completitud, consistencia, actualidad y fiabilidad entre 1 y 5. `Sensitivity` SHALL declarar si hay PII, los tipos de entidad y el nivel de acceso (`public`, `internal`, `confidential`). Las decisiones `review` y `exclude` SHALL exigir una justificación no vacía. (Referencia: `app/ingestion/catalog/models.py`.)

#### Scenario: Catálogo válido
- **WHEN** se valida un catálogo con fuentes bien formadas
- **THEN** `DataCatalog` se construye y `find(nombre)` devuelve la fuente.

#### Scenario: Nombre inválido o duplicado
- **WHEN** un nombre no es snake_case en minúsculas o aparece dos veces
- **THEN** la validación falla.

#### Scenario: Puntuación fuera de rango
- **WHEN** una puntuación de calidad es 0 o 6
- **THEN** la validación falla.

#### Scenario: Decisión sin justificación
- **WHEN** una fuente con decisión `review` o `exclude` no tiene `decision_reason`
- **THEN** la validación falla; con `include` no se exige justificación.

#### Scenario: Fuentes incluidas
- **WHEN** se llama a `included_sources()`
- **THEN** devuelve únicamente las fuentes con decisión `include`.

### Requirement: Carga segura y CLI de validación
El sistema SHALL cargar el YAML con `yaml.safe_load` y validarlo contra `DataCatalog` mediante `load_catalog(path)`. `python -m app.ingestion.catalog.loader <ruta>` SHALL imprimir la versión, el total de fuentes y las incluidas. (Referencia: `app/ingestion/catalog/loader.py`.)

#### Scenario: Carga del catálogo de ejemplo
- **WHEN** se carga `data/catalog/catalog.yaml`
- **THEN** contiene exactamente tres fuentes: `presupuestos_json` (include), `transcripciones_txt` (review) y `rate_card_xlsx` (exclude).

#### Scenario: Campo desconocido
- **WHEN** el YAML contiene un campo no definido en los modelos
- **THEN** la validación falla.

### Requirement: Inspector de carpetas
El sistema SHALL ofrecer `python -m app.ingestion.catalog.inspect <carpeta>` que informe, por subcarpeta y por los archivos sueltos de la raíz, el número de archivos, el tamaño en MB, la última modificación y los formatos detectados. El inspector SHALL producir solo datos observables: no modifica el catálogo ni asigna decisiones o puntuaciones. (Referencia: `app/ingestion/catalog/inspect.py`.)

#### Scenario: Inspección del corpus de ejemplo
- **WHEN** se inspecciona `data/seed`
- **THEN** se informa de `budgets` (6 archivos, `json`), `transcripts` (3 archivos, `txt`) y los archivos de la raíz (`xlsx`).

#### Scenario: Carpeta inexistente
- **WHEN** la carpeta no existe
- **THEN** el CLI termina con código distinto de 0 sin modificar ningún archivo.
