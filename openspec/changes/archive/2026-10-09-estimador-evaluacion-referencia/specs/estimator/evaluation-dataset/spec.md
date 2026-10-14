# Spec Delta

## Purpose

Disponer de casos de referencia versionados con expectativas verificables para medir el estimador.

## ADDED Requirements

### Requirement: Dataset de referencia versionado
El sistema SHALL incluir un dataset de referencia versionado con 16 casos, dos por cada categoría: SaaS, aplicaciones móviles, herramientas internas, pipelines de datos, entradas vagas, entradas adversariales, restricciones regulatorias y plazos exigentes. Cada caso SHALL tener un identificador único, categoría, tipo de proyecto, transcripción y expectativas. El dataset SHALL validarse al cargarse con un esquema estricto.

#### Scenario: Cobertura
- **WHEN** se carga el dataset
- **THEN** contiene 16 casos con identificadores únicos y exactamente dos de cada una de las ocho categorías.

#### Scenario: Caso mal formado
- **WHEN** un caso tiene un campo desconocido, un rango invertido o una transcripción demasiado corta
- **THEN** la carga falla con un error explícito.

### Requirement: Expectativas por caso
Cada caso SHALL definir, cuando corresponda, requisitos o tecnologías esperados (con alternativas aceptables) y rangos de número de fases, coste total y duración total. Los casos sin cifras SHALL declarar si esperan un resultado fuera de alcance o un rechazo por guardrails.

#### Scenario: Casos con cifras
- **WHEN** se inspeccionan los casos de las categorías SaaS, móvil, herramienta interna, pipeline, regulatorio y plazo exigente
- **THEN** cada uno define al menos un requisito o tecnología esperado y rangos de coste y duración.

#### Scenario: Casos vagos y adversariales
- **WHEN** se inspeccionan los casos de entradas vagas
- **THEN** esperan un resultado fuera de alcance, y al menos un caso adversarial espera el rechazo por inyección de instrucciones.
