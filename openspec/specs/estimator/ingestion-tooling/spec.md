# estimator/ingestion-tooling Specification

## Purpose
Aportar configuración, corpus de ejemplo y utilidades de comprobación reproducibles en Docker para las capacidades de ingesta.

## Requirements

### Requirement: Configuración de ingesta
`Settings` SHALL aceptar `CATALOG_PATH` (`data/catalog/catalog.yaml` por defecto), `INGESTION_DATA_ROOT` (`data/seed`), `PRESIDIO_SPACY_MODEL` (`es_core_news_md`), `PSEUDONYM_FAKER_LOCALE` (`es_ES`) y `PSEUDONYM_HASH_SALT` (`change-me-in-prod`, a sustituir fuera de desarrollo), documentadas en `.env.example`. (Referencia: `app/config.py`, `.env.example`.)

#### Scenario: Valores por defecto
- **WHEN** no se definen las variables
- **THEN** `Settings` usa los valores por defecto indicados.

#### Scenario: Sobrescritura por entorno
- **WHEN** se define `CATALOG_PATH`
- **THEN** `Settings.catalog_path` toma ese valor.

### Requirement: Corpus de ejemplo
El repositorio SHALL incluir en `estimador-cag/data/` el catálogo `catalog/catalog.yaml` con exactamente tres fuentes (presupuestos JSON incluidos, transcripciones TXT en revisión y tarifas XLSX excluidas) y el corpus `seed/` con seis presupuestos JSON, tres transcripciones TXT y el XLSX de tarifas, tal como en la referencia. (Referencia: `data/`.)

#### Scenario: Corpus completo
- **WHEN** se cuentan los archivos de `data/seed`
- **THEN** hay 6 `.json`, 3 `.txt` y 1 `.xlsx`.

#### Scenario: Catálogo válido
- **WHEN** se ejecuta `python -m app.ingestion.catalog.loader data/catalog/catalog.yaml`
- **THEN** informa de 3 fuentes y 1 incluida.

### Requirement: Demos y preflight
El repositorio SHALL incluir `scripts/demo_cleaning_s06.py` (limpieza y reporte de validación del corpus), `scripts/demo_pii_s06.py` (seudonimización de una transcripción con el modelo español) y `scripts/preflight_s06.py` (entorno, dependencias, modelo español, corpus, catálogo, `/health` y tablas/migraciones), ejecutables dentro de Docker; los fallos del preflight SHALL producir un código de salida distinto de 0. (Referencia: `scripts/`.)

#### Scenario: Demo de limpieza
- **WHEN** se ejecuta `demo_cleaning_s06.py`
- **THEN** informa de 6 ficheros leídos, 5 filas tras deduplicar y 1 registro descartado.

#### Scenario: Preflight correcto
- **WHEN** el stack está levantado y las migraciones aplicadas
- **THEN** todas las comprobaciones pasan y el código de salida es 0.

#### Scenario: Preflight con fallo
- **WHEN** falta una tabla de ingesta
- **THEN** la comprobación falla y el código de salida es distinto de 0.
