# Spec Delta

## Purpose

Decidir con reglas ejecutables si un corpus encaja en CAG, en RAG o en un enfoque híbrido, sin conectar esa decisión al pipeline de estimación.

## ADDED Requirements

### Requirement: Perfiles y restricciones de viabilidad CAG
El sistema SHALL ofrecer en `app/ingestion/architecture.py` los tipos `CorpusProfile`, `ModelProfile` y `CAGViability` y la función `assess_cag_viability`. `CAGViability` SHALL evaluar cuatro restricciones —ventana de contexto, coste (con reutilización del prefijo), latencia y pérdida de información en el centro del contexto— y SHALL considerar viable CAG únicamente cuando las cuatro se cumplen, listando las que fallan en `failing_constraints()`. Los umbrales SHALL ser los de la referencia: 70 % de la ventana utilizable, 100 000 tokens para latencia y recuerdo del centro, y al menos 7 días de refresco para amortizar la caché del prefijo. (Referencia: `app/ingestion/architecture.py`.)

#### Scenario: Las cuatro restricciones se cumplen
- **WHEN** el corpus ocupa 50 000 tokens, se refresca cada 30 días y el modelo admite caché de prefijo con ventana de 128 000
- **THEN** `viable` es verdadero y `failing_constraints()` está vacío.

#### Scenario: Una restricción en rojo anula CAG
- **WHEN** el corpus ocupa 250 000 tokens
- **THEN** `viable` es falso y `failing_constraints()` incluye `context_window`, `latency` y `lost_in_the_middle`.

#### Scenario: Refresco demasiado frecuente
- **WHEN** el corpus cambia cada 3 días
- **THEN** la restricción `cost` falla aunque el modelo admita caché de prefijo.

### Requirement: Recomendación arquitectónica
El sistema SHALL ofrecer `recommend_architecture(corpus, model)` que devuelva `CAG`, `Hybrid` o `RAG` según volumen, frecuencia de actualización, necesidad de trazabilidad y control de acceso: `CAG` si los cuatro ejes lo permiten; `Hybrid` si el corpus cabe en la ventana y es estable pero requiere trazabilidad o control de acceso; `RAG` en el resto. La función SHALL ser una utilidad independiente: no modifica el flujo de estimación ni se usa como selector del pipeline. (Referencia: `app/ingestion/architecture.py`.)

#### Scenario: CAG
- **WHEN** el corpus es pequeño, estable y sin requisitos de trazabilidad ni de acceso
- **THEN** la recomendación es `CAG`.

#### Scenario: Híbrido
- **WHEN** el corpus cabe y es estable pero se exige trazabilidad
- **THEN** la recomendación es `Hybrid`.

#### Scenario: RAG
- **WHEN** el corpus no cabe en la ventana utilizable
- **THEN** la recomendación es `RAG`.

### Requirement: CLI de la recomendación
El módulo SHALL poder ejecutarse con `python -m app.ingestion.architecture` e imprimir el perfil evaluado, la viabilidad CAG con las restricciones en rojo y la recomendación para el escenario de ejemplo de la referencia (Proyecto 2 con `gpt-4o-mini`).

#### Scenario: Ejecución del CLI
- **WHEN** se ejecuta `python -m app.ingestion.architecture`
- **THEN** termina con código 0 e imprime `Viabilidad CAG: NO viable` y `Recomendación arquitectónica: RAG`.
