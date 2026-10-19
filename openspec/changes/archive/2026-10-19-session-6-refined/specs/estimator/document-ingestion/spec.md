# Spec Delta

## Purpose

Convertir los archivos de una fuente del catálogo en documentos con un contrato común, sin indexarlos ni conectarlos a la estimación.

## ADDED Requirements

### Requirement: Modelo documental
El sistema SHALL definir `Document` (`id`, `text`, `metadata`) y `DocumentMetadata` (`source_name`, `source_version`, `ingested_at`, `lineage`, `sensitivity_pii_flags`, `sensitivity_access_level`, `location`, `extra`) con Pydantic y campos extra prohibidos. El `id` SHALL ser estable y determinista entre ingestas, y `source_version` SHALL ser la versión del catálogo activa. (Referencia: `app/ingestion/documents/models.py`.)

#### Scenario: Metadatos completos
- **WHEN** un parser produce un documento
- **THEN** sus metadatos incluyen fuente, versión del catálogo, fecha de ingesta, linaje, sensibilidad, nivel de acceso y ubicación original.

#### Scenario: Campo extra
- **WHEN** se construye un `Document` con un campo no definido
- **THEN** la validación falla.

### Requirement: Cargador de sistema de archivos
El sistema SHALL ofrecer `FileSystemLoader(data_root)` cuyo `iter_blobs(location, formats)` resuelva la ubicación del catálogo respecto de una raíz configurable, recorra los archivos en orden, filtre por extensión y devuelva `LoadedBlob(relative_path, bytes_)`. Una ubicación inexistente SHALL producir `FileNotFoundError` explícito. (Referencia: `app/ingestion/loaders/filesystem.py`.)

#### Scenario: Recorrido ordenado y filtrado
- **WHEN** la carpeta contiene archivos `.json` y `.txt` y se piden los formatos `{json}`
- **THEN** solo se devuelven los `.json`, ordenados por ruta.

#### Scenario: Ubicación inexistente
- **WHEN** la ubicación no existe bajo la raíz
- **THEN** se lanza `FileNotFoundError` con la ubicación en el mensaje.

### Requirement: Contrato y registro de parsers
El sistema SHALL definir el protocolo `Parser` (`supported_formats`, `parse(blob, context)`) y `ParseContext` (fuente, versión del catálogo, fecha de ingesta). `ParserRegistry` SHALL registrar parsers por formato, rechazar con `ValueError` un formato ya registrado y lanzar `KeyError` para un formato sin parser. `default_registry()` SHALL incluir únicamente los parsers JSON y TXT: no se registran parsers de ingesta XLSX, DOCX ni PDF. (Referencia: `app/ingestion/parsers/protocol.py`, `registry.py`.)

#### Scenario: Registro duplicado
- **WHEN** se registran dos parsers para el formato `json`
- **THEN** el segundo registro lanza `ValueError`.

#### Scenario: Registro predeterminado
- **WHEN** se crea `default_registry()`
- **THEN** sus formatos son exactamente `{json, txt}`.

### Requirement: Parser de presupuestos JSON
`BudgetJsonParser` SHALL convertir cada presupuesto en un documento Markdown con las secciones cliente, total, fases y notas, conservando los importes, y SHALL asignar el identificador `"{fuente}:{budget_id}:{ruta_relativa}"` y los metadatos `budget_id`, `client_code`, `currency`, `total_amount` y `signed_at` en `extra`. (Referencia: `app/ingestion/parsers/budget_json.py`.)

#### Scenario: Presupuesto completo
- **WHEN** se parsea `BUDGET-2024-0001.json`
- **THEN** el texto contiene `# Presupuesto BUDGET-2024-0001`, el importe con su moneda y una línea por fase.

#### Scenario: Identificador determinista
- **WHEN** se parsea dos veces el mismo archivo
- **THEN** ambos documentos tienen el mismo `id`.

### Requirement: Parser de transcripciones TXT
`TranscriptTxtParser` SHALL detectar el formato con marcas de tiempo y hablantes (`[hh:mm:ss] Hablante: texto`) cuando al menos tres líneas coinciden con el patrón y, en ese modo, generar un documento por turno con `speaker`, `timestamp` y `format_mode=tagged`. En caso contrario (formato heredado) SHALL generar un documento por bloque separado por líneas vacías, sin inventar hablantes y con `format_mode=legacy`. (Referencia: `app/ingestion/parsers/transcript_txt.py`.)

#### Scenario: Formato con hablantes
- **WHEN** la transcripción tiene al menos tres líneas `[10:00:12] Laura: …`
- **THEN** se genera un documento por turno con su hablante y marca de tiempo.

#### Scenario: Formato heredado
- **WHEN** la transcripción no alcanza tres líneas con el patrón
- **THEN** se genera un documento por bloque, sin campo `speaker`.
