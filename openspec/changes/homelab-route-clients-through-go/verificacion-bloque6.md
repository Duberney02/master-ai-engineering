# Verificación del Bloque 6 (tareas 14 a 16)

Base: `291da32` (checkpoint publicado del bloque 5). Proyecto Docker `hl-s1`, claves ficticias y proveedor OpenAI simulado
(nunca se contactó a un proveedor real). Evidencias locales en `.block4/evidencias/` (no versionadas); las versionadas están
en `evidencias-bloque6/`. Antes y después de cada construcción y grupo de pruebas se comprobó `errors_count` (0) y el registro
del kernel (sin errores nuevos). Un solo grupo a la vez bajo el bloqueo compartido.

## 14.1 Recorridos de extremo a extremo (cliente → Nginx → Go → Python)

Pila de integración real (imágenes `hl-stack`: React/Nginx, Go y la IA reconstruida con la corrección de este bloque) más el
proveedor OpenAI simulado (`openai-simulado.mjs`, en `ai-egress-net`, al que la IA llega con `OPENAI_BASE_URL`). El navegador se
sustituye por un cliente Node con el mismo contrato HTTP y la misma cancelación (`AbortController`) que `estimatorApi.ts`; el
cableado interno de React lo cubren las 175 pruebas de Vitest.

| Grupo | Resultado |
|---|---|
| Flujos (`e2e-flujos.txt`) | 39 de 39. Salud, vista previa del prompt con ejemplos, estimación REST con ID, historial y detalle (404 y límites 1–50), sesión creada, continuidad de turnos (1, 2, 3 y 4), metadatos, adjuntos PDF y DOCX, transcripción TXT larga, sesión inexistente 404, adjunto no admitido, archivo de 11 MiB (413), más de cinco archivos, JSON de más de 1 MiB (413), descripción corta (422), tipo no admitido, 404/405 JSON, ausencia del HTML de Go, 403 saneado en las seis rutas administrativas sin llamar al proveedor, proyección pública del modelo primario sin catálogo, SSE de transcripción y estructurada con entrega incremental, fallo del proveedor saneado (5xx, sin cuerpo del proveedor, claves ni hosts internos), recuperación y persistencia |
| Python detenido (`e2e-caido.txt`) | 3 de 3. Error 502/503/504 saneado, historial con error saneado y Nginx operativo |
| Cancelación con barreras (`e2e-cancelacion.txt`) | 8 de 8. REST antes de generar, durante la escritura y tras confirmarla (una fila completa y consultable); SSE estructurada antes, durante la escritura y tras `result`; SSE de transcripción tras el primer token. En todos Python observa el cierre y recibe un único POST |
| Cancelación del Chunking Lab hasta Python real | Go real (con la decisión administrativa exclusiva de pruebas), Python FastAPI real con el procesamiento retenido y PostgreSQL efímero. `TestLabCancellationThroughPython` |

**Defecto hallado y corregido.** `POST /embeddings/compare` no cancelaba el trabajo al desconectarse Go: tras cancelar,
Python seguía con el procesamiento activo (`provider_active=true`, sin liberar) hasta terminarlo. Evidencia previa a la corrección:
`lab-cancelacion-antes-de-la-correccion.txt` (FAIL). La ruta usa ahora `complete_while_connected` como las demás rutas REST;
resultado tras la corrección: PASS (`lab-cancelacion-tras-la-correccion.txt`), con una única solicitud, procesamiento
liberado y cero comparaciones persistidas. Se añadió la prueba unitaria `test_chunking_compare_disconnect_cancels_the_comparison`.

Alcance de la comprobación administrativa: los mecanismos de autorización de prueba no existen en la imagen normal, por lo que
en la pila real solo se comprueba el 403. Los flujos administrativos autorizados (Ajustes, catálogo y Chunking Lab) los cubre
la suite de Go (`api_admin_test`, `authorization_test`) y la prueba de cancelación del Lab. Los plazos de Nginx y Go se
verificaron en los bloques 3 y 4 (3.4, 6.1) y no se repiten con valores reales de 600 s.

## 14.2 Regresión completa

| Suite | Aprobadas | Fallidas | Omitidas |
|---|---|---|---|
| Go, `go test -count=1 ./...` con PostgreSQL efímero | 227 | 0 | 3 (las tres integraciones con Python: ver fila siguiente) |
| Go, integraciones con Python aislado (`TestSSECancellationThroughPython`, `TestRESTCancellationThroughPython`, `TestLabCancellationThroughPython`) | 3 | 0 | 0 |
| Python (`pytest -q -rs`, con el Compose raíz, el secundario, el de verificación y `estimator-web-go` montados) | 1757 | 0 | 0 |
| React, Vitest (39 suites) | 175 | 0 | 0 |
| React, `tsc` y `vite build` | correcto | | |
| Ruff, gofmt y go vet | correcto | | |
| Verificador de paridad (`verificar-paridad-bloque4.mjs` sobre `paridad-bloque3.json`, de solo lectura) | 17 de 17 filas; 124 pruebas vigentes exigidas, 70 referencias HTML retiradas y 2 conservadas | 0 | 0 |
| Compose y CI | `docker compose config` de la pila raíz, el secundario (con `.env.example`), el de verificación y los complementos; comprobador estático de topología (20 autopruebas) y comandos de los trabajos de CI ejecutados en local | | |

Justificación de omisiones: las 3 de Go requieren el upstream Python con barreras y se ejecutan por separado (fila siguiente). En
Python, la ejecución anterior omitía las pruebas de estructura del Compose porque el contenedor solo montaba `estimador-cag/`; con
los archivos montados no hay omisiones. No se redujo la cobertura ni se eliminó ninguna prueba.

El pipeline remoto de GitHub Actions **no se ha ejecutado** en este bloque: no se declara aprobado.

## 14.3 Auditoría de arquitectura

| Requisito | Resultado |
|---|---|
| React único cliente; Streamlit y HTML de Go ausentes | Sin Streamlit en dependencias, imágenes ni Compose; el binario de Go no importa `html/template`; `TestNoHTMLPresentationDependenciesRemain` y `TestRetiredHTMLRoutesAnswerJSON404WithoutEffects` pasan; el recorrido E2E confirma que las rutas HTML antiguas no existen. Solo quedan referencias históricas o de retirada (documentos con aviso, pruebas de ausencia y `AGENTS.md`) |
| Go única puerta de React hacia la IA; sin proxies genéricos | Sin `ReverseProxy` en Go; catálogo explícito de 17 rutas (`api.go`, `server.go`), resto 404/405. Nginx reenvía `/api/` a Go y Go aplica el catálogo. Matriz de red del bloque 5: React no alcanza IA, Redis ni PostgreSQL |
| Python responsable de IA, RAG y embeddings | Sin cambios de responsabilidad; Go solo valida transporte (capas verificadas por `test_layer_dependencies` y `archtest`) |
| Autorización administrativa denegada por defecto; sin autorización de pruebas en producción | `adminDecision` es `nil` en el ensamblado normal y solo se asigna en pruebas (`git grep`); no hay variable de configuración ni imagen que lo habilite; 403 en las seis rutas con cookies y cabeceras de rol falsas |
| Límites de archivos, solicitudes, errores y plazos | 413 (cuerpo y archivo), 415, 422 y errores saneados comprobados en E2E; plazos y límites en las suites de Go del bloque 3 |
| Cancelación y SSE | E2E 8 de 8 más la integración del Lab (defecto corregido) |
| IDs bigint como cadenas | `TestLabLargeIDsKeepExactDigitsThroughGoAndPostgreSQL` y `TestLabAtomicPersistenceInPostgreSQL` pasan |
| Segmentación de redes y publicación exclusiva de React | Matriz del bloque 5 (`matriz-comunicaciones-bloque4.tsv`, 43 comprobaciones) y túnel SSH real desde Windows. La ausencia de NAT en `client-net` no equivale a una política de firewall |
| Sin credenciales reales | `git grep` de claves sin resultados; las imágenes y la configuración no incluyen claves; las pruebas usan `sk-test-dummy` |

**Limitación aceptada.** `sshd` del host (`0.0.0.0:22`) es alcanzable desde los contenedores por el gateway. No se modificó el
firewall ni `sshd`. El endurecimiento queda para la fase de seguridad del homelab.

## 15.1 y 15.2 Documentación, especificaciones e instrucciones

Actualizados `README.md` raíz (arquitectura, redes, sondas, acceso por túnel SSH, pruebas y limitaciones), `AGENTS.md`
(estructura vigente, DA-15 a DA-28, comandos y estado de entorno privado de desarrollo), `openspec/config.yaml`, los README y
la arquitectura de los servicios afectados, los documentos de Streamlit (aviso de documento histórico) y
`arquitectura-actual.md` (aviso histórico). `CLAUDE.md` sigue importando `AGENTS.md` con `@AGENTS.md`, sin duplicaciones. En el
delta `web-backend-go` se resolvió la cláusula obsoleta sobre la cookie firmada: Go no emite cookies y expira la legada si llega
(escenario «Cookie legada»). La revisión de propósitos obsoletos de las especificaciones principales queda preparada en
`revision-propositos-specs.md` para el paso de integración de deltas; no se modificó ninguna especificación principal.
