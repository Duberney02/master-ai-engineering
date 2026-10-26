# Sanity check de embeddings

Modelo `text-embedding-3-small` (1536 dimensiones). Ejecutado el 2026-10-20 con `scripts/compare.py` dentro del contenedor (`docker compose exec estimador-cag python scripts/compare.py ...`). Los umbrales son orientativos; esto no es una evaluación formal del modelo.

| Pareja | Texto A | Texto B | Similitud coseno | Expectativa orientativa |
|---|---|---|---|---|
| A (cercanos) | OAuth 2.0 authentication backend with JWT tokens for fintech mobile app | Authorization service using JSON Web Tokens for a banking application | **0.5957** | > 0.6 |
| B (no relacionados) | OAuth 2.0 authentication backend with JWT tokens for fintech mobile app | Database migration from MySQL to PostgreSQL with zero downtime | **0.1920** | < 0.4 |
| C (genéricos) | Backend services | API development | **0.5407** | sin umbral |

## Comentario

La pareja B cumple con holgura (0.19 < 0.4) y la A queda a 0.004 del umbral orientativo de 0.6 sin superarlo: separa claramente lo relacionado de lo que no lo está (0.60 frente a 0.19), pero el umbral de 0.6 resulta algo optimista para este modelo con frases largas y vocabulario distinto (JWT frente a JSON Web Tokens).
Lo más llamativo es la pareja C: dos frases de dos o tres palabras sin contexto alcanzan 0.54, casi lo mismo que la pareja A, de modo que la similitud de textos cortos y genéricos no es comparable con la de frases técnicas completas.
Un único valor de coseno no tiene una lectura absoluta; sirve para ordenar parejas, no para decidir "parecido" con un umbral fijo.
