# Sesión 08 — Barrido de `hnsw.ef_search` y decisión adoptada

Entregable posterior al directo. Todas las cifras son de **mi** ejecución en Docker (PostgreSQL 17 + pgvector, con los
flags de tuning del Compose raíz) sobre el corpus real de 15 presupuestos (52 chunks) más **30 000 chunks sintéticos**
(`insert_synthetic_chunks_s08.py 30000`: mezclas convexas de embeddings reales con ruido leve, ver nota al final).
Las 5 queries son las de `query_examples.py`; cada medida es la media de 1 calentamiento + 2 repeticiones por query.

## Valor adoptado

**`HNSW_EF_SEARCH=40`** (default de `Settings.hnsw_ef_search`, aplicado con `SET LOCAL hnsw.ef_search = 40` en cada
búsqueda).

## Tabla del barrido (`sweep_ef_search_s08.py`)

Verdad de fondo: top-10 exacto con `SET LOCAL enable_indexscan = off`. Recall@5 = |top5 índice ∩ top5 real| / 5.
La medición fuerza el índice (`enable_seqscan = off`); "Plan natural" es lo que el planner elige por sí solo.

| ef_search | Latencia media (ms) | recall@5 | Plan natural | ★ |
|----------:|--------------------:|---------:|--------------|---|
| 10        | 2.67                | 0.76     | Index        |   |
| 20        | 2.81                | 0.76     | Index        |   |
| **40**    | **2.88**            | **1.00** | Index        | ★ |
| 80        | 3.38                | 1.00     | **Seq Scan** |   |
| 120       | 3.40                | 1.00     | **Seq Scan** |   |
| 200       | 4.21                | 1.00     | Index        |   |

★ = menor `ef_search` con recall ≥ mejor − 0.005 (aquí 0.995).

## Decisión razonada: recall ganado frente a latencia pagada

- **De 20 a 40**: +0.24 de recall@5 (de 0.76 a 1.00) por **+0.07 ms** (≈ +2.5 %). Es la mejora que compensa.
- **De 40 a 200**: recall idéntico (1.00) y la latencia sube de 2.88 a 4.21 ms (**+46 %**). Todo ese coste es puro
  desperdicio con este corpus.
- **Los valores 80 y 120 son una trampa operativa**: el coste que estima pgvector para el índice depende de
  `ef_search` y, en una tabla de ~30 000 filas, a esos valores el planner prefiere *Seq Scan + Sort* (≈ 770 ms frente
  a ≈ 3 ms). Con `ef_search = 40` el planner usa el índice de forma estable. En tablas más grandes el Seq Scan encarece
  y el índice gana siempre; aun así, tras cambiar `HNSW_EF_SEARCH` conviene comprobar con
  `EXPLAIN` (`sql_s08/02_test_antipatron.sql`, `04_monitoring_queries.sql`) que `idx_scan` sigue subiendo.
- Resultado: `40` es el mínimo que alcanza el recall máximo **y** el que evita el cambio de plan. Coincide con el
  default de pgvector, pero ahora está medido y fijado explícitamente en la configuración.

## Latencia de la consulta SQL: sin índice frente a con índice

| Escenario (30 052 chunks) | Media de las 5 queries | Plan |
|---------------------------|-----------------------:|------|
| Sin índice (migración `0002`) | **766.9 ms** | Seq Scan |
| Con HNSW halfvec (`0003`)     | **3.71 ms**  | Index Scan using `chunks_embedding_halfvec_idx` |

≈ 200× menos latencia. (`alembic downgrade 0002` → medir → `alembic upgrade head` → medir.)

## Tamaños: `vector` frente a `halfvec` (`report_index_sizes_s08.py`)

| Índice | Tipo | Tamaño |
|--------|------|-------:|
| `chunks_embedding_idx` (`vector_cosine_ops`) | hnsw | 235 MB |
| `chunks_embedding_halfvec_idx` (`halfvec_cosine_ops`) | hnsw | 117 MB |

halfvec / vector = **50.0 %**. La tabla `chunks` ocupa 404 MB (sin contar los índices). Construir los dos
índices con `maintenance_work_mem=512MB` y 2 workers paralelos tardó ≈ 68 s sobre 30 000 filas.

## Overlap observado (`compare_indexes_s08.py`)

Top-5 de cada query contra el índice `vector` y contra el `halfvec` (cada uno forzado por la expresión del `ORDER BY`
y confirmado con `EXPLAIN`):

| Query | Overlap |
|-------|--------:|
| Componente conocido | 1.00 |
| Reformulación semántica | 1.00 |
| Dominio distinto | 1.00 |
| Ambigua | 1.00 |
| Muy específica | 1.00 |

Overlap medio **1.000**: el mismo top-5 con la mitad de espacio de índice. Las latencias son equivalentes (3.11 ms
`vector` frente a 3.15 ms `halfvec`). Por eso `/search` usa halfvec y `chunks_embedding_idx` queda solo para comparar
(se puede eliminar con `DROP INDEX CONCURRENTLY chunks_embedding_idx` sin afectar a la búsqueda).

En `output_examples.txt` (corpus real, 52 chunks) el orden y los `chunk_id` son los mismos que con el *sequential scan*;
solo cambia la cuarta cifra decimal de algunas distancias (p. ej. 0.5258 → 0.5257), por la media precisión del cast.

## Límites de la medición

- **5 queries y un corpus sintético**: el recall tiene granularidad de 0.2/query; las conclusiones son orientativas.
  Repetir `sweep_ef_search_s08.py` cuando el corpus real crezca.
- **Un primer intento con ruido muy pequeño** (copias casi idénticas de los 52 chunks) dio recall 0.3–0.7 y overlap
  0.44: no era un fallo del índice sino empates en el top-k y un grafo degenerado. El generador se cambió a mezclas
  convexas de vectores reales, que reparten los puntos de forma continua.
- La verdad de fondo es el top-10 exacto **del halfvec** (misma expresión que el índice): mide la pérdida del grafo
  HNSW, no la de la media precisión (esa se ve en `compare_indexes_s08.py`).
