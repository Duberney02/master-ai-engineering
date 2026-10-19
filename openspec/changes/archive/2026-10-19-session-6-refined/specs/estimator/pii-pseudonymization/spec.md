# Spec Delta

## Purpose

Detectar datos personales en español y sustituirlos de forma consistente sin guardar el valor original, como utilidad independiente de los guardrails y del pipeline.

## ADDED Requirements

### Requirement: Analizador Presidio en español
El sistema SHALL ofrecer `build_analyzer()` que devuelva un `AnalyzerEngine` de Presidio configurado para español con spaCy y el modelo indicado por `PRESIDIO_SPACY_MODEL` (`es_core_news_md` por defecto), reutilizado como singleton, con los reconocedores `BudgetIdRecognizer` (`BUDGET-YYYY-NNNN`) y `ClientCodeRecognizer` (`CLI-NNNN`) registrados. (Referencia: `app/ingestion/pii/analyzer.py`, `recognizers.py`.)

#### Scenario: Reconocedores del dominio
- **WHEN** el texto contiene `BUDGET-2024-0001` y `CLI-0042`
- **THEN** se detectan como `BUDGET_ID` y `CLIENT_CODE` con puntuación al menos 0,9.

#### Scenario: Formas no válidas
- **WHEN** el texto contiene `CLI-42` o `BUDGET-2024`
- **THEN** no se detecta ninguna entidad de dominio.

#### Scenario: Nombres hispanos
- **WHEN** se analiza «Laura Fernández firmó el contrato» con el analizador real
- **THEN** se detecta una entidad `PERSON`.

### Requirement: Seudonimización consistente
`ConsistentPseudonymizer` SHALL sustituir personas, correos, ubicaciones y los identificadores del dominio calculando el HMAC-SHA256 del valor original con la sal configurada (`PSEUDONYM_HASH_SALT`), obteniendo el seudónimo del store mediante búsqueda o creación consistente y generándolo con Faker según el locale configurado (`PSEUDONYM_FAKER_LOCALE`). Las sustituciones SHALL aplicarse del final del texto hacia el principio y el resultado SHALL contener el texto seudonimizado y la relación de sustituciones aplicadas (tipo, hash, seudónimo y posición). El mismo valor SHALL recibir el mismo seudónimo entre llamadas y valores distintos seudónimos distintos. (Referencia: `app/ingestion/pii/pseudonymizer.py`.)

#### Scenario: Consistencia entre textos
- **WHEN** «Laura Fernández» aparece en dos textos distintos
- **THEN** recibe el mismo seudónimo en ambos y el original no figura en el resultado.

#### Scenario: Valores distintos
- **WHEN** aparecen dos personas distintas
- **THEN** reciben seudónimos distintos.

#### Scenario: Identificador de presupuesto
- **WHEN** se sustituye `BUDGET-2024-0001`
- **THEN** el seudónimo conserva la forma `BUDGET-…` y el original desaparece.

#### Scenario: Sin PII
- **WHEN** el texto no contiene entidades
- **THEN** se devuelve sin cambios y sin sustituciones.

### Requirement: Stores intercambiables y borrado de un mapping
El sistema SHALL ofrecer `MappingStore` con `lookup_or_create` y `forget`, y las implementaciones `InMemoryMappingStore` (pruebas) y `PostgresMappingStore`. La persistencia SHALL guardar tipo de entidad, hash y seudónimo, nunca el valor original en texto plano, y SHALL conservar la unicidad de `(entity_type, original_hash)` y la convergencia ante inserciones concurrentes. `forget` SHALL eliminar únicamente el mapping y devolver si existía. La seudonimización no es reversible: no existe desseudonimización, endpoint de borrado ni eliminación del corpus. (Referencia: `app/ingestion/pii/mapping_store.py`, `app/persistence/repositories/mappings.py`.)

#### Scenario: Creación única
- **WHEN** se consulta dos veces el mismo `(entity_type, hash)`
- **THEN** el factory de seudónimos se invoca una sola vez y ambas devuelven el mismo seudónimo.

#### Scenario: Olvidar un mapping
- **WHEN** se llama a `forget` para un mapping existente
- **THEN** devuelve verdadero y la siguiente consulta crea un seudónimo nuevo.

#### Scenario: Sin valor original en la base
- **WHEN** se persiste un mapping en PostgreSQL
- **THEN** la fila contiene el hash y el seudónimo y ninguna columna con el valor original.

### Requirement: Independencia de los guardrails
La seudonimización SHALL ser una utilidad independiente: los guardrails de entrada existentes que rechazan ciertos datos personales conservan su comportamiento y no invocan el seudonimizador.

#### Scenario: Guardrails intactos
- **WHEN** se ejecutan las pruebas de guardrails existentes
- **THEN** pasan sin cambios.
