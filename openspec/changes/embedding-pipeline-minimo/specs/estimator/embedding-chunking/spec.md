# Spec Delta

## Purpose

Definir los contratos Pydantic del pipeline y el chunking estructural de presupuestos históricos.

## ADDED Requirements

### Requirement: Contratos Pydantic del pipeline
El módulo `app/embedding_pipeline/schemas.py` SHALL definir, con Pydantic v2, `BudgetComponent`, `Budget`, `Chunk` (`chunk_id`, `text`, `metadata`, `token_count`), `EmbeddedChunk` (extiende `Chunk` con `embedding: list[float]`), `IngestRequest` (`budgets: list[Budget]`) e `IngestResponse` (`chunks: list[EmbeddedChunk]`, `stats: dict`). `Budget` SHALL incluir `budget_id`, `client_metadata`, `project_summary`, `main_technology`, `year`, `total_estimated_hours` y `components`. Los campos con categorías de valores no exhaustivamente conocidos (`complexity`, `sector`) SHALL ser cadenas y no `Literal`.

#### Scenario: Presupuesto válido
- **WHEN** se valida un presupuesto de `data/budgets_sample.json`
- **THEN** se obtiene un `Budget` con todos sus componentes.

#### Scenario: Entrada inválida
- **WHEN** un componente tiene horas negativas, un `component_id` vacío o repetido dentro del presupuesto, o dos presupuestos comparten `budget_id`
- **THEN** la validación falla con `ValidationError`.

### Requirement: Un chunk por componente con contexto
`JSONStructuralChunker.chunk(budgets)` SHALL devolver exactamente un `Chunk` por cada componente de cada presupuesto, en el orden de entrada. El texto SHALL seguir la plantilla `[Project: …]`, `[Client sector: … | Year: … | Main tech: …]`, línea en blanco y `Component:`, `Description:`, `Tech stack:` (separado por `, `), `Complexity:`, `Estimated hours:`. No SHALL haber overlap ni división de descripciones largas.

#### Scenario: Conteo y texto
- **WHEN** se trocean los 15 presupuestos de ejemplo
- **THEN** el número de chunks es igual a la suma de componentes y el texto del primero coincide con la plantilla.

### Requirement: Metadatos e identificadores trazables
Cada chunk SHALL llevar en `metadata` al menos `budget_id`, `component_id`, `client_sector`, `main_technology`, `year`, `complexity` y `estimated_hours`, sin concatenarlos al texto. El `chunk_id` SHALL tener el formato `{budget_id}::{component_id}`.

#### Scenario: Metadatos fuera del texto
- **WHEN** se obtiene el chunk `BUD-2024-001::AUTH-001`
- **THEN** `metadata["client_sector"]` es `finance` y el texto no contiene `budget_id` ni `component_id`.

### Requirement: Conteo de tokens
`token_count` SHALL calcularse sobre el texto del chunk con `tiktoken.encoding_for_model("text-embedding-3-small")`.

#### Scenario: Tokens positivos y reproducibles
- **WHEN** se trocea dos veces el mismo presupuesto
- **THEN** `token_count` es mayor que cero y coincide con la longitud de `encode(text)`.
