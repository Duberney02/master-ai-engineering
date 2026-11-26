# Verificación del Bloque 2

Base `0b9ee672b9a644a201ca60596786009bafc23ca8`. La caracterización original, sus imágenes y sus redes se conservan. Se reutilizan los entornos de ejecución de Python 3.11.18, Go 1.25.14 y Node 22.23.5. Los manifiestos y locks son los de la base aprobada.

## Entorno y reproducción

El proyecto `homelab-block2-clientes-go` usa redes propias con gateway de puente aislado, bases en `tmpfs`, dependencias de imágenes locales y montajes de solo lectura. Los servicios de lint y React usan `network_mode: none`. El fixture SSE escucha solo en la red interna y solo existe en el Compose de verificación. Usa proveedores simulados y la base PostgreSQL efímera de Python. El vocabulario verificado por SHA-256 se prepara siguiendo [la receta del Bloque 1](caracterizacion.md#reproducción-de-la-parte-c).

Desde la raíz, comprobar el contador EXT4 y los mensajes del kernel antes y después de cada fase. Ejecutar cada comando de prueba hasta su final antes de iniciar el siguiente. Verificar etiquetas de proyecto y servicio, red, salud, ausencia de puertos publicados y montaje de datos en `tmpfs` al iniciar cada base. Confirmar la titularidad antes de retirar los contenedores creados por esta ejecución.

```bash
d=openspec/changes/homelab-route-clients-through-go
python3 "$d/preparar-bloque2.py"
mkdir -p .block2/evidencias
export COMPOSE_REMOVE_ORPHANS=false
c=(docker --config .block2/docker-config --host unix:///var/run/docker.sock compose
   --env-file /dev/null -p homelab-block2-clientes-go
   -f docker-compose.verify.yml -f "$d/compose.caracterizacion.yml" -f "$d/compose.bloque2.yml")

"${c[@]}" config --quiet
"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 60 block1-web-db
"${c[@]}" run --rm --no-deps --pull never -T web-test -timeout=90s -count=1 -json ./...
"${c[@]}" stop block1-web-db
"${c[@]}" rm -f block1-web-db

"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 60 block1-api-db
"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 45 api-sse-fixture
"${c[@]}" run --rm --no-deps --pull never -T web-sse-test
"${c[@]}" stop -t 2 api-sse-fixture
"${c[@]}" rm -f api-sse-fixture
"${c[@]}" stop block1-api-db
"${c[@]}" rm -f block1-api-db

"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 60 block1-api-db
"${c[@]}" run --rm --no-deps --pull never -T api-test -v \
  tests/test_main.py tests/test_sessions_api.py tests/test_project_estimations.py \
  tests/test_history.py tests/test_history_conversation.py tests/test_history_postgres.py \
  tests/test_config_api.py tests/test_sse_and_options.py tests/test_llm_service_streaming.py \
  tests/test_stream_disconnect.py tests/test_layer_dependencies.py tests/test_architecture.py
"${c[@]}" stop block1-api-db
"${c[@]}" rm -f block1-api-db
"${c[@]}" run --rm --no-deps --pull never -T api-lint check app/api/disconnect.py app/api/project_estimations.py app/api/sessions.py \
  tests/block2_sse_fixture.py tests/test_stream_disconnect.py
"${c[@]}" run --rm --no-deps --pull never -T --entrypoint sh web-lint -ec \
  'go version; pending=$(gofmt -l .); test -z "$pending" || { printf "%s\n" "$pending"; exit 1; }'
"${c[@]}" run --rm --no-deps --pull never -T --entrypoint go web-lint vet ./...
"${c[@]}" run --rm --no-deps --pull never -T react-test npm test -- --maxWorkers=1 --reporter=verbose
```

## Alcance de la evidencia

- REST. Servidores HTTP simulados verifican método y destino, UUID, contenido JSON y de formularios, representación de campos nulos y aditivos, límites, Unicode, errores saneados, salud independiente y cancelación de la solicitud HTTP upstream.
- SSE unitario. Un upstream HTTP simulado retiene eventos con barreras y comprueba que el primer evento ya llegó al cliente, incluso con fragmentación, comentarios, CRLF y datos multilínea. Los casos de error previo y terminal, EOF, secuencia incorrecta, tamaño, inactividad y plazo total verifican que Go no sintetiza `done`.
- Python aislado. Las pruebas ASGI del Bloque 1 se conservan y comprueban la desconexión de FastAPI durante la generación estructurada y tras un token de transcripción.
- Integración Go→Python. El cliente consume el handler Go en un servidor TCP y este llama a FastAPI/Uvicorn real en otra instancia. El fixture observa la finalización explícita del proveedor simulado, el cierre del generador y la escritura del historial real en PostgreSQL efímero. Para la interrupción durante la escritura, pausa después de `flush` y antes de `commit`. Una lectura independiente comprueba cero filas confirmadas. Tras `result`, el fixture retiene el siguiente evento y comprueba que la fila confirmada permanece. Los dobles de caché solo cuentan resultados completos del pipeline real. Esta prueba no incluye React ni Nginx.
- Autorización. La composición habitual carece de decisión que conceda administración. El servidor verifica la decisión por operación antes de entrar a los handlers HTML o al transporte JSON administrativo. El fake se asigna desde los tests. El transporte JSON administrativo queda registrado para denegar accesos en esta etapa. Sus operaciones se implementarán en el bloque correspondiente.

## Resultados de la regresión

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

## Correcciones tras la revisión técnica

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
