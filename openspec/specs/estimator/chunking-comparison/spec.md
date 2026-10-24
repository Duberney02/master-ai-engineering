# estimator/chunking-comparison Specification

## Purpose
Comparar estrategias de chunking con estadísticas de corpus y recuperación top-k, y exponerlo por HTTP sin persistencia.

## Requirements

### Requirement: Estadísticas por estrategia
El comparador SHALL calcular, por estrategia, el número de chunks, la distribución de tokens (mínimo, p50, p95 y máximo), el número de chunks huérfanos (menos de 20 tokens) y obesos (más de 800 tokens), el coste y las llamadas extra de la ingesta y el tiempo de chunking.

#### Scenario: Chunks degenerados
- **WHEN** una estrategia produce chunks de 5, 10, 30 y 900 tokens
- **THEN** se informan 2 huérfanos, 1 obeso, mínimo 5 y máximo 900.

### Requirement: Top-k por similitud coseno
Dadas consultas, el comparador SHALL embeber las consultas y los chunks de cada estrategia y devolver los `top_k` chunks de mayor similitud coseno con su puntuación, una vista previa del texto y, si existen, `level` y `parent_chunk_id`. Sin consultas SHALL no llamar al embedder.

#### Scenario: Orden y padre
- **WHEN** se consulta la estrategia jerárquica con `top_k` 2
- **THEN** los resultados vienen ordenados por coseno descendente y cada hijo incluye el id de su padre.

### Requirement: Chunking memoizado
El comparador SHALL trocear cada estrategia una sola vez por conjunto de presupuestos y reutilizar el resultado (y los embeddings de los chunks) entre estadísticas y consultas. Cambiar de embedder SHALL conservar el chunking ya calculado.

#### Scenario: Estadísticas y consultas
- **WHEN** se piden estadísticas y después dos rondas de consultas sobre los mismos presupuestos
- **THEN** cada chunker se ejecuta una vez y los chunks se embeben una vez.

### Requirement: POST /embeddings/compare
El servicio SHALL exponer `POST /embeddings/compare` con `budgets`, `queries`, `strategies` y `top_k` (1 a 10, por defecto 3) y responder `stats_per_strategy` y `queries_per_strategy`, sin persistir nada. Sin `strategies` SHALL ejecutar solo las estrategias gratuitas. SHALL responder `400` ante una estrategia desconocida, `503` si falta la clave de una estrategia pedida o `OPENAI_API_KEY` cuando hay consultas o se pide `semantic`, `500` con mensaje genérico ante un fallo de cómputo y `422` ante entrada inválida. Los mensajes SHALL nombrar la variable ausente pero nunca contener claves ni el texto de la excepción original.

#### Scenario: Estrategias por defecto
- **WHEN** se envía una comparación sin `strategies`
- **THEN** la respuesta contiene exactamente las cinco estrategias gratuitas.

#### Scenario: Estrategia desconocida
- **WHEN** se pide la estrategia `magic`
- **THEN** la respuesta es 400 y nombra la estrategia.

#### Scenario: Clave ausente
- **WHEN** se pide `contextual_retrieval` sin `ANTHROPIC_API_KEY`
- **THEN** la respuesta es 503 y el mensaje menciona `ANTHROPIC_API_KEY`.

#### Scenario: Fallo de cómputo
- **WHEN** el embedder lanza un error con un texto interno
- **THEN** la respuesta es 500 con un mensaje genérico que no contiene ese texto.

### Requirement: Corpus y consultas de prueba
El repositorio SHALL incluir `data/test_queries.json` con una lista fija de consultas y `data/budgets_stress_cases.json` con presupuestos que provoquen chunks obesos, huérfanos y descripciones de varias frases, válidos contra el esquema `Budget`.

#### Scenario: Casos límite
- **WHEN** se trocea el corpus con la estrategia estructural y con `sentence_window`
- **THEN** aparece al menos un chunk obeso en la primera y chunks huérfanos en la segunda.
