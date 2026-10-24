# estimator/chunking-strategies Specification

## Purpose
Definir la interfaz común de las estrategias de chunking y las ocho estrategias intercambiables.

## Requirements

### Requirement: Interfaz común de chunker
Toda estrategia SHALL implementar `Chunker` con `strategy_name` y `async chunk(budgets) -> list[Chunk]`. Tras cada ejecución SHALL dejar en `last_extra_api_calls` y `last_extra_cost_usd` las llamadas y el coste adicionales de la ingesta (cero si no llama a ninguna API). Todas SHALL contar tokens con el tokenizador `cl100k_base` y SHALL emitir un único evento `chunking_done` con `strategy`, `n_chunks`, `n_input_documents`, `extra_api_calls`, `extra_cost_usd` y `latency_ms`, sin texto de los documentos.

#### Scenario: Evento uniforme
- **WHEN** se ejecutan las ocho estrategias
- **THEN** cada una emite un evento `chunking_done` con exactamente los mismos campos.

#### Scenario: Estrategia gratuita
- **WHEN** se ejecuta una estrategia sin llamadas a API
- **THEN** `last_extra_api_calls` y `last_extra_cost_usd` valen cero.

### Requirement: Estrategias gratuitas
El sistema SHALL ofrecer `structural` (un chunk por componente con cabecera de contexto), `fixed_size` (ventana de 512 tokens con solapamiento de 80), `recursive` (separadores de grueso a fino, tamaño en tokens, solapamiento), `sentence_window` (una frase por chunk con `window_text` de ±2 frases en los metadatos) y `hierarchical` (un chunk padre por presupuesto y un hijo por componente con `parent_chunk_id` y `level`).

#### Scenario: Ventana de frases
- **WHEN** un componente tiene tres frases y la ventana es 1
- **THEN** se generan tres chunks de una frase y el primero lleva en `window_text` las dos primeras.

#### Scenario: Jerárquica
- **WHEN** se trocea un presupuesto de dos componentes
- **THEN** hay un padre con `level` «parent» y dos hijos con `level` «child» y `parent_chunk_id` igual al id del padre.

### Requirement: Estrategias de pago
El sistema SHALL ofrecer `semantic` (cortes donde la distancia coseno entre frases consecutivas supera el percentil 95 del documento; reporta una llamada de embeddings por lote y su coste), `propositional` (un LLM descompone cada componente en proposiciones atómicas; una llamada por componente; si falla conserva el componente entero) y `contextual_retrieval` (un LLM de Anthropic antepone a cada chunk un contexto que lo sitúa en su presupuesto; el documento padre se envía con `cache_control` y el coste incluye escritura y lectura de caché). Los modelos de las dos últimas SHALL venir de `propositional_chunker_model` y `contextual_chunker_model`.

#### Scenario: Fallo del LLM
- **WHEN** la llamada del proposicional falla para un componente
- **THEN** el componente se conserva como un único chunk y su coste es cero.

#### Scenario: Modelo configurado
- **WHEN** `propositional_chunker_model` vale `gpt-4o`
- **THEN** todas las llamadas del chunker usan `gpt-4o`.

#### Scenario: Caché del prompt
- **WHEN** se trocea un presupuesto con varios componentes con `contextual_retrieval`
- **THEN** todas las llamadas envían el documento con `cache_control` y la primera se completa antes de lanzar las demás.

### Requirement: Estrategias de pago solo bajo petición
`semantic`, `propositional` y `contextual_retrieval` SHALL ejecutarse únicamente cuando se piden por nombre. Una estrategia cuyo proveedor no tiene clave configurada, o cuyo modelo configurado no corresponde al proveedor, SHALL informarse como no disponible sin llamar a ninguna API.

#### Scenario: Clave ausente
- **WHEN** se pide `contextual_retrieval` sin `ANTHROPIC_API_KEY`
- **THEN** la construcción falla indicando la variable ausente, sin exponer ningún valor.

#### Scenario: Nombre desconocido
- **WHEN** se pide una estrategia que no existe
- **THEN** se rechaza como estrategia desconocida.
