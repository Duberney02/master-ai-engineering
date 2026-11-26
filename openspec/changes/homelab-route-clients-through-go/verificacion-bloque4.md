# Verificación del Bloque 4 (parcial: tareas 10 y 11)

Base de código: `33662f1` (integración de S2 y S3) más las correcciones de `8bffce1` y posteriores. Proyecto Docker `hl-s1`,
claves ficticias, sin proveedores reales. Evidencias locales (no versionadas) en `.block4/evidencias/`. Las evidencias
de los bloques 1 a 3 no se han tocado.

## Entorno

Imágenes `estimador-cag:s1-test` y `estimator-web-go:s1-test` construidas tras el merge, con el `uv.lock` y el `go.mod`
definitivos; el código se monta desde el árbol actual. React usa la imagen del bloque 1 (el `package-lock.json` no ha
cambiado desde `73b6e40`) con las fuentes actuales montadas en solo lectura. Antes y después de cada grupo se
comprobó `errors_count` (0) y el registro del kernel (sin errores nuevos). Un solo grupo a la vez bajo el bloqueo
compartido.

## Resultados

| Comprobación | Resultado |
|---|---|
| `go vet` y gofmt (`web-lint`) | Correcto |
| `go test -count=1 -json ./...` con PostgreSQL efímero | 227 aprobadas, 0 fallidas, 2 omitidas (las dos que requieren el upstream Python) |
| `TestSSECancellationThroughPython` y `TestRESTCancellationThroughPython` contra el fixture ASGI de Python (`api-sse-fixture`) | Aprobadas |
| Vitest (React) | 175 de 175 |
| `verificar-paridad-bloque4.mjs` sobre `paridad-bloque3.json` (solo lectura) | 17 filas OK: 124 pruebas vigentes exigidas y ejecutadas con éxito; 70 referencias HTML retiradas (ausentes) y 2 conservadas, ambas aprobadas |
| Python dirigido (estructura, informe de stress, `main`, capas, SSE, ejemplos de documentación, estimaciones, arquitectura) | 89 aprobadas, 7 omitidas, 0 fallidas. Las omisiones de estructura del Compose se re-ejecutaron montando los Compose: 10 de 10 aprobadas |
| Ruff | Correcto |
| `openspec validate --all --strict` | 58 de 59. Falla solo `session-11-calidad-generacion-rag` (fallo heredado, sin deltas; no se modifica) |
| `uv.lock` y entorno de la imagen de pruebas | Sin `streamlit`; `httpx` y `python-multipart` presentes |

## Defectos hallados y corregidos

- `test_project_structure.py` seguía exigiendo el servicio de chat, los puertos antiguos y los archivos HTML de Go, y en el
  contenedor se omitía en silencio. Actualizado a la topología segmentada y a la retirada del HTML.
- `evals/stress/report.py` y `REPORT.md` describían un modo `--http` hacia `host.docker.internal`; ahora describen la
  ejecución en proceso.
- `client-net` tenía salida a Internet por NAT; se deshabilitó con `enable_ip_masquerade=false` (validación dinámica pendiente).

## Paridad: referencias históricas

La matriz del bloque 3 se conserva intacta. Sus referencias a pruebas HTML de Go figuran ahora como retiradas; su
reemplazo está en las columnas `recorrido_react` y `contrato_go` de cada fila (todas aprobadas) y en
`estimator-web-go/EVIDENCIA-RETIRADA-HTML.md`.

## Pendiente (no dado por completado)

12.1 (imágenes de la pila), 12.2 (CI y sondas en ejecución), 13.1 (pila sana, persistencia) y 13.2 (publicación,
matriz de comunicaciones y túnel SSH) requieren construir las imágenes y levantar la pila. Pendiente para 14.1: la
cancelación del Chunking Lab hasta Python (hoy solo hay prueba unitaria) y la cancelación de REST/SSE con Python real.
Limitación aceptada: el puerto SSH del host (`0.0.0.0:22`) puede alcanzarse desde los contenedores por el gateway;
el endurecimiento del firewall se pospone a la fase de seguridad del homelab. Para 15.2: la spec «cookie con firma
inválida = sesión vacía» queda obsoleta (la cookie legada solo se expira).
