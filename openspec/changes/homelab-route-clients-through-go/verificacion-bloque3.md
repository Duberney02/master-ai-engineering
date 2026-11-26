# Verificación del Bloque 3

Base `e96398d620992d38f0270e111beebb1a1d759db7` (rama `feature/homelab-integration`). Cubre las tareas 6.1 a 9.2: comunicaciones de React, Ajustes de IA, Chunking Lab y paridad. Reutiliza las imágenes del Bloque 1 (Python `4062b6ded3c1`, Go `45171af038d7`, React `483dc26b02bd`, PostgreSQL Go `f9cf3e1f0066`, pgvector `b513c48566e4`) y la imagen `nginxinc/nginx-unprivileged:stable-alpine` ya presente. No se descargó ni construyó nada con red.

## Entorno y reproducción

El proyecto `homelab-block3-clientes-go` monta las fuentes vigentes en solo lectura (los snapshots verificados de `.block1/` y `.block2/` no se tocan), usa bases en `tmpfs` dentro de redes internas con gateway aislado, claves ficticias y `network_mode: none` en lint, React y la matriz de paridad. nginx, su upstream simulado y su comprobador viven en la red interna `block3-edge`. Antes y después de cada fase se consultó `/sys/fs/ext4/sda2/errors_count` (0 en todas las lecturas).

```bash
d=openspec/changes/homelab-route-clients-through-go
export COMPOSE_REMOVE_ORPHANS=false
c=(docker --config .block3/docker-config --host unix:///var/run/docker.sock compose --env-file /dev/null
   -p homelab-block3-clientes-go -f docker-compose.verify.yml -f "$d/compose.caracterizacion.yml" -f "$d/compose.bloque3.yml")
mkdir -p .block3/docker-config .block3/evidencias && echo '{}' > .block3/docker-config/config.json

# Go: suite completa con PostgreSQL efímero, en JSON para la matriz
"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 60 block1-web-db
"${c[@]}" run --rm --no-deps --pull never -T web-test -timeout=180s -count=1 -json ./... > .block3/evidencias/go-test.json
# Go → FastAPI real (Bloque 2), con las fuentes vigentes
"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 60 block1-api-db api-sse-fixture
"${c[@]}" run --rm --no-deps --pull never -T web-sse-test
# Lint y compilación
"${c[@]}" run --rm --no-deps --pull never -T --entrypoint sh web-lint -ec 'test -z "$(gofmt -l .)"'
"${c[@]}" run --rm --no-deps --pull never -T --entrypoint go web-lint vet ./...
"${c[@]}" run --rm --no-deps --pull never -T react-build
# React (Vitest) en JSON para la matriz
"${c[@]}" run --rm --no-deps --pull never -T react-test sh -c 'npx vitest run --reporter=json --outputFile=/tmp/v.json --maxWorkers=1 >/dev/null 2>&1; s=$?; cat /tmp/v.json; exit $s' > .block3/evidencias/vitest.json
# Python (sin cambios en este bloque) y matriz de paridad
"${c[@]}" run --rm --no-deps --pull never -T api-test
"${c[@]}" run --rm --no-deps --pull never -T api-lint check .
"${c[@]}" run --rm --no-deps --pull never -T parity-check
# nginx delante de un upstream simulado de Go
"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 90 block3-nginx
"${c[@]}" run --rm --no-deps --pull never -T block3-nginx-check
"${c[@]}" run --rm --no-deps --pull never -T block3-nginx-bad   # debe fallar al arrancar
```

## Resultados

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

## Qué se verifica y con qué

- **6.1 · Proxy hacia Go.** Compose, Dockerfile, plantilla de nginx y `vite.config.ts` dirigen `/api` y `/health` a Go. `src/test/viteConfig.test.ts` fija destino, orden de reglas, plazos 35/615 s y su validación. `nginx-check.mjs` comprueba contra un upstream simulado, con barreras y sin pausas arbitrarias: el primer evento de cada ruta SSE llega al cliente antes de que el upstream emita el resto, cabeceras SSE y de seguridad, sin compresión; el cierre del cliente llega al upstream en las dos rutas SSE y en las dos largas con un único POST; la clasificación por plazos (habitual 504 a los 2 s, largas y SSE silenciosas más allá del habitual, SSE inactivo cortado al plazo largo); 413 con 56 MiB y paso con 54 MiB; `X-Forwarded-For` reescrito y `Host` del upstream; `/health` reenviado y `/healthz` local.
- **6.2 · Contratos y cancelación.** `AbortSignal` llega a `fetch` en estimaciones y sesión. Pruebas: cancelar rehabilita el formulario, no muestra resultado parcial, conserva el borrador y no reenvía; salir de la pantalla aborta; una señal ya abortada no envía; el 404 de sesión conserva el borrador y no reenvía; rechazos locales conservan el borrador; plazos 40/630 s coordinados.
- **7.1–7.3 · Ajustes e indicador.** Go proyecta el catálogo con `null`, filtra por proveedor, envía todos los campos, convierte vacío en `null`, no llama a IA sin campos reconocidos y sanea los `detail`. La atomicidad pertenece a IA (`tests/test_config_api.py::test_put_is_all_or_nothing`, incluida en la ejecución de Pytest). `primary-model` es general, expone solo el nombre y cachea valor, ausencia y fallo 15 s. Las pruebas deterministas de la caché usan barreras: lecturas concurrentes comparten una consulta, la consulta en vuelo invalidada no se almacena, el contexto del primer lector no cachea una ausencia falsa y los lectores cancelados no esperan. React cubre selectores, embeddings de solo lectura, confirmación, rechazo, reintento, estado restringido, `aria-current`, enlace del indicador solo tras acceso concedido e inicio utilizable sin servicios.
- **8.1–8.3 · Lab.** Opciones y comparación con las ocho estrategias, `top_k` omitido = 3 y enteros acotados a 1–10 (también fuera de 64 bits), decimales/exponentes/cadenas/booleanos/`null` = 422, consultas sin tope propio (1 500 consultas y una de 20 000 caracteres intactas), mapeo completo de errores, plazo propio, 201 con `Location` o 200 con ID nulo, cancelación hasta IA sin escritura, y atomicidad en PostgreSQL. Listado de 20, indisponibilidad, 404/500. `TestLabLargeIDsKeepExactDigitsThroughGoAndPostgreSQL` siembra el ID 9007199254740993, avanza la secuencia y crea el 9007199254741001; alta, `Location`, listado y detalle conservan los dígitos tras reiniciar el servidor, y PostgreSQL mantiene `bigint` y el valor. React usa los IDs como texto (ruta y detalle con dígitos exactos) y rechaza un ID numérico en el JSON.
- **9.1–9.2 · Paridad y corte.** `paridad-bloque3.json` enlaza cada capacidad HTML con su prueba HTML de referencia (que sigue pasando, porque el HTML se conserva), su recorrido React y su contrato Go. `verificar-paridad.mjs` falla si una referencia no existe, no pasó o fue omitida. Bloqueo en composición normal: `TestAdministrativeOperationsDenyBeforeEffects`, `TestNormalCompositionDeniesEveryAdministrativeRouteWhateverTheClientSends` y `TestNoProductionCodeEnablesAnAdministrativeDecision`, más la comprobación del binario real. Evidencia de aprobación del corte: esta tabla y las dos salidas de la matriz; no depende de un sistema de identidad.

## Limitaciones y observaciones

- Sin detector de carreras: la imagen de pruebas no tiene `gcc` y no hay red. La concurrencia de la caché se verifica con barreras deterministas, no con `-race`.
- Tras nginx, Go solo acepta mutaciones del navegador si `ESTIMATOR_PUBLIC_ORIGIN` coincide con el origen visto por el navegador (el Compose lo fija a `http://localhost:3001`). El recorrido React → Nginx → Go real con IA simulada corresponde a la tarea 14.1.
- No se construyó la imagen de producción de React: la base `node:22-alpine` no está en local y no hay red. Se verifican la plantilla, el script de plazos y las variables de entorno con la imagen estándar de nginx y el `Dockerfile` como texto.
- Se conservan íntegros el HTML de Go y Streamlit, que sigue apuntando a la API de IA hasta los bloques posteriores.
