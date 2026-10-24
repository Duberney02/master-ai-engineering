> Generado con `scripts/compare_chunkers.py --strategies free --show-stats --show-cost` dentro del contenedor.
> Solo incluye las estrategias **gratuitas**, que no necesitan claves. Las de pago (`semantic`, `propositional`,
> `contextual_retrieval`) y el top-k por consulta requieren `OPENAI_API_KEY` y `ANTHROPIC_API_KEY` y se generan con:
> `python scripts/compare_chunkers.py --strategies all --queries all --show-stats --show-top-k 3 --show-cost --output <ruta>`.
> El corpus son los 15 presupuestos de `data/budgets_sample.json` más 3 casos límite de `data/budgets_stress_cases.json`:
> un monolito de un solo componente muy largo (obeso), tareas mínimas (huérfanos) y descripciones de varias frases.

# Comparación de estrategias de chunking

Corpus: 18 presupuestos · estrategias: structural, fixed_size, recursive, sentence_window, hierarchical


## Estadísticos por estrategia

| strategy | chunks | min | p50 | p95 | max | huérfanos (<20) | obesos (>800) | segundos | llamadas extra | coste USD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| structural | 61 | 59 | 79.0 | 106.0 | 821 | 0 | 1 | 0.00 | 0 | 0.000000 |
| fixed_size | 62 | 59 | 79.0 | 106.0 | 512 | 0 | 0 | 0.00 | 0 | 0.000000 |
| recursive | 20 | 37 | 197.5 | 357.9 | 507 | 0 | 0 | 0.01 | 0 | 0.000000 |
| sentence_window | 103 | 4 | 19.0 | 26.0 | 33 | 53 | 0 | 0.05 | 0 | 0.000000 |
| hierarchical | 79 | 59 | 82.0 | 245.8 | 826 | 0 | 2 | 0.01 | 0 | 0.000000 |
