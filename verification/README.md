# Arneses de verificación

Verificaciones que van más allá de `docker compose -f docker-compose.verify.yml run --rm api-test|web-test|react-test`:
topología y aislamiento de red, persistencia, recorridos de extremo a extremo con proveedores simulados, cancelación REST,
SSE y del Chunking Lab hasta Python, comportamiento de Nginx y paridad funcional. Todo se ejecuta en contenedores, con
claves ficticias, y funciona desde un clon limpio: no depende de snapshots, imágenes ni archivos de ninguna ejecución previa.

La evidencia de las 38 tareas del cambio `homelab-route-clients-through-go` está en
[`verification.md`](../openspec/changes/archive/2026-11-26-homelab-route-clients-through-go/verification.md).

## Estructura

| Archivo | Contenido |
|---|---|
| `lib.sh` | Funciones comunes: raíz del repositorio, proyecto `verify-*`, guardia de EXT4, `heavy` (flock opcional) |
| `prepare.sh` | Prepara `.verification/` (ignorado por Git) y, con `--build`, construye las imágenes |
| `verify-network.sh` | Topología, pila, persistencia y matriz de red (`compose.network.yml`, `topology-check.mjs`, `probe-network.mjs`, `https-provider-fake.mjs`) |
| `verify-e2e.sh` | Flujos, Python detenido y cancelación con barreras (`compose.e2e.yml`, `e2e.mjs`, `openai-fake.mjs`) |
| `verify-integration.sh` | Cancelación REST, SSE y del Lab de Go a Python real (`compose.integration.yml`, `estimador-cag/tests/integration_fixture.py`) |
| `verify-parity.sh` | Matriz de paridad (`parity.json`, `parity-check.mjs`) |
| `verify-nginx.sh` | Nginx sobre un upstream simulado (`compose.nginx.yml`, `nginx-check.mjs`, `nginx-fixture.mjs`) |

Los scripts resuelven las rutas respecto a la raíz del repositorio y pueden invocarse desde cualquier directorio.

## Puesta en marcha desde un clon limpio

```bash
verification/prepare.sh --build     # construye imágenes y prepara .verification/ (único paso con red: tiktoken y bases de imágenes)
```

`prepare.sh` crea `.verification/` con: credenciales ficticias de la IA, un certificado autofirmado efímero, los adjuntos
sintéticos (PDF y DOCX) y la caché `cl100k_base.tiktoken`. Esta se descarga de la fuente oficial de OpenAI
(`https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken`), se verifica contra el SHA-256
`223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7` (el `expected_hash` de `tiktoken_ext/openai_public.py`) y se
reutiliza si ya existe con ese hash. Si la descarga o la verificación fallan, el script termina con error. El archivo no se versiona.

Las imágenes de herramientas son `estimator-web-react:test`, `estimador-cag:test` y `estimator-web-go:test`
(`docker-compose.verify.yml`). Para reutilizar otras ya construidas: `VERIFY_NODE_IMAGE`, `VERIFY_API_IMAGE` y `VERIFY_GO_IMAGE`.

## Ejecución

```bash
PROJECT=verify-local verification/verify-network.sh static        # sin levantar la pila
PROJECT=verify-local verification/verify-network.sh stack
PROJECT=verify-local verification/verify-network.sh persistence
PROJECT=verify-local verification/verify-network.sh network
PROJECT=verify-local verification/verify-network.sh clean
PROJECT=verify-local verification/verify-e2e.sh stack && verification/verify-e2e.sh flows
PROJECT=verify-local verification/verify-e2e.sh backend-down
PROJECT=verify-local verification/verify-e2e.sh cancellation
PROJECT=verify-local verification/verify-e2e.sh clean
PROJECT=verify-local verification/verify-integration.sh run       # y `clean`
PROJECT=verify-local verification/verify-parity.sh
PROJECT=verify-local verification/verify-nginx.sh run             # y `clean`
node --test verification/topology-check.test.mjs                  # autopruebas del comprobador de topología (Node nativo opcional)
```

## Reglas de seguridad

- `PROJECT` debe ser `verify-<nombre>`: así los redes, volúmenes y contenedores son propios y nunca coinciden con la pila real
  ni con servicios del host. Cada ejecución paralela debe usar un `PROJECT` distinto.
- `clean` solo hace `down -v` del proyecto indicado. No se ejecutan limpiezas globales de Docker.
- Los arneses no usan proveedores de IA reales ni publican puertos salvo el `127.0.0.1:3001` de la propia pila.
- `HEAVY_LOCK=<archivo>` serializa las construcciones y regresiones pesadas con `flock`; úsalo cuando varias sesiones comparten el host.
- Las guardias consultan el contador de errores de EXT4 del disco del repositorio (si existe) y detienen la ejecución si aumenta.

## Limitaciones conocidas

- El aislamiento de Docker (redes internas, `client-net` sin NAT) no sustituye a un firewall del host: los servicios del host
  que escuchan en todas las interfaces (p. ej. `sshd`) son alcanzables desde los contenedores por el gateway. La matriz de
  `verify-network.sh network` lo registra como informativo.
- Estos arneses no forman parte de CI; CI ejecuta las suites de `docker-compose.verify.yml` y los controles de `.github/workflows/`.
- Go no tiene shell en su imagen: su posición de red se comprueba con una sonda en las mismas redes (`probe-go`).
- La autorización de pruebas de Go solo existe en el código de pruebas: en la pila real solo se comprueba el 403.
