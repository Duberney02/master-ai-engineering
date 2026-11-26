# Verificación del Bloque 4 (tareas 10 a 13)

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

## Bloque 5: imágenes, CI local, pila y aislamiento (tareas 12.1, 12.2, 13.1 y 13.2)

Proyecto `hl-s1` con `compose.bloque4.yml` (claves ficticias, proveedor simulado). Imágenes `estimador-cag:hl-stack`
(2,89 GB), `estimator-web:hl-stack` (21,5 MB) y `estimator-web-react:hl-stack` (90,6 MB), construidas con las capas en
caché. `errors_count` 0 y sin errores de kernel antes y después de cada construcción y grupo.

| Comprobación | Resultado |
|---|---|
| Imagen de IA | UID 10001; sin `streamlit` (ni `altair`/`pydeck`); sin `streamlit_app.py` ni `app/static`; `httpx` y `python-multipart` presentes; sin claves (el `GPG_KEY` de la imagen base de Python es una huella pública) |
| Imagen de Go | `nonroot:nonroot`; solo el binario `/estimator-web` (sin plantillas ni estáticos; `go list -deps` sin `html/template`); sonda `estimator-web healthcheck`; sin variables de proveedor |
| Imagen de React | Usuario 101 (Nginx sin privilegios); sonda `/healthz`; `API_UPSTREAM=http://estimator-web:3000` |
| Seis servicios | `healthy`; orden de arranque observado: Redis, PostgreSQL de Go y PostgreSQL de IA; después IA; después Go; por último React |
| Sondas nativas | `/health` de IA, `estimator-web healthcheck` (`/up`), `/healthz` de Nginx, `pg_isready` x2, `redis-cli ping` y RediSearch cargado |
| Persistencia (reinicio con `down` sin `-v` y `up --wait`) | Marcas en ambas bases, una estimación sintética servida después por React→Go→IA y una comparación sintética del Lab: conservadas |
| Publicación | Solo `estimator-web-react` en `127.0.0.1:3001`; el resto, sin publicación; sin IPv6 (`[::1]:3001` falla, redes sin IPv6); acceso por la IP del host sin túnel: falla |
| Administración | Lectura administrativa por React: 403 |
| Matriz de comunicaciones | 43 comprobaciones OK, 0 fallidas (ver `matriz-comunicaciones-bloque4.tsv`) |
| Salida HTTPS de IA | `estimador-cag` completa TLS contra el proveedor simulado en `ai-egress-net`; sin llamadas a proveedores reales |
| Credenciales | Solo `estimador-cag` las recibe (inspección de configuración de los otros cinco servicios) |
| Servicios del homelab | `postgresql`, `open-webui` y `ollama` sin cambios (mismas publicaciones en 127.0.0.1) |

Matriz observada: React alcanza solo Go; React no alcanza IA, Redis ni las dos PostgreSQL por DNS ni por IP directa, ni
el gateway ni la IP del host (5432, 11434, 3000, 8000, 6379) ni Internet. Go (posición equivalente en `client-net`,
`service-net` y `go-data-net`) alcanza IA y su PostgreSQL y no alcanza Redis ni la PostgreSQL de IA, el gateway,
la IP del host ni Internet. IA alcanza Redis y su PostgreSQL y no alcanza la PostgreSQL de Go ni los servicios del host.
`client-net` sin NAT (`enable_ip_masquerade=false`) mantiene la entrada publicada en 127.0.0.1:3001 y elimina la salida
a Internet de React y Go.

### Defectos hallados y corregidos

- Cinco archivos del árbol de trabajo tenían modo 0600 (Git registra 0644), con lo que `COPY` los dejaba ilegibles para el
  usuario sin privilegios de la imagen de IA y el servicio no arrancaba. Se restauró 0644 en el árbol; no cambia el
  contenido versionado.
- El arnés fallaba al comprobar las variables de Go con `exec env` (imagen sin `env`): ahora inspecciona la configuración.
- La prueba de persistencia sembraba una estimación con opciones inválidas; ahora usa registros válidos.

### Limitaciones

- `sshd` del host (`0.0.0.0:22`) es alcanzable desde los contenedores por el gateway (registrado como INFO en la
  matriz). Limitación aceptada; el endurecimiento del firewall queda para la fase de seguridad del homelab.
- Go no tiene shell: su posición se comprueba con una sonda en las mismas tres redes, no dentro de su contenedor.
- El pipeline remoto de CI no se ha ejecutado. Se comprobaron en local los comandos de cada job (suites del Compose de
  verificación, configuración de los Compose, smoke con sondas internas y puerto 3001).
- La prueba real del túnel SSH desde Windows está pendiente de confirmación del operador (13.2).

## Pendiente (no dado por completado)

Para 14.1: la cancelación del Chunking Lab contra Python real (hoy solo hay prueba unitaria) y la cancelación de REST/SSE
a través de React y Nginx. Para 15.2: la spec «cookie con firma inválida = sesión vacía» queda obsoleta (la cookie legada
solo se expira).
