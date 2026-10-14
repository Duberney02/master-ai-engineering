# Stress test del CAG: baseline de degradación

Fuente: `evals/stress/results.csv` (ejecución 20261014T102939Z). 900 filas (una por turno), 45 sesiones, 26 turnos con error. Modelo: gpt-4o-mini-2024-07-18 (un único proveedor). Coste total medido: 1.11 USD. Workers: 4.

## 1. Escenario × tamaño de adjunto

Latencia, `tokens_in` y coste usan solo las sesiones frías (sin ningún acierto de caché; las repeticiones idénticas aciertan la caché de completions y miden la caché, no el CAG). Coste acumulado: media por sesión de 20 turnos. Hit exacto/semántico: fracción de todos los turnos con `cache_hit_kind` exact/semantic. Recall: media de todos los turnos con hechos que evaluar.

| Escenario | Adjunto KB | Sesiones frías | Latencia P50 ms | Latencia P95 ms | Coste acum. USD/sesión | Hit exacto | Hit semántico | Recall medio |
|---|---|---|---|---|---|---|---|---|
| growing | 0 | 1/3 | 8 823 | 13 367 | 0.0182 | 64% | 0% | 0.88 |
| growing | 5 | 1/3 | 8 774 | 13 281 | 0.0223 | 62% | 0% | 0.84 |
| growing | 20 | 3/3 | 8 885 | 11 352 | 0.0241 | 0% | 0% | 0.88 |
| growing | 50 | 3/3 | 8 262 | 13 851 | 0.0282 | 0% | 0% | 0.81 |
| growing | 100 | 2/3 | 8 252 | 11 519 | 0.0338 | 33% | 0% | 0.86 |
| pivot | 0 | 1/3 | 7 448 | 9 012 | 0.0162 | 67% | 0% | 0.85 |
| pivot | 5 | 1/3 | 8 996 | 10 316 | 0.0189 | 67% | 0% | 0.87 |
| pivot | 20 | 1/3 | 8 214 | 10 552 | 0.0204 | 67% | 0% | 0.92 |
| pivot | 50 | 2/3 | 9 131 | 12 822 | 0.0273 | 31% | 0% | 0.89 |
| pivot | 100 | 3/3 | 8 556 | 12 187 | 0.0342 | 0% | 0% | 0.88 |
| contradiction | 0 | 1/3 | 5 737 | 12 889 | 0.0125 | 47% | 0% | 0.61 |
| contradiction | 5 | 1/3 | 6 889 | 12 705 | 0.0213 | 67% | 0% | 0.78 |
| contradiction | 20 | 1/3 | 8 991 | 14 507 | 0.0211 | 18% | 0% | 0.69 |
| contradiction | 50 | 2/3 | 9 761 | 15 289 | 0.0298 | 12% | 0% | 0.69 |
| contradiction | 100 | 3/3 | 9 499 | 13 578 | 0.0366 | 0% | 0% | 0.68 |

## 2. Curvas

**Latencia vs `tokens_in`** (todas las llamadas del turno):

| tokens_in del turno | Turnos | P50 ms | P95 ms | P50 (barra) |
|---|---|---|---|---|
| 0–2 000 | 6 | 3 271 | 4 438 | ███████ |
| 2 000–4 000 | 70 | 5 223 | 9 340 | ████████████ |
| 4 000–8 000 | 328 | 9 274 | 13 175 | █████████████████████ |
| 8 000–16 000 | 47 | 4 389 | 15 441 | ██████████ |
| 16 000–32 000 | 47 | 3 779 | 13 110 | ████████ |
| ≥ 32 000 | 6 | 10 773 | 14 248 | ████████████████████████ |

**Coste acumulado por sesión vs turno** (USD, media por tamaño de adjunto):

| Adjunto | turno 1 | turno 3 | turno 6 | turno 10 | turno 20 | turno 20 (barra) |
|---|---|---|---|---|---|---|
| 0 KB | 0.0004 | 0.0012 | 0.0025 | 0.0057 | 0.0156 | ███████████ |
| 5 KB | 0.0007 | 0.0018 | 0.0037 | 0.0078 | 0.0208 | ██████████████ |
| 20 KB | 0.0019 | 0.0037 | 0.0069 | 0.0113 | 0.0227 | ████████████████ |
| 50 KB | 0.0036 | 0.0067 | 0.0118 | 0.0162 | 0.0284 | ███████████████████ |
| 100 KB | 0.0054 | 0.0107 | 0.0186 | 0.0227 | 0.0350 | ████████████████████████ |

**Recall de memoria vs N** (fracción de hechos vigentes presentes en resumen, anclas o metadatos):

| Escenario | N=1 | N=3 | N=6 | N=10 | N=20 |
|---|---|---|---|---|---|
| growing | n/d | 1.00 | 0.97 | 0.78 | 0.85 |
| pivot | n/d | 1.00 | 0.68 | 0.95 | 0.97 |
| contradiction | n/d | 1.00 | 0.48 | 0.54 | 0.78 |
| **todos** | n/d | 1.00 | 0.73 | 0.76 | 0.87 |

## 3. Observaciones de memoria y presupuestos

- `pivot`: Django (sustituido en el turno 5) sigue en la memoria en 15 de 15 sesiones (100%).
- `contradiction`: el presupuesto de 30.000 EUR (sustituido en el turno 8) sigue en la memoria en 15 de 15 sesiones (100%).
- `growing`: el nombre original (Atlas) sobrevive en memoria en 14 de 14 sesiones.
- Adjunto de 5 KB: el hecho `Veridian` del turno 1 está en memoria al final en 9 de 9 sesiones.
- Adjunto de 20 KB: el hecho `Veridian` del turno 1 está en memoria al final en 9 de 9 sesiones.
- Adjunto de 50 KB: el hecho `Veridian` del turno 1 está en memoria al final en 9 de 9 sesiones.
- Adjunto de 100 KB: el hecho `Veridian` del turno 1 está en memoria al final en 9 de 9 sesiones.
- Presupuesto de latencia 30000 ms: cumplen 503 de 504 turnos (100%).
- Presupuesto de coste 0.01 USD/turno: cumplen 504 de 504 turnos (100%).

## 4. Análisis

**Dónde degrada el CAG.** En el rango medido (hasta 100 KB de adjunto, 20 turnos, gpt-4o-mini) no rompe por tamaño de contexto: el turno de mayor `tokens_in` (36 534 con el PDF de 100 KB, 22 veces los 1 642 sin adjunto) tardó 10,6 s frente a 2,9 s, y solo 1 de 504 turnos fríos superó el presupuesto de 30 s; el coste acumulado a 20 turnos va de 0,016 USD (sin adjunto) a 0,035 USD (100 KB) y ningún turno superó 0,01 USD. La dimensión que domina es la **memoria**, no el contexto: el adjunto solo pesa mientras está en la ventana (en el turno 8 todas las sesiones rondan entre 3 600 y 4 100 `tokens_in`, con o sin adjunto) y, cuando sale, la latencia sube porque se activa la compresión (mediana 3,8 s en el turno 6 → 7,6 s en el 7 → 9,9 s en el 20, por las llamadas extra de anclas y resumen). El resumen se satura en 2 000 caracteres desde el turno 10 y el recall cae a 0,48–0,97 según el escenario en N=6 y a 0,78–0,97 en N=20 (`contradiction` es el peor: 0,48 en N=6). Además la memoria acumula en lugar de sustituir: el stack sustituido (Django) y el presupuesto anulado (30.000 EUR) siguen en memoria en 15 de 15 sesiones, y 26 de 900 turnos (24 de ellos en `contradiction`) fallaron con 502 por agotar la validación.

**Qué caso justificaría RAG.** El CAG actual se sostiene mientras el material cabe en la ventana de entrada: el tope duro es 80 000 caracteres entre transcripción y adjuntos (el PDF de 100 KB ya consume 73 238) y por encima la API rechaza con 413 en lugar de degradar. RAG estaría justificado cuando el corpus relevante supere ese tope (varios documentos, especificaciones o transcripciones largas) o cuando haya que recuperar hechos concretos de turnos antiguos con fiabilidad: ahí el resumen de 2 000 caracteres y las anclas heurísticas (0–1,3 anclas de media a los 20 turnos) pierden entre el 3 % y el 52 % de los hechos vigentes según el escenario. Para conversaciones cortas (N ≤ 3, recall 1,00) con adjuntos de hasta ~100 KB el CAG es suficiente y barato; la comparación con RAG debe repetir exactamente este protocolo y centrarse en recall a N ≥ 6 y en corpus mayores que el tope.

## 5. Límites

- El tope de texto de la API es `MAX_DESCRIPTION_CHARS` = 80 000 caracteres entre transcripción y adjuntos y
  se rechaza (413) en vez de truncar; no existe un `MAX_ATTACHMENT_CHARS` de 60 000. El PDF de 100 KB extrae
  73 238 caracteres: queda a 6 762 del tope.
- Las sesiones no pasan por la caché exacta ni la semántica del pipeline (su resultado depende del historial):
  solo por la caché de completions del wrapper (Redis del Compose). Por eso el hit semántico es 0 por construcción
  y el exacto solo aparece al repetir una sesión idéntica.
- El adjunto se envía solo en el turno 1; `latency_ms`, `tokens_in` y coste suman todas las llamadas del turno.
- Coincidencia exacta de hechos: una paráfrasis del modelo cuenta como olvido (falso negativo).
- Con `--workers` > 1 la latencia incluye la contención de la API del proveedor.

## 6. Reproducir

```sh
# desde la raíz del repositorio (Docker; estimador-cag/.env con la clave del proveedor)
docker compose up -d --build estimador-cag          # API + Redis + PostgreSQL del proyecto
docker compose -f docker-compose.verify.yml run --rm api-stress     --http http://host.docker.internal:8000 --scenarios growing,pivot,contradiction     --attachment-sizes 0,5,20,50,100 --repeats 3 --workers 4 --output evals/stress/results.csv
docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-stress -m evals.stress.report
```

Para vaciar la caché antes de otra medición: `docker compose exec redis redis-cli FLUSHALL`.
Sin `--http` el runner usa la
aplicación en proceso. Pruebas: `docker compose -f docker-compose.verify.yml run --rm api-test`.
