# Design

## Context

Parte del estado que dejan las Sesiones 09 y 10 portadas (estimación fundamentada, multi-índice, horas por tarea). En
`estimator/` la Sesión 11 vive en `generation/rag/quality/`, `validation.py`, `index_service.py`,
`api/routers/corpus_index.py`, la migración `0005_session11_hnsw_multi_index` y los scripts `*_s11.py`. Se porta su
comportamiento con las convenciones de `estimador-cag`.

## Goals / Non-Goals

**Goals:**
- Calidad verificable de la generación (citas por línea, *gate* semántico, aumentación, rangos) y corpus ampliable.
- Evaluación RAGAS reproducible con *gate* de regresión.

**Non-Goals:**
- Re-embeber el corpus o cambiar de modelo de embeddings (migración *blue-green*).
- Ejecutar RAGAS dentro de `pytest` o en CI con claves reales.

## Decisions

1. **Funciones puras + conductor.** Ancla numérica, combinación por línea (`gate_line`), compresión, reordenación y
   rango determinista son funciones puras probadas sin LLM; el juez y la redacción del motivo usan
   `generate_structured` con modelos resolubles en runtime. Igual reparto que `estimator/`.
2. **Regla asimétrica del gate.** Solo penaliza la sobreestimación respecto al ancla (una línea puede ser una fracción
   del componente histórico); el juez se ejecuta una vez por estimación, no por línea, para acotar coste.
3. **Expansión del corpus con BackgroundTasks asíncronas** sobre el `DocumentStore` existente (sesión async) y la
   tabla de jobs de la ingesta. `estimator/` mezcla una sesión síncrona para el job; aquí se usa el repositorio de
   jobs asíncrono si existe o se envuelve en `asyncio.to_thread`, sin bloquear el event loop.
4. **HNSW con `CREATE INDEX CONCURRENTLY` en `autocommit_block()`**, como la migración `0003_hnsw_indexes` existente,
   solo para las tablas nuevas (`chunks` ya tiene su índice).
5. **RAGAS aislado.** `estimator/` separa la recolección de muestras (`eval_ragas_s11.py --collect-only`) de la
   puntuación (`score_ragas_s11.py`, que solo importa `ragas`) por conflictos de dependencias. Se replica: `ragas` y
   `datasets` en el grupo `dev` y, si chocan con el lock, el puntuador se ejecuta en un servicio de verificación
   propio. Las pruebas cubren solo la lógica del *gate* (umbrales, código de salida) con métricas falsas.
6. **Contrato aditivo de la estimación.** `sources` por línea pasa a objetos de cita; como las Sesiones 09–10 aún no
   tienen consumidores externos de ese campo, se documenta en el README y en el changelog del cambio.

## Risks / Trade-offs

- [Coste y latencia del juez] → conmutable en runtime (`hallucination_gate_enabled`) y `use_judge=false` en la etapa.
- [Compresión que elimina contexto útil sin cifras] → conmutable por separado (`augmentation_compress`).
- [Conflictos de `ragas` con el lock] → puntuador aislado (decisión 5).

## Migration Plan

`alembic upgrade head` crea los índices HNSW nuevos; `downgrade` los elimina con `DROP INDEX CONCURRENTLY IF EXISTS`.
