# Verificación del cambio homelab-route-clients-through-go

Informe consolidado que acredita las 38 tareas de `tasks.md`. Reúne las verificaciones de cada bloque de implementación con sus
cantidades reales de pruebas, la matriz de comunicaciones, la prueba real del túnel SSH desde Windows, la evidencia de cancelación
del Chunking Lab antes y después de la corrección, la paridad funcional y las limitaciones aceptadas. Las salidas originales se
pueden recuperar desde Git (sección «Recuperación de las evidencias originales»).

**Las evidencias históricas conservan el vocabulario de su momento**: los «Bloques» 1 a 6 son las fases de implementación y los
nombres de scripts, Compose e imágenes que citan ya no existen con esos nombres; sus sustitutos están en `verification/` (ver
la sección «Refactorización de los arneses»). Los resultados de la refactorización se registran aparte y no sustituyen a los históricos.

## Resumen de aceptación

| Tareas | Verificación | Sección |
|---|---|---|
| 1.1–1.2, 2.1–2.3 | Inventario, caracterización y fixtures de referencia | Bloque 1 |
| 3.1–3.4, 4.1–4.2, 5.1–5.2 | API REST, SSE y frontera de autorización de Go | Bloque 2 |
| 6.1–6.2, 7.1–7.3, 8.1–8.3, 9.1–9.2 | Comunicaciones de React, Ajustes, Chunking Lab y paridad | Bloque 3 |
| 10.1–10.2, 11.1–11.3 | Retirada del HTML de Go y de Streamlit | Bloques 4 y 5 |
| 12.1–12.2, 13.1–13.2 | Imágenes, CI local, pila, persistencia, aislamiento de red y túnel SSH | Bloques 4 y 5 |
| 14.1–14.3, 15.1–15.2, 16.1 | Extremo a extremo, regresión, auditoría, documentación y validación final | Bloque 6 |

## Recuperación de las evidencias originales

Los archivos de esta carpeta que se consolidaron y retiraron siguen en Git, sin modificar:

| Archivo retirado | Ruta histórica | Commit donde existe |
|---|---|---|
| `caracterizacion.md` (referencia del Bloque 1: matrices E1–E9 y A1–A7, consumidores y límites) | `openspec/changes/archive/2026-11-26-homelab-route-clients-through-go/caracterizacion.md` | `1ef22c4c72ff72efcd71df7fe1fdff5ef043c14c` |
| `verificacion-bloque2.md`, `verificacion-bloque3.md`, `verificacion-bloque4.md`, `verificacion-bloque6.md` | misma carpeta | `1ef22c4c72ff72efcd71df7fe1fdff5ef043c14c` |
| `evidencias-bloque6/*.txt`, `matriz-comunicaciones-bloque4.tsv`, `revision-propositos-specs.md` | misma carpeta | `1ef22c4c72ff72efcd71df7fe1fdff5ef043c14c` |
| `compose.caracterizacion.yml`, `compose.bloque2.yml`, `compose.bloque3.yml`, `preparar-fuentes.py`, `preparar-bloque2.py`, `verificar-paridad.mjs` | misma carpeta | `1ef22c4c72ff72efcd71df7fe1fdff5ef043c14c` |

Antes del archivado, esos archivos estaban en `openspec/changes/homelab-route-clients-through-go/` (commit `6f3bffb5eb4a696d9f06dd7743a44e643cb89c6b`).
Recuperación: `git show <commit>:<ruta>`; por ejemplo
`git show 1ef22c4c72ff72efcd71df7fe1fdff5ef043c14c:openspec/changes/archive/2026-11-26-homelab-route-clients-through-go/caracterizacion.md`.
Las notas de los bloques 2 y 3 citan comandos, Compose y scripts de esa época (`compose.caracterizacion.yml`, `preparar-*.py`,
`.block1/` a `.block3/`); no son reproducibles tal cual y se conservan como registro.

## Bloque 1 · Referencia y caracterización (tareas 1 y 2)

Base de código `307a8b9`. La matriz completa de contratos (E1–E9 y A1–A7) está en `design.md`; la referencia detallada original, en
`caracterizacion.md` (ver recuperación).

### Trazabilidad de aceptación del Bloque 1

Los nombres siguientes identifican pruebas de referencia disponibles para la Parte C. La revisión estática confirma la existencia y el alcance de los casos. Los resultados de ejecución figuran en la sección de la Parte C.

| Tarea y casos | Criterio | Evidencia de referencia |
|---|---|---|
| 1.1, E1–E2 | 201 UUID, conservación de sesión, parámetros y adjuntos del turno, metadatos y errores | `test_sessions_api.py` (`test_create_session_returns_a_uuid_v4_and_distinct_ids`, `test_estimate_returns_a_validated_result_with_session_state`, pruebas de adjuntos, campos, caducidad y guardrails); `clients_test.go` (`TestSessionEstimationSendsMultipartEvenWithoutAttachments`); `sessionApi.test.ts`. |
| 1.1, E3–E5 | Prompt y defaults, historial con límites, campos anulables, ID inválido, ausente e indisponibilidad | `test_history.py` (vista previa, límites, persistencia, detalle 404 y 503); `test_history_postgres.py`; `test_history_conversation.py` (metadatos y sesión persistidos); `estimations_test.go`, `estimatorApi.test.ts` y `pages.test.tsx` para consumidores. El 422 del parámetro de ruta no entero de FastAPI se identifica en la firma tipada de `history.py`; Go HTML y React cubren el rechazo local. |
| 1.1, E6–E9 | JSON estructurado y validación, flujos SSE completos o interrumpidos, y sondas | `test_project_estimations.py`, `test_sse_and_options.py` y `test_stream_disconnect.py` (orden, error terminal, rechazo previo y cierre ASGI); `test_main.py` para `/health`; `security_test.go::TestTheHealthProbeAnswers200WithoutCallingAnyone` para `/up`; smoke de CI para `/healthz`. |
| 1.1, A1–A7 | Método, consumidor, entrada, salida y errores | Referencias estáticas en las siete filas A1–A7. Sus equivalentes HTML o internos se ejercitan con las pruebas de 2.2 y 2.3. Las rutas JSON objetivo se verifican en las etapas 7 y 8. |
| 1.2 | Lista de retirada y conservación con consumidores identificados | Registro de rutas en `internal/web/server.go`, embeds, inventario de scripts, CI y empaquetado. `security_test.go`, `session_test.go` y `test_project_structure.py` cubren comportamientos y archivos del legado. |
| 2.1 | Base aislada y casos OK, sin ID, no estimable, expiración, error, adjuntos, vista previa, métricas y navegación | Configuración `docker-compose.verify.yml` + `compose.caracterizacion.yml`; en Python, E1–E9. En Go, `conversation_test.go`, `estimations_test.go` y `home_test.go`. En React, `src/pages/conversation.test.tsx`, `src/pages/pages.test.tsx` y fixtures de `src/test/mockApi.ts`. La Parte B debe confirmar el aislamiento efectivo. |
| 2.2, A1–A3 | Siete campos, catálogo, primario, restablecimiento y fallos | `test_config_api.py` (overrides parciales, atomicidad, validación y embeddings de solo lectura); `settings_test.go` y `home_test.go` (formulario, indicador, caducidad e invalidación). |
| 2.2, A4–A7 | Ocho estrategias, consultas, coste, top-k, resultados jerárquicos, historial y fallos de persistencia | `lab_test.go` (incluido `TestLegacyLabPostWithoutTopKUsesOne`), `rag/contracts_test.go`, `clients_test.go::TestCompareChunkingSendsCorpusAndReturnsPayload` y `pg_test.go` (guardado, detalle e historial con IA simulada). |
| 2.3, A6–A7 | IDs históricos exactos, orden, fechas y payload reutilizable en el corte | `pgstore_test.go::TestStoreReadsLegacyComparisonsWithoutChangingIDsOrPayload` siembra tres `int64` superiores a 2⁵³−1, verifica orden cronológico y desempate y compara por igualdad JSONB tanto el valor de la tabla como el payload devuelto por `Find` frente al fixture. |


#### Resultados de la Parte C

Ejecución final de las suites el 25 de noviembre de 2026, de 22:49:12 a 22:51:03 UTC. Los registros locales en `.block1-evidencias/parte-c/` conservan comandos completos, fecha, duración de la operación Docker y códigos de retorno, con los intentos Python previos en subdirectorios separados.

| Operación | Inicio UTC | Duración Docker | Código | Resultado |
|---|---|---:|---:|---|
| Pytest 9.1.1, Python 3.11.18 | 22:49:12 | 12 s | 0 | 155 aprobadas, 0 fallidas, 0 omitidas. 9.03 s en Pytest y una advertencia de deprecación de Starlette/AnyIO. |
| Ruff 0.16.10 según `uv.lock` | 22:49:24 | 1 s | 0 | `check tests/test_stream_disconnect.py` pasó. |
| `go test -p 1 -count=1 -json ./...`, Go 1.25.14 | 22:49:53 | 28 s | 0 | 190 eventos de prueba o subprueba aprobados, 0 fallidos, 0 omitidos. Nueve paquetes aprobados y `cmd/server` sin archivos de prueba. |
| `gofmt -l .`, Go 1.25.14 | 22:50:21 | 1 s | 0 | Sin archivos pendientes de formato. |
| `go vet ./...`, Go 1.25.14 | 22:50:22 | 6 s | 0 | Sin diagnósticos. |
| Vitest 5.0.3, Node 22.23.5 | 22:50:54 | 9 s | 0 | 9 archivos, 113 aprobadas, 0 fallidas y 0 omitidas. 7.29 s en Vitest. |

Vitest ejecutó ambos archivos de API, `components.test.tsx`, `hooks.test.tsx`, `attachments.test.ts`, `estimationForm.test.ts`, `format.test.ts`, `conversation.test.tsx` y `pages.test.tsx`. Imágenes reutilizadas (IDs abreviados), API `4062b6ded3c1`, Go `45171af038d7`, React `483dc26b02bd`, pgvector `b513c48566e4` y PostgreSQL Go `f9cf3e1f0066`. Docker Engine 29.10.0 y Compose 5.8.0.

El primer intento Python arrojó 6 errores de recolección (código 2) porque faltaba el vocabulario de tiktoken en la imagen y DNS estaba bloqueado. Ruff devolvió 2 porque la versión instalada requiere un booleano textual en `RUFF_NO_CACHE`. Se corrigió el entorno con el vocabulario estático verificado en solo lectura y `RUFF_NO_CACHE=true`. El segundo intento dio 154 aprobadas y una fallida (código 1). El doble de la estimación SSE estructurada rechazaba los argumentos del pipeline, lo que generaba un evento `error` 502 por `TypeError`. Se corrigió la firma del doble y se repitió la suite con las mismas aserciones de desconexión.

| Tarea | Evidencia de aceptación |
|---|---|
| 1.1 | Las matrices E1–E9 y A1–A7 quedan trazadas a métodos, rutas, consumidores, schemas y referencias de prueba. |
| 1.2 | El inventario identifica consumidores, retirada o conservación y recursos compartidos, incluidas referencias de CI y empaquetado. |
| 2.1 | Las dos bases arrancaron sanas, con `tmpfs`, sin puertos y en su red aislada. Pasaron el round-trip de historial Python con PostgreSQL y ambos casos de desconexión SSE. Pytest y los recorridos HTML y React corroboran estimación válida, no estimable, sin ID, expiración, adjuntos, métricas, errores y navegación. |
| 2.2 | Pasaron los casos HTML de Ajustes y Lab con IA simulada, incluidos siete campos, catálogo, indicador, ocho estrategias, consultas, jerarquía, fallo de persistencia y `TestLegacyLabPostWithoutTopKUsesOne`. |
| 2.3 | Pasaron `TestStoreReadsLegacyComparisonsWithoutChangingIDsOrPayload`, `TestLabEndToEndWithPostgreSQL` y `TestLabHistoryPersistsAcrossServerInstances`. El fixture verificó fechas, orden y desempate, tres IDs exactos superiores a 2⁵³−1, tipo `bigint` e igualdad semántica del JSONB almacenado y devuelto por `Find`. |

El contador `errors_count` de EXT4 en `/dev/sda2` permaneció en 0 y la consulta del kernel desde el cierre de la Parte B no encontró incidencias nuevas de SATA, EXT4 o E/S. Se retiraron las bases y los contenedores efímeros de la Parte C. El inventario final no muestra contenedores activos ni volúmenes del proyecto de pruebas. PostgreSQL y Open WebUI siguen saludables, Ollama sigue activo y `ai-network` conserva su ID y sus tres endpoints. En el cierre formal se retiraron los dos contenedores detenidos de la ejecución interrumpida y la red residual `homelab-block1-307a8b9_default` tras verificar su titularidad y que la red estaba vacía. Se conservaron las dos redes de caracterización y las imágenes reutilizables.


## Bloque 2 · API REST, SSE y autorización de Go (tareas 3 a 5)

### Alcance de la evidencia

- REST. Servidores HTTP simulados verifican método y destino, UUID, contenido JSON y de formularios, representación de campos nulos y aditivos, límites, Unicode, errores saneados, salud independiente y cancelación de la solicitud HTTP upstream.
- SSE unitario. Un upstream HTTP simulado retiene eventos con barreras y comprueba que el primer evento ya llegó al cliente, incluso con fragmentación, comentarios, CRLF y datos multilínea. Los casos de error previo y terminal, EOF, secuencia incorrecta, tamaño, inactividad y plazo total verifican que Go no sintetiza `done`.
- Python aislado. Las pruebas ASGI del Bloque 1 se conservan y comprueban la desconexión de FastAPI durante la generación estructurada y tras un token de transcripción.
- Integración Go→Python. El cliente consume el handler Go en un servidor TCP y este llama a FastAPI/Uvicorn real en otra instancia. El fixture observa la finalización explícita del proveedor simulado, el cierre del generador y la escritura del historial real en PostgreSQL efímero. Para la interrupción durante la escritura, pausa después de `flush` y antes de `commit`. Una lectura independiente comprueba cero filas confirmadas. Tras `result`, el fixture retiene el siguiente evento y comprueba que la fila confirmada permanece. Los dobles de caché solo cuentan resultados completos del pipeline real. Esta prueba no incluye React ni Nginx.
- Autorización. La composición habitual carece de decisión que conceda administración. El servidor verifica la decisión por operación antes de entrar a los handlers HTML o al transporte JSON administrativo. El fake se asigna desde los tests. El transporte JSON administrativo queda registrado para denegar accesos en esta etapa. Sus operaciones se implementarán en el bloque correspondiente.

### Resultados de la regresión

Ejecución del 25 de noviembre de 2026 (UTC). Registros locales de comandos, avances, diagnósticos y códigos en `.block2/evidencias/`, excluido de Git. Imágenes reutilizadas del Bloque 1 (IDs abreviados), Python `4062b6ded3c1`, Go `45171af038d7`, React `483dc26b02bd`, PostgreSQL Go `f9cf3e1f0066` y pgvector `b513c48566e4`.

| Comprobación | Código | Duración Docker | Evidencia y línea base |
|---|---:|---:|---|
| Pytest 9.1.1 | 0 | 12 s | 162 aprobadas, 0 fallidas y 0 omitidas frente a 155 de la caracterización. Incluye las pruebas de arquitectura y dependencias. |
| Ruff 0.16.10 | 0 | <1 s | Pasó en los ficheros Python cambiados y los dos fixtures SSE. |
| Go 1.25.14 | 0 | 30 s | 223 pruebas y subpruebas aprobadas, 0 fallidas, frente a 190 de la caracterización. Las dos pruebas con upstream Python se omitieron en esta ejecución general y pasaron en la siguiente. |
| Integración Go→Python | 0 | 21 s | Cuatro escenarios SSE y un escenario REST aprobados. En REST el upstream observa la desconexión antes de responder, cierra el proveedor simulado y queda un solo POST, sin escrituras ni caché. |
| `gofmt` / `go vet`, Go 1.25.14 | 0 / 0 | 1 s / 7 s | Sin archivos pendientes de formato ni diagnósticos. |
| Vitest 5.0.3 | 0 | 7 s | 9 archivos y 113 pruebas aprobadas, 0 fallidas y 0 omitidas. Misma cobertura de regresión que en el Bloque 1. |

La primera verificación REST encontró dos colisiones de nombres con el harness Go. Se renombraron los nuevos helpers. El intento siguiente ejecutó pruebas PostgreSQL sin iniciar su base y se repitió con la instancia efímera verificada. La primera integración SSE pasó tres escenarios y falló después de `result` porque la barrera del fixture no escuchaba la desconexión. El fixture corrigió la espera usando un `StreamingResponse` de pruebas, sin cambios en el protocolo. Una regresión Go quedó bloqueada en la salida de un servidor simulado que no consumía el cuerpo POST. Se detuvo ese contenedor específico, se retiró su base efímera y se corrigió el doble para leer el cuerpo y acotar la espera. La regresión final completa pasó.

Los recorridos con React→Nginx/Vite→Go y la configuración de clientes corresponden a etapas posteriores. El despliegue habitual conserva las rutas HTML para estimaciones y aplica la denegación administrativa a Ajustes y Lab. El origen de navegador puede configurarse con `ESTIMATOR_PUBLIC_ORIGIN`. Los presupuestos públicos son independientes del plazo legado `ESTIMATOR_READ_TIMEOUT`; las variables `ESTIMATOR_REGULAR_*`, `ESTIMATOR_LONG_*`, `ESTIMATOR_PROBE_TIMEOUT`, `ESTIMATOR_STRUCTURED_*_TIMEOUT` y `ESTIMATOR_TRANSCRIPTION_*_TIMEOUT` mantienen los defaults documentados en el diseño.

El binario normal, compilado en Docker con `go build -p 1 -trimpath -o /tmp/estimator-web ./cmd/server`, devolvió 403 en Ajustes y Lab, tanto en JSON como en HTML, con una cabecera de rol falsificada y la variable del fixture presente. La comprobación se hizo por loopback dentro de `web-lint`, sin red ni puertos publicados (código 0, 19 s).

El inventario final confirma que se retiraron los contenedores efímeros y las bases del Bloque 2. Las dos redes internas exclusivas quedaron sin endpoints y el proyecto no tiene volúmenes. Se preservaron las imágenes reutilizadas, `ai-network` y sus tres servicios. El contador EXT4 se mantuvo en 0 y los registros consultados no contienen incidencias nuevas de SATA, EXT4 o E/S.

### Correcciones tras la revisión técnica

La primera versión validaba la presencia de partes de la respuesta, pero podía aceptar fases vacías y metadatos SSE fuera de contrato. Go aplica ahora reglas compartidas para el resultado de estimación REST y el evento `result`, con validadores específicos para los otros contratos. Conserva el JSON original para mantener campos aditivos, nulos admitidos y precisión numérica.

| Frontera | Validación y comportamiento |
|---|---|
| REST de sesiones y estimación | UUID y clave de sesión exacta, metadatos y contadores conversacionales, resultado completo y fases con nombre, duración y coste, métricas anidadas si están presentes. Una respuesta inválida produce 502 JSON saneado. |
| REST de lectura | Vista previa con ejemplos válidos, historial con entradas completas y detalle con opciones y resultado tipados. Las colecciones vacías previstas y los campos anulables siguen siendo compatibles. `/health` conserva el 503 aprobado para upstream inválido. |
| SSE antes de cabeceras | El cliente de IA valida estado HTTP y tipo de contenido. Un 200 con tipo incompatible produce 502 JSON saneado. |
| SSE después de cabeceras | Se validan `result`, `token`, `metadata`, `done` y `error` según la ruta, incluyendo uso agregado y por fase, y evaluación cuando se incluye. Ante un evento inválido se cancela y cierra upstream y se emite un único error terminal si se puede escribir. Los eventos siguientes se descartan, incluido `done`. |
| Escritura SSE | El plazo de 30 s se aplica antes de `WriteHeader` y del primer `Flush`, y se libera tras un flush correcto. El doble de transporte detiene el primer flush, confirma el plazo desde las cabeceras y simula su vencimiento. La prueba verifica el cierre del handler y del upstream. |
| Persistencia después de `result` | PostgreSQL efímero devuelve la fila completa como JSONB antes y después de cancelar. La prueba compara ID, número de filas, resultado emitido, opciones, modelo, proveedor, caché, fechas y metadatos, sin reducir números a `float64`. Las comprobaciones de caché siguen usando dobles del pipeline. |

Los casos negativos incluyen fases vacías o incompletas, tipo incorrecto, nulos no admitidos, objetos y colecciones inválidos y secuencia SSE con un evento inválido antes de `done`. Los positivos comprueban campos aditivos, ausencia de opciones admitidas, valores nulos admitidos e IDs por encima de 2⁵³−1. Las pruebas completas de UI de React del Bloque 2 siguen siendo aplicables. React, sus dependencias y su configuración no cambiaron en esta corrección y Vitest no se repitió.

La copia de fuentes del Bloque 2 incluye el nuevo validador `internal/estimatorai/contracts.go`. La copia histórica del Bloque 1 se conserva. Los registros de esta revalidación se guardan bajo `.block2/evidencias/correccion/` y `.block2/evidencias/correccion-final/`, fuera de Git.

Revalidación secuencial del 25 de noviembre de 2026 (UTC). Se usaron las mismas imágenes identificadas arriba, con Go 1.25.14 y Python 3.11.18. Los registros de cada ejecución conservan el comando exacto, la duración y el código de retorno.

| Comprobación | Código | Duración | Resultado |
|---|---:|---:|---|
| REST, SSE y primer flush dirigidos | 0 / 0 / 0 | 22 / 23 / 22 s | Pasaron los casos positivos y negativos de cada grupo. |
| Casos dirigidos sobre la copia final | 0 | 21 s | Pasaron la clave exacta de sesión, el tipo de contenido SSE incorrecto y el bloqueo del primer flush. |
| Integración dedicada sobre la copia final | 0 | 34 s | Cuatro escenarios SSE y uno REST, incluidos los límites de persistencia y la comparación de la fila confirmada. |
| `go test -p 1 -count=1 -timeout=90s -json ./...` sobre la copia final | 0 | 32 s | 247 pruebas y subpruebas aprobadas, 0 fallidas y 2 omitidas que se ejecutaron en el servicio dedicado. |
| `gofmt -l .` / `go vet ./...` | 0 / 0 | <1 / 6 s | Sin archivos pendientes de formato ni diagnósticos de vet. |
| Pytest 9.1.1 | 0 | 12 s | 162 aprobadas, 0 fallidas, 0 omitidas y 1 advertencia. Las fuentes Python quedaron idénticas en ambas copias. |
| Ruff 0.16.10 | 0 | <1 s | Alcance: `app/api/disconnect.py app/api/project_estimations.py app/api/sessions.py tests/block2_sse_fixture.py tests/test_stream_disconnect.py`. |


## Bloque 3 · React, Ajustes, Chunking Lab y paridad (tareas 6 a 9)

### Resultados

| Comprobación | Código | Resultado |
|---|---:|---|
| `go test -p 1 ./...` (JSON) | 0 | 335 pruebas y subpruebas: 333 aprobadas, 0 fallidas, 2 omitidas (las dos que requieren el upstream Python; pasan en la fila siguiente). Frente a 223 del Bloque 2. |
| Integración Go → FastAPI real | 0 | `TestSSECancellationThroughPython` (cuatro escenarios) y `TestRESTCancellationThroughPython` aprobadas. |
| `gofmt` / `go vet` (Go 1.25.14) | 0 / 0 | Sin archivos pendientes ni diagnósticos. |
| Vitest 5.0.3 | 0 | 11 archivos y 175 pruebas aprobadas, 0 fallidas, 0 omitidas (113 en el Bloque 2). |
| `tsc --noEmit` y `vite build` | 0 | Compilación de la SPA correcta. |
| Pytest | 0 | 1798 aprobadas, 6 omitidas por entorno (cinco comprueban el Compose raíz y una el directorio Go, que el contenedor no monta), 0 fallidas. Sin código Python cambiado. |
| Ruff | 0 | `All checks passed!` |
| Matriz de paridad | 0 | 17 filas, 120 referencias a pruebas Go y 76 a React, todas existentes y aprobadas. |
| nginx → upstream simulado | 0 | 33 comprobaciones aprobadas, 0 fallos (ver abajo). Plazos incoherentes: el contenedor se niega a arrancar (código 1). |
| Binario normal con variables y cabeceras manipuladas | 0 | Ajustes y Lab, API y HTML, 403; `primary-model` 200 `{"model":null}`; `/up` 200. |
| `openspec validate homelab-route-clients-through-go --strict` | 0 | Válido. `validate --all --strict`: 58 aprobados y 1 fallo heredado de `session-11-calidad-generacion-rag` (sin deltas), documentado en `tasks.md`. |

Registros locales de cada comando en `.block3/evidencias/`, excluido de Git.

### Qué se verifica y con qué

- **6.1 · Proxy hacia Go.** Compose, Dockerfile, plantilla de nginx y `vite.config.ts` dirigen `/api` y `/health` a Go. `src/test/viteConfig.test.ts` fija destino, orden de reglas, plazos 35/615 s y su validación. `nginx-check.mjs` comprueba contra un upstream simulado, con barreras y sin pausas arbitrarias: el primer evento de cada ruta SSE llega al cliente antes de que el upstream emita el resto, cabeceras SSE y de seguridad, sin compresión; el cierre del cliente llega al upstream en las dos rutas SSE y en las dos largas con un único POST; la clasificación por plazos (habitual 504 a los 2 s, largas y SSE silenciosas más allá del habitual, SSE inactivo cortado al plazo largo); 413 con 56 MiB y paso con 54 MiB; `X-Forwarded-For` reescrito y `Host` del upstream; `/health` reenviado y `/healthz` local.
- **6.2 · Contratos y cancelación.** `AbortSignal` llega a `fetch` en estimaciones y sesión. Pruebas: cancelar rehabilita el formulario, no muestra resultado parcial, conserva el borrador y no reenvía; salir de la pantalla aborta; una señal ya abortada no envía; el 404 de sesión conserva el borrador y no reenvía; rechazos locales conservan el borrador; plazos 40/630 s coordinados.
- **7.1–7.3 · Ajustes e indicador.** Go proyecta el catálogo con `null`, filtra por proveedor, envía todos los campos, convierte vacío en `null`, no llama a IA sin campos reconocidos y sanea los `detail`. La atomicidad pertenece a IA (`tests/test_config_api.py::test_put_is_all_or_nothing`, incluida en la ejecución de Pytest). `primary-model` es general, expone solo el nombre y cachea valor, ausencia y fallo 15 s. Las pruebas deterministas de la caché usan barreras: lecturas concurrentes comparten una consulta, la consulta en vuelo invalidada no se almacena, el contexto del primer lector no cachea una ausencia falsa y los lectores cancelados no esperan. React cubre selectores, embeddings de solo lectura, confirmación, rechazo, reintento, estado restringido, `aria-current`, enlace del indicador solo tras acceso concedido e inicio utilizable sin servicios.
- **8.1–8.3 · Lab.** Opciones y comparación con las ocho estrategias, `top_k` omitido = 3 y enteros acotados a 1–10 (también fuera de 64 bits), decimales/exponentes/cadenas/booleanos/`null` = 422, consultas sin tope propio (1 500 consultas y una de 20 000 caracteres intactas), mapeo completo de errores, plazo propio, 201 con `Location` o 200 con ID nulo, cancelación hasta IA sin escritura, y atomicidad en PostgreSQL. Listado de 20, indisponibilidad, 404/500. `TestLabLargeIDsKeepExactDigitsThroughGoAndPostgreSQL` siembra el ID 9007199254740993, avanza la secuencia y crea el 9007199254741001; alta, `Location`, listado y detalle conservan los dígitos tras reiniciar el servidor, y PostgreSQL mantiene `bigint` y el valor. React usa los IDs como texto (ruta y detalle con dígitos exactos) y rechaza un ID numérico en el JSON.
- **9.1–9.2 · Paridad y corte.** `paridad-bloque3.json` enlaza cada capacidad HTML con su prueba HTML de referencia (que sigue pasando, porque el HTML se conserva), su recorrido React y su contrato Go. `verificar-paridad.mjs` falla si una referencia no existe, no pasó o fue omitida. Bloqueo en composición normal: `TestAdministrativeOperationsDenyBeforeEffects`, `TestNormalCompositionDeniesEveryAdministrativeRouteWhateverTheClientSends` y `TestNoProductionCodeEnablesAnAdministrativeDecision`, más la comprobación del binario real. Evidencia de aprobación del corte: esta tabla y las dos salidas de la matriz; no depende de un sistema de identidad.

### Limitaciones y observaciones

- Sin detector de carreras: la imagen de pruebas no tiene `gcc` y no hay red. La concurrencia de la caché se verifica con barreras deterministas, no con `-race`.
- Tras nginx, Go solo acepta mutaciones del navegador si `ESTIMATOR_PUBLIC_ORIGIN` coincide con el origen visto por el navegador (el Compose lo fija a `http://localhost:3001`). El recorrido React → Nginx → Go real con IA simulada corresponde a la tarea 14.1.
- No se construyó la imagen de producción de React: la base `node:22-alpine` no está en local y no hay red. Se verifican la plantilla, el script de plazos y las variables de entorno con la imagen estándar de nginx y el `Dockerfile` como texto.
- Se conservan íntegros el HTML de Go y Streamlit, que sigue apuntando a la API de IA hasta los bloques posteriores.


## Bloques 4 y 5 · Retirada de Go HTML y de Streamlit, infraestructura y aislamiento (tareas 10 a 13)

### Entorno

Imágenes `estimador-cag:s1-test` y `estimator-web-go:s1-test` construidas tras el merge, con el `uv.lock` y el `go.mod`
definitivos; el código se monta desde el árbol actual. React usa la imagen del bloque 1 (el `package-lock.json` no ha
cambiado desde `73b6e40`) con las fuentes actuales montadas en solo lectura. Antes y después de cada grupo se
comprobó `errors_count` (0) y el registro del kernel (sin errores nuevos). Un solo grupo a la vez bajo el bloqueo
compartido.

### Resultados

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

### Defectos hallados y corregidos

- `test_project_structure.py` seguía exigiendo el servicio de chat, los puertos antiguos y los archivos HTML de Go, y en el
  contenedor se omitía en silencio. Actualizado a la topología segmentada y a la retirada del HTML.
- `evals/stress/report.py` y `REPORT.md` describían un modo `--http` hacia `host.docker.internal`; ahora describen la
  ejecución en proceso.
- `client-net` tenía salida a Internet por NAT; se deshabilitó con `enable_ip_masquerade=false` (validación dinámica pendiente).

### Paridad: referencias históricas

La matriz del bloque 3 se conserva intacta. Sus referencias a pruebas HTML de Go figuran ahora como retiradas; su
reemplazo está en las columnas `recorrido_react` y `contrato_go` de cada fila (todas aprobadas) y en
`estimator-web-go/EVIDENCIA-RETIRADA-HTML.md`.

### Bloque 5: imágenes, CI local, pila y aislamiento (tareas 12.1, 12.2, 13.1 y 13.2)

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

#### Defectos hallados y corregidos

- Cinco archivos del árbol de trabajo tenían modo 0600 (Git registra 0644), con lo que `COPY` los dejaba ilegibles para el
  usuario sin privilegios de la imagen de IA y el servicio no arrancaba. Se restauró 0644 en el árbol; no cambia el
  contenido versionado.
- El arnés fallaba al comprobar las variables de Go con `exec env` (imagen sin `env`): ahora inspecciona la configuración.
- La prueba de persistencia sembraba una estimación con opciones inválidas; ahora usa registros válidos.

#### Limitaciones

- `sshd` del host (`0.0.0.0:22`) es alcanzable desde los contenedores por el gateway (registrado como INFO en la
  matriz). Limitación aceptada; el endurecimiento del firewall queda para la fase de seguridad del homelab.
- Go no tiene shell: su posición se comprueba con una sonda en las mismas tres redes, no dentro de su contenedor.
- El pipeline remoto de CI no se ha ejecutado. Se comprobaron en local los comandos de cada job (suites del Compose de
  verificación, configuración de los Compose, smoke con sondas internas y puerto 3001).

#### Túnel SSH desde Windows (prueba real del operador)

Con `ssh -N -L 3001:127.0.0.1:3001 <usuario>@<servidor>` abierto desde Windows (puerto local 3001, el origen canónico):

| Comprobación | Resultado |
|---|---|
| `GET http://localhost:3001/healthz` | `ok` |
| `GET http://localhost:3001/api/v1/estimations` | `[]` |
| `GET http://localhost:3001/api/v1/ai/settings` | HTTP 403 |
| Interfaz React en el navegador | Carga: formulario de estimación, metadatos del proyecto, contexto del prompt, ejemplos few-shot y modelo `gpt-4o-mini` |
| `Test-NetConnection <servidor> -Port 3001` | `TcpTestSucceeded: False` (el ping responde, `PingSucceeded: True`) |
| `curl.exe -m 5 http://<servidor>:3001/healthz` | `curl: (28)` tiempo de espera agotado |

Acceso positivo por el túnel y fallo de la conexión directa sin túnel, como exige 13.2. La estimación sintética no se
mostraba en el historial porque se eliminó antes de esta prueba.

### Pendiente al cerrar el bloque 5 (resuelto en el bloque 6)

Para 14.1: la cancelación del Chunking Lab contra Python real (hoy solo hay prueba unitaria) y la cancelación de REST/SSE
a través de React y Nginx. Para 15.2: la spec «cookie con firma inválida = sesión vacía» queda obsoleta (la cookie legada
solo se expira).


### Matriz completa de comunicaciones (43 comprobaciones y 1 informativa)

Salida de la validación dinámica del Bloque 5 (proyecto temporal, pila real con claves ficticias):

| Origen | Destino | Esperado | Observado | Resultado |
|---|---|---|---|---|
| react | estimator-web:3000 | alcanza | alcanza | OK |
| react | estimador-cag:8000(DNS) | falla | falla | OK |
| react | redis:6379(DNS) | falla | falla | OK |
| react | postgres:5432(DNS) | falla | falla | OK |
| react | estimator-web-db:5432(DNS) | falla | falla | OK |
| react | host.docker.internal:5432(DNS) | falla | falla | OK |
| react | 172.26.0.4:8000(IP-IA) | falla | falla | OK |
| react | 172.29.0.2:8000(IP-IA) | falla | falla | OK |
| react | 172.27.0.2:8000(IP-IA) | falla | falla | OK |
| react | 172.26.0.2:6379(IP-redis) | falla | falla | OK |
| react | 172.26.0.3:5432(IP-pgIA) | falla | falla | OK |
| react | 172.28.0.2:5432(IP-pgGo) | falla | falla | OK |
| react | 172.25.0.1:5432 | falla | falla | OK |
| react | 172.25.0.1:11434 | falla | falla | OK |
| react | 172.25.0.1:3000 | falla | falla | OK |
| react | 172.25.0.1:8000 | falla | falla | OK |
| react | 172.25.0.1:6379 | falla | falla | OK |
| react | 192.168.1.17:5432 | falla | falla | OK |
| react | 192.168.1.17:11434 | falla | falla | OK |
| react | 192.168.1.17:3000 | falla | falla | OK |
| react | 192.168.1.17:8000 | falla | falla | OK |
| react | 192.168.1.17:6379 | falla | falla | OK |
| react | 1.1.1.1:443(Internet) | falla | falla | OK |
| react | 8.8.8.8:53(Internet) | falla | falla | OK |
| go | estimador-cag:8000 | alcanza | alcanza | OK |
| go | estimator-web-db:5432 | alcanza | alcanza | OK |
| go | redis:6379(DNS) | falla | falla | OK |
| go | postgres:5432(DNS) | falla | falla | OK |
| go | 172.26.0.2:6379(IP-redis) | falla | falla | OK |
| go | 172.26.0.3:5432(IP-pgIA) | falla | falla | OK |
| go | 172.25.0.1:5432 | falla | falla | OK |
| go | 172.25.0.1:11434 | falla | falla | OK |
| go | 172.25.0.1:3000 | falla | falla | OK |
| go | 172.25.0.1:6379 | falla | falla | OK |
| go | 1.1.1.1:443(Internet) | falla | falla | OK |
| go | 8.8.8.8:53(Internet) | falla | falla | OK |
| ia | redis:6379 | alcanza | alcanza | OK |
| ia | postgres:5432 | alcanza | alcanza | OK |
| ia | estimator-web-db:5432 | falla | falla | OK |
| ia | 172.28.0.2:5432(IP-pgGo) | falla | falla | OK |
| ia | 192.168.1.17:5432 | falla | falla | OK |
| ia | 192.168.1.17:11434 | falla | falla | OK |
| ia | 192.168.1.17:3000 | falla | falla | OK |
| react | 172.25.0.1:22(sshd, limitación aceptada) | - | alcanza | INFO |

## Bloque 6 · Extremo a extremo, regresión, auditoría, documentación y validación final (tareas 14 a 16)

### 14.1 Recorridos de extremo a extremo (cliente → Nginx → Go → Python)

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

### 14.2 Regresión completa

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

### 14.3 Auditoría de arquitectura

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

### 15.1 y 15.2 Documentación, especificaciones e instrucciones

Actualizados `README.md` raíz (arquitectura, redes, sondas, acceso por túnel SSH, pruebas y limitaciones), `AGENTS.md`
(estructura vigente, DA-15 a DA-28, comandos y estado de entorno privado de desarrollo), `openspec/config.yaml`, los README y
la arquitectura de los servicios afectados, los documentos de Streamlit (aviso de documento histórico) y
`arquitectura-actual.md` (aviso histórico). `CLAUDE.md` sigue importando `AGENTS.md` con `@AGENTS.md`, sin duplicaciones. En el
delta `web-backend-go` se resolvió la cláusula obsoleta sobre la cookie firmada: Go no emite cookies y expira la legada si llega
(escenario «Cookie legada»). La revisión de propósitos obsoletos de las especificaciones principales queda preparada en
`revision-propositos-specs.md` para el paso de integración de deltas; no se modificó ninguna especificación principal.

### 16.1 Validación final

| Comprobación | Resultado |
|---|---|
| `openspec status` | Cuatro artefactos `done`, planificación completa |
| `openspec validate homelab-route-clients-through-go --strict` | Válido |
| `openspec validate --all --strict` | 58 de 59. Falla solo `session-11-calidad-generacion-rag` (sin deltas): **fallo heredado**, no modificado |
| `git diff --check 6322a1d..HEAD`, `git status --short`, `git ls-files --others --exclude-standard` | Limpio y sin archivos sin seguimiento (los logs de evidencia se normalizaron sin espacios finales) |
| Once deltas | Los once presentes y válidos; solo se tocó `web-backend-go` en este bloque (cláusula de la cookie legada) |
| Secretos y temporales versionados | `git grep` de claves sin resultados; sin `.env`, `.block*`, cachés ni logs versionados |
| Alcance del diff desde la base `6322a1d` | 126 archivos: retirada del HTML de Go y de Streamlit, segmentación de redes, CI y Compose, arneses de verificación, corrección de la cancelación del Lab y documentación |
| CI remoto | No ejecutado: no se declara aprobado |

**Revisión independiente.** La efectuó un revisor externo de solo lectura sobre `291da32..HEAD`. No halló defectos demostrables.
Sus observaciones menores, aceptadas como limitaciones de las pruebas:

1. Los arneses `verificar-*.sh` fijan por defecto rutas propias del homelab (`HEAVY`, `/sys/fs/ext4/sda2/errors_count`): son específicos de esta máquina.
2. La aserción de «sin reintentos de POST» del E2E (`1 <= llamadas al proveedor <= 4`) no distingue un reintento extra de Nginx o de Go de los
   reintentos del SDK; el cierre exacto con un único POST lo comprueba la fase de cancelación y las pruebas de Go del bloque 3 (3.4).
3. La comprobación E2E de las rutas HTML antiguas es laxa; la cubren `TestRetiredHTMLRoutesAnswerJSON404WithoutEffects` y
   `TestNoHTMLPresentationDependenciesRemain`.
4. El fixture parchea `ChunkingComparator.compute_stats` al importarse; solo se carga en el contenedor aislado de pruebas.
5. Las especificaciones principales siguen mencionando tecnologías retiradas hasta la integración de deltas; está preparado en
   `revision-propositos-specs.md`.


### Salidas de los recorridos de extremo a extremo (14.1)

Flujos:

```
Container hl-s1-e2e-run-0b2f3615d4a6 Creating
 Container hl-s1-e2e-run-0b2f3615d4a6 Created
OK    nginx /healthz
OK    vista previa del prompt (200, prompt y ejemplos few-shot)
OK    vista previa sin proveedor
OK    estimación REST 200 con resultado e ID
OK    historial lista la estimación
OK    detalle por ID
OK    detalle inexistente 404
OK    ID no numérico rechazado sin 5xx
OK    límites del historial 1–50
OK    sesión creada (201 + UUID)
OK    turno 1 (200, turn_count 1, project_metadata)
OK    turno 2 continúa la conversación (turn_count 2)
OK    adjuntos PDF y DOCX aceptados (200)
OK    transcripción TXT larga como texto del turno (200)
OK    sesión inexistente 404
OK    adjunto no admitido (4xx saneado)
OK    archivo de 11 MiB rechazado (413)
OK    más de cinco archivos rechazado (4xx)
OK    JSON de más de 1 MiB rechazado (413)
OK    descripción corta rechazada (422)
OK    tipo de contenido no admitido (415)
OK    ruta desconocida 404 JSON
OK    método no admitido 405
OK    rutas HTML antiguas de Go ya no existen (SPA o 404, nunca HTML de Go)
OK    GET /api/v1/ai/settings → 403 saneado
OK    PUT /api/v1/ai/settings → 403 saneado
OK    GET /api/v1/rag/chunking-comparisons/options → 403 saneado
OK    GET /api/v1/rag/chunking-comparisons → 403 saneado
OK    POST /api/v1/rag/chunking-comparisons → 403 saneado
OK    GET /api/v1/rag/chunking-comparisons/1 → 403 saneado
OK    lo administrativo no llamó al proveedor
OK    proyección pública del modelo primario (200, sin catálogo)
OK    SSE transcripción: text/event-stream, tokens y done
OK    SSE transcripción: entrega incremental (primer token mucho antes del final)
OK    SSE estructurada: result y done en orden
OK    fallo del proveedor → 5xx saneado (sin cuerpo del proveedor, claves ni hosts internos)
OK    sin reintentos de POST desde Nginx ni Go (una sola ráfaga de reintentos del SDK, no multiplicada)
OK    recuperación tras el fallo
OK    persistencia: el historial conserva las estimaciones
flujos: 39/39 correctas
```

Python detenido:

```
Container hl-s1-e2e-run-46c699daa294 Creating
 Container hl-s1-e2e-run-46c699daa294 Created
OK    Python detenido → 502/503/504 saneado desde React→Go
OK    historial con Python detenido → error saneado, no HTML ni traza
OK    Nginx sigue sirviendo con Python detenido
caido: 3/3 correctas
```

Cancelación con barreras:

```
Container hl-s1-e2e-run-3eb3278e9718 Creating
 Container hl-s1-e2e-run-3eb3278e9718 Created
OK    REST/antes: el cliente recibe la cancelación
OK    REST/antes: Python observa el cierre, un único POST y cero filas
OK    REST/escritura: Python libera la escritura, un único POST y cero filas confirmadas
OK    REST/después: Python observa el cierre, un único POST y exactamente una fila completa consultable
OK    SSE estructurada/before: cierre hasta Python, un POST, ninguna fila y sin caché parcial (0 entradas completas)
OK    SSE estructurada/write: cierre hasta Python, un POST, ninguna fila y sin caché parcial (2 entradas completas)
OK    SSE estructurada/tras result: cierre hasta Python, un POST y exactamente una fila completa
OK    SSE transcripción/tras el primer token: cierre hasta Python, liberación del proveedor, un POST y sin datos parciales
cancelacion: 8/8 correctas
```

### Cancelación del Chunking Lab hasta Python real: antes y después de la corrección

Antes de corregir `POST /embeddings/compare` (el procesamiento de Python seguía activo tras cancelar Go):

```
[heavy] s1-lab esperando 15:18:17
[heavy] s1-lab adquirido 15:18:17
 Container hl-s1-api-sse-fixture-1 Running
 Container hl-s1-block1-web-db-1 Running
 Container hl-s1-api-sse-fixture-1 Waiting
 Container hl-s1-block1-web-db-1 Waiting
 Container hl-s1-api-sse-fixture-1 Healthy
 Container hl-s1-block1-web-db-1 Healthy
 Container hl-s1-web-lab-test-run-d390fa7db7ae Creating
 Container hl-s1-web-lab-test-run-d390fa7db7ae Created
=== RUN   TestLabCancellationThroughPython
    api_lab_integration_test.go:65: no se alcanzó la barrera: {Rows:[] CacheWrites:0 Posts:1 ProviderActive:true ProviderClosed:false Writing:false WriteClosed:false Committed:0 ResponseClosed:false}
--- FAIL: TestLabCancellationThroughPython (3.08s)
FAIL
FAIL	estimator-web/internal/web	3.088s
FAIL

[heavy] s1-lab liberado rc=1 15:18:40
```

Después de la corrección (`complete_while_connected`):

```
[heavy] s1-lab esperando 15:19:41
[heavy] s1-lab adquirido 15:19:41
time="2026-11-26T15:19:41Z" level=warning msg="Found orphan containers (hl-s1-api-db-1) for this project. If you removed or renamed this service in your compose file, you can run this command with the --remove-orphans flag to clean it up."
 Container hl-s1-block1-web-db-1 Running
 Container hl-s1-api-sse-fixture-1 Running
 Container hl-s1-block1-web-db-1 Waiting
 Container hl-s1-api-sse-fixture-1 Waiting
 Container hl-s1-api-sse-fixture-1 Healthy
 Container hl-s1-block1-web-db-1 Healthy
 Container hl-s1-web-lab-test-run-42a0c97fefc2 Creating
 Container hl-s1-web-lab-test-run-42a0c97fefc2 Created
=== RUN   TestLabCancellationThroughPython
--- PASS: TestLabCancellationThroughPython (0.09s)
PASS
ok  	estimator-web/internal/web	0.093s
[heavy] s1-lab liberado rc=0 15:20:01
```

### Paridad funcional final (14.2)

```
[heavy] s1-paridad esperando 15:28:05
[heavy] s1-paridad adquirido 15:28:05
time="2026-11-26T15:28:05Z" level=warning msg="Found orphan containers (hl-s1-web-db-1) for this project. If you removed or renamed this service in your compose file, you can run this command with the --remove-orphans flag to clean it up."
 Container hl-s1-parity-check-run-203c3320672b Creating
 Container hl-s1-parity-check-run-203c3320672b Created
OK    inicio-navegacion — React 6, contrato Go 1, HTML retiradas 2, conservadas 0
OK    indicador-primario — React 4, contrato Go 10, HTML retiradas 5, conservadas 0
OK    estimacion-formulario — React 5, contrato Go 2, HTML retiradas 4, conservadas 0
OK    estimacion-adjuntos — React 4, contrato Go 2, HTML retiradas 4, conservadas 0
OK    estimacion-errores — React 2, contrato Go 2, HTML retiradas 5, conservadas 0
OK    resultado — React 5, contrato Go 2, HTML retiradas 5, conservadas 0
OK    conversacion — React 9, contrato Go 2, HTML retiradas 5, conservadas 0
OK    historial-estimaciones — React 6, contrato Go 2, HTML retiradas 5, conservadas 0
OK    barra-contexto — React 6, contrato Go 1, HTML retiradas 5, conservadas 0
OK    ajustes-lectura — React 2, contrato Go 1, HTML retiradas 4, conservadas 0
OK    ajustes-guardado — React 5, contrato Go 4, HTML retiradas 8, conservadas 0
OK    lab-formulario — React 1, contrato Go 1, HTML retiradas 2, conservadas 0
OK    lab-ejecucion — React 5, contrato Go 7, HTML retiradas 4, conservadas 0
OK    lab-errores — React 2, contrato Go 2, HTML retiradas 4, conservadas 0
OK    lab-resultados — React 3, contrato Go 2, HTML retiradas 2, conservadas 0
OK    lab-historial — React 5, contrato Go 4, HTML retiradas 5, conservadas 1
OK    denegacion-administrativa — React 6, contrato Go 3, HTML retiradas 1, conservadas 1
Filas: 17. Pruebas vigentes exigidas: 124. Referencias HTML retiradas: 70, conservadas: 2. Go ejecutadas: 230. React ejecutadas: 175.
[heavy] s1-paridad liberado rc=0 15:28:05
```

### Propósitos de las especificaciones revisados al sincronizar

La revisión de propósitos obsoletos se aplicó a las especificaciones principales al sincronizar los deltas (2026-11-26):
`http-streaming`, `web-client`, `web-backend-go`, `prompt-preview`, `web-client-contexts`, `web-react-client`,
`structured-estimation`, `deployment-stack`, `web-ai-settings` y `web-chunking-lab`. El requisito obsoleto de cookies se resolvió
en el delta de `web-backend-go`: Go no emite cookies y expira la legada `_estimator_web_session` sin interpretarla (escenario
«Cookie legada»).

## Limitaciones y deuda técnica aceptadas

- Autenticación y roles reales: pendientes de `homelab-authentication-authorization`.
- `sshd` del host (`0.0.0.0:22`) es alcanzable desde los contenedores por el gateway; el aislamiento de Docker no sustituye a un
  firewall del host. El endurecimiento queda para la fase de seguridad del homelab.
- El pipeline remoto de GitHub Actions no se ejecutó sobre el checkpoint final (el workflow solo se dispara con push a `master`
  o pull request).
- Las observaciones menores del revisor independiente: arneses con rutas de máquina (resuelto en la refactorización), aserción laxa de
  «sin reintentos de POST» en el flujo de errores, comprobación laxa de las rutas HTML antiguas (cubierta por pruebas de Go).
- `web-react-client` conserva un requisito titulado «Rutas equivalentes a la web Rails» que ningún delta modificó.
- `session-11-calidad-generacion-rag` conserva su fallo heredado (sin deltas) y no forma parte de este cambio.

## Refactorización de los arneses (posterior al archivado)

Los arneses de verificación vivían en esta carpeta y dependían de snapshots, imágenes y evidencias locales. Se movieron a
`verification/` (README con los procedimientos), con nombres técnicos y reproducibles desde un clon limpio:

| Origen (en esta carpeta, commit `1ef22c4c72ff72efcd71df7fe1fdff5ef043c14c`) | Destino |
|---|---|
| `verificar-red-bloque4.sh`, `compose.bloque4.yml` | `verification/verify-network.sh`, `verification/compose.network.yml` |
| `verificar-compose-bloque4.mjs` y su prueba | `verification/topology-check.mjs`, `topology-check.test.mjs` |
| `sonda-red-bloque4.mjs`, `proveedor-simulado.mjs` | `verification/probe-network.mjs`, `https-provider-fake.mjs` |
| `verificar-e2e-bloque6.sh`, `compose.bloque6.yml`, `e2e-bloque6.mjs`, `openai-simulado.mjs` | `verification/verify-e2e.sh`, `compose.e2e.yml`, `e2e.mjs`, `openai-fake.mjs` |
| `compose.caracterizacion.yml`, `compose.bloque2.yml`, `compose.bloque3.yml` (servicios útiles), `compose.bloque6-lab.yml`, `preparar-*.py` | `verification/compose.integration.yml`, `compose.nginx.yml`, `prepare.sh` |
| `paridad-bloque3.json`, `verificar-paridad-bloque4.mjs`, `compose.bloque4-paridad.yml` | `verification/parity.json`, `parity-check.mjs`, `verify-parity.sh` |
| `nginx-check.mjs`, `nginx-fixture.mjs` | `verification/nginx-check.mjs`, `nginx-fixture.mjs`, `verify-nginx.sh` |
| `estimador-cag/tests/block2_sse_fixture.py`, variable `BLOCK2_SSE_FIXTURE_URL` | `estimador-cag/tests/integration_fixture.py`, `PYTHON_FIXTURE_URL` |

Los resultados de esta refactorización (verificaciones ligeras y validación dinámica) figuran a continuación; no modifican los
resultados históricos de los bloques anteriores.

### Fase 1: verificaciones ligeras (sin construir imágenes ni levantar la pila)

Realizadas tras mover los arneses a `verification/` y renombrar el fixture de Python y su variable de entorno; los arneses
originales se conservaron en esta carpeta hasta validar la fase 2 (ver abajo).

| Comprobación | Resultado |
|---|---|
| Sintaxis de los siete scripts `.sh`, de los diez `.mjs` y de `integration_fixture.py` | Correcta |
| Autopruebas de topología (`topology-check.test.mjs`) | 20 de 20 |
| Render de `docker compose config`: raíz + `compose.network.yml` (perfil `probes`), + `compose.e2e.yml` (perfiles `e2e`, `e2e-fixture`, `probes`), `docker-compose.verify.yml` solo y con `compose.integration.yml`, `compose.nginx.yml` y el Compose secundario | Correcto en todas |
| `verify-network.sh static` desde un directorio ajeno al repositorio (rutas relativas a la raíz) | Topología sin fallos y 20 autopruebas aprobadas |
| Dependencias históricas en `verification/` (`.block*`, imágenes `homelab-block1-*`, rutas absolutas de la máquina, rutas del archivo OpenSpec) | Ninguna; solo el enlace del README a `verification.md` |
| Ningún Compose, script, prueba o CI accede al cambio archivado | Confirmado; solo hay enlaces documentales a `verification.md` en `AGENTS.md`, `README.md` y `EVIDENCIA-RETIRADA-HTML.md` |
| `git diff --check` y `openspec validate --all --strict` | Limpio; 57 de 58 (solo el fallo heredado de `session-11-calidad-generacion-rag`) |

### Fase 2: validación dinámica desde un clon limpio

Ejecutada el 2026-11-26 sobre un clon local del commit de la fase 1 (`git clone --no-hardlinks`), sin `.block*`, sin `.env`, sin
`.verification/` y sin evidencias previas, con `PROJECT=verify-p2` y `HEAVY_LOCK` compartido. Las imágenes se construyeron desde los
Dockerfile versionados reutilizando capas de la caché de Docker (las 31 etapas de la construcción de la pila resultaron `CACHED`), de modo que
la reproducibilidad de la construcción queda demostrada para las definiciones, no para una construcción sin caché. Los comandos fueron:

```bash
verification/prepare.sh --build && verification/verify-integration.sh run && verification/verify-parity.sh && verification/verify-nginx.sh run
verification/verify-network.sh {static,stack,persistence,network} && verification/verify-e2e.sh {stack,flows,backend-down,cancellation}
# y `clean` en cada arnés (solo down -v del proyecto)
```

| Grupo | Resultado |
|---|---|
| Preparación | Descarga real de `cl100k_base.tiktoken` con SHA-256 `223921b7…b2a7`; reutilización con hash correcto; un archivo corrompido se sustituye por una descarga verificada; un hash esperado incorrecto aborta con error y sin escribir archivo |
| `gofmt` / `go vet` (`web-lint`) tras el renombrado del fixture | Sin diagnósticos |
| Integración Go↔Python | 3 de 3 (`TestSSECancellationThroughPython` con 4 escenarios, `TestRESTCancellationThroughPython`, `TestLabCancellationThroughPython`) |
| Paridad | 17 filas, 124 pruebas vigentes exigidas; Go ejecutó 230 y React 175; 70 referencias HTML retiradas y 2 conservadas |
| Nginx | 33 de 33 comprobaciones y negativa a arrancar con plazos incoherentes |
| Red | Autopruebas 20 de 20 y topología sin fallos; 6 servicios saludables; persistencia tras reiniciar sin borrar volúmenes; 43 comprobaciones de matriz OK más la entrada informativa de `sshd`; salida HTTPS al proveedor simulado, sin claves de proveedor en Go, React ni bases de datos |
| Extremo a extremo | 39 de 39 flujos, 3 de 3 con Python detenido, 8 de 8 de cancelación |

La evidencia del túnel SSH desde Windows se mantiene: la configuración funcional que la sustenta no cambió.

Defectos de los arneses portados detectados y corregidos durante la validación (sin tocar la aplicación ni reducir aserciones):

1. `compose.nginx.yml`, usado solo, resolvía sus rutas relativas desde `verification/`; `verify-nginx.sh` fija ahora `--project-directory` en la raíz.
2. El alias y el certificado del proveedor HTTPS simulado (`proveedor-simulado.test`) no coincidían con el nombre que consulta `verify-network.sh network`; ambos pasan a `https-provider-fake.test`.

Tras la validación se eliminaron de esta carpeta los 22 archivos históricos de arneses sustituidos (siete `compose.*.yml`, `preparar-bloque2.py`,
`preparar-fuentes.py`, `verificar-*.mjs|.sh`, `sonda-red-bloque4.mjs`, `proveedor-simulado.mjs`, `e2e-bloque6.mjs`, `openai-simulado.mjs`,
`nginx-*.mjs` y `paridad-bloque3.json`). Se recuperan desde Git en `1ef22c4c72ff72efcd71df7fe1fdff5ef043c14c` (ruta
`openspec/changes/archive/2026-11-26-homelab-route-clients-through-go/`). La carpeta contiene ahora solo `.openspec.yaml`, `proposal.md`,
`design.md`, `tasks.md`, `specs/` (11 deltas) y `verification.md`.
