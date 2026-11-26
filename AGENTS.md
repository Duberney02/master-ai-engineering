# Guía compartida del repositorio

Monorepo del máster en AI Engineering para un estimador de proyectos con IA. Codex lee este archivo directamente y Claude Code lo importa desde `CLAUDE.md`.

## Estructura y arquitectura implementada

- `estimador-cag/`: API de IA en Python 3.11 con FastAPI y uv. Contiene la lógica de estimación, CAG, RAG, agentes, conversación e ingesta. Solo Go la llama. Consulta [la arquitectura del servicio](estimador-cag/ARCHITECTURE.md).
- `estimator-web-go/`: servicio `estimator-web`, backend HTTP de aplicación. Expone la API REST y SSE pública con `net/http`, rutas explícitas y errores tipados, decide la autorización de las operaciones administrativas (denegadas por defecto), llama por HTTP a la API de IA y persiste el historial del Chunking Lab en su PostgreSQL. No sirve HTML. Consulta [la arquitectura de Go](estimator-web-go/ARCHITECTURE.md).
- `estimator-web-react/`: único cliente web, React y TypeScript servido por Nginx. Habla solo con Go por su propio origen.
- El Compose raíz define seis servicios: React/Nginx, Go, `estimador-cag`, PostgreSQL de Go, PostgreSQL con pgvector para IA y Redis Stack. Cinco redes: `client-net` (React y Go, sin NAT de salida), `service-net`, `go-data-net` y `ai-data-net` (internas) y `ai-egress-net` (solo la IA). Solo React/Nginx publica puerto: `127.0.0.1:3001`. La configuración actual admite OpenAI y Anthropic para generación y usa OpenAI para embeddings. La reutilización de infraestructura del homelab y el soporte de Ollama son objetivos de integración futuros.
- Estado: entorno **privado de desarrollo**, validado en una pila temporal de pruebas, no un despliegue de producción. Solo lo usa el operador autorizado mediante túnel SSH, sin exposición pública ni uso multiusuario hasta completar `homelab-authentication-authorization`. Go deniega por defecto las operaciones administrativas (Ajustes de IA y Chunking Lab) con 403 saneado. Los mecanismos de autorización de prueba existen solo en pruebas y nunca en la imagen normal.
- `examples/`: ejemplos y trazas. [El diagnóstico de arquitectura](arquitectura-actual.md) es un documento histórico que retrata el cierre de la Sesión 08. Para la arquitectura vigente consulta este archivo, la arquitectura de cada servicio y los deltas y el informe de verificación de `openspec/changes/archive/2026-11-26-homelab-route-clients-through-go/`.
- `openspec/`: especificaciones en `specs/` (capacidades en `specs/estimator/`), cambios en `changes/` y archivo en `changes/archive/`. Las habilidades de ambos asistentes viven en `.agents/skills/` y `.claude/skills/`.

## Arquitectura objetivo aprobada

Estas decisiones rigen los próximos cambios de integración. Su implementación requiere cambios OpenSpec propios.

| Decisión | Restricción |
|---|---|
| DA-01 · Windows como cliente | Usar Windows exclusivamente con VS Code Remote SSH y navegador. El flujo prescinde de Docker Desktop, Node.js, Python, Go y una copia local del repositorio en Windows. |
| DA-02 · Homelab centralizado | Alojar el código fuente, las herramientas, las aplicaciones y la infraestructura en el homelab. |
| DA-03 · Comunicación de clientes | React, único cliente web, llama exclusivamente al backend Go. Se prohíbe el acceso directo desde el cliente a `estimador-cag`, PostgreSQL, Redis u Ollama. Streamlit se retiró (DA-18). |
| DA-04 · Entrada por Go | Entre los componentes de aplicación, solo Go llama a `estimador-cag`. Go intermedia y toda la lógica de IA permanece en `estimador-cag`. |
| DA-05 · Generación | Soportar Ollama, Anthropic y OpenAI mediante abstracciones que mantengan la lógica de negocio independiente del proveedor. |
| DA-06 · Credenciales | Las credenciales de proveedores de IA se inyectan exclusivamente en `estimador-cag`. Nunca exponerlas a Go ni a React ni versionar secretos, tokens, claves API o credenciales. |
| DA-07 · Infraestructura existente | Reutilizar PostgreSQL, pgvector y Ollama del homelab cuando sea seguro. Mantener bases y usuarios independientes por responsabilidad y evitar instancias redundantes. |
| DA-08 · Redis Stack | Mantener Redis Stack y las capacidades RediSearch que usan funcionalidades como la caché semántica. |
| DA-09 · Docker y OpenSpec | Usar Docker y Docker Compose para desarrollar, gestionar dependencias, compilar, probar, ejecutar, verificar, aplicar lint y desplegar las aplicaciones. Especificar y planificar con OpenSpec antes de implementar cambios funcionales o arquitectónicos. |
| DA-10 · Generación y embeddings | Configurar proveedor y modelo por separado para cada función. Anthropic participa solo en generación. Nunca mezclar espacios de modelos de embeddings distintos, incluso si tienen la misma dimensión. |
| DA-11 · Herramientas nativas | Git, Claude Code, Codex CLI, NVM, Node.js, npm, OpenSpec, Docker y Docker Compose pueden instalarse y ejecutarse en Ubuntu. Node.js nativo sirve para herramientas de desarrollo como OpenSpec. El ciclo de las aplicaciones se ejecuta en Docker. |
| DA-12 · Instrucciones compartidas | Mantener la guía común en `AGENTS.md` y las particularidades de cada asistente en su propia configuración. `CLAUDE.md` importa `AGENTS.md` mediante `@AGENTS.md`. |
| DA-13 · Habilidades versionadas | Versionar esta guía, `CLAUDE.md`, `.agents/skills/` y `.claude/skills/`, junto con la configuración compartida pertinente. Excluir ajustes personales, permisos locales y secretos, como `.claude/settings.local.json`. Mantener ambos juegos de habilidades sincronizados con la misma versión de OpenSpec y regenerarlos con el CLI, sin ediciones manuales. |
| DA-14 · OpenSpec reproducible | Usar OpenSpec 1.13.2 en Ubuntu y en Docker. Priorizar el CLI nativo para desarrolladores y asistentes. Mantener el servicio Compose existente para validaciones reproducibles, CI/CD y entornos sin Node.js u OpenSpec nativos. Usar Docker Compose directamente, sin wrappers adicionales. |
| DA-15–17 y DA-19 · Frontera y matriz HTTP | Cada operación pública tiene un handler explícito en Go y un método por contexto en `internal/estimatorai`. Sin proxy genérico: una ruta desconocida responde 404 y un método no admitido, 405, sin llamar a la IA. Go valida método, ruta, tipo, tamaño y sintaxis; Python conserva las reglas de negocio. Los contratos REST y SSE conservan campos, tipos y errores saneados (503 conexión, 504 plazo, 502 respuesta inválida). `/health` mide el camino Go→IA, `/up` es la sonda local de Go y `/healthz` la de Nginx. La vista previa del prompt es informativa. |
| DA-18 · Retirada de Streamlit | Streamlit, su dependencia, su servicio, su puerto y la demo HTML de Python quedan retirados; se conservan las rutas SSE. |
| DA-20–21 · Streaming y plazos | Go reenvía SSE con flush por evento, sin sintetizar `done` ni reintentar. La cancelación de React llega hasta Python y libera al proveedor sin persistir resultados parciales; una escritura ya confirmada puede conservarse. Plazos configurables por operación (conexión 5 s; 30 s habituales y 600 s largas en Go; 5/35/615 s en Nginx). |
| DA-22–23 · Superficie, redes y seguridad | Redes `client-net`, `service-net`, `go-data-net`, `ai-data-net` y `ai-egress-net`. Solo React/Nginx publica `127.0.0.1:3001`. Límites de 55 MiB de multipart, cinco archivos de 10 MiB y 1 MiB de JSON por operación. Mutaciones de navegador validadas contra `ESTIMATOR_PUBLIC_ORIGIN`. Las pruebas usan proyectos Compose propios y nunca tocan PostgreSQL, Ollama, Open WebUI ni otros recursos preexistentes. El aislamiento de Docker no sustituye a un firewall del host: los servicios del host que escuchan en todas las interfaces (p. ej. `sshd`) son alcanzables desde los contenedores. |
| DA-24–25 · Paridad y corte | El HTML de Go se retiró tras demostrar la paridad en React (Ajustes de IA, indicador del modelo primario y Chunking Lab incluidos) con evidencia en Docker. La cookie legada `_estimator_web_session` ya no se emite y solo se expira si el navegador la envía. |
| DA-26 · Autorización | Go decide la autorización de cada operación administrativa, lecturas incluidas, antes de leer datos, cachés, IA o PostgreSQL. La composición normal deniega con 403 saneado. Configuración, catálogo y Chunking Lab están reservados al rol futuro `admin`; la proyección del modelo primario es de lectura general. Los fakes de decisión existen solo en pruebas. Autenticación, roles y aislamiento por usuario quedan en `homelab-authentication-authorization`. |
| DA-27 · IDs del Lab | Los IDs de comparación se serializan como cadenas decimales (alta, listado, detalle y `Location`); PostgreSQL conserva tipo, precisión y valor. |
| DA-28 · `top_k` del Lab | El valor por defecto es 3 y el intervalo, 1–10; es exclusivo del Chunking Lab. |

Combinaciones objetivo de generación y embeddings, respectivamente: Anthropic/Ollama, OpenAI/Ollama, Ollama/OpenAI, Ollama/Ollama y OpenAI/OpenAI. Un cambio de modelo de embeddings debe contemplar la identificación del proveedor y modelo, dimensionalidad, compatibilidad de los índices vectoriales, persistencia, reindexación, caché semántica y migración de datos existentes. No asumir que el cambio puede aplicarse en caliente a datos persistidos.

## Límites entre capas

En `estimador-cag/app/`, define la configuración en `config.py`, sitúa todas las fábricas de dependencias en `dependencies.py` (composition root) y mantén la fábrica FastAPI y el montaje de la aplicación en `main.py`.

| Capa | Responsabilidad e importaciones permitidas |
|---|---|
| `foundation/` | Primitivas de LLM, prompts, guardrails, adjuntos y persistencia, sin decisiones de las estrategias de IA. Puede importar `config`. |
| `domain/schemas/` | Contratos con clientes. Puede importar `config` y `foundation`. |
| `domain/` | Conductor de estimación (`pipeline`, `session_estimation`, `acb`). Puede importar `config`, `foundation`, `domain` y `generation` para componer estrategias. |
| `generation/` | `cag`, `rag`, `agentic` y `conversation` pueden importar `config`, `foundation` y `domain.schemas`. Los módulos hermanos se reúnen en el conductor. Se conserva la excepción `agentic` → `conversation`. |
| `ingestion/` | Pipeline batch offline. Puede importar `config`, `foundation`, `domain.schemas` y `generation.rag`. |
| `api/` | Routers finos, sin lógica de negocio. Pueden importar `config`, `dependencies`, `domain`, `foundation`, `generation` e `ingestion`. |

`tests/test_layer_dependencies.py` comprueba estos límites y es la referencia para las excepciones heredadas. Conserva únicamente los pares de importación allí enumerados para `domain.schemas.sessions`, `foundation.guardrails.input`, `foundation.llm.service`, `foundation.llm.structured` y `foundation.prompts.loader`. Ninguna capa importa `app.main`. Solo `api/` puede importar `app.dependencies`. Evita añadir excepciones o nuevos cruces.

En Go, solo `internal/estimatorai` habla por HTTP con la API de IA y centraliza la traducción a errores tipados. Los contextos `rag`, `ai` y `estimation` se mantienen independientes y `internal/web` los compone con handlers de transporte. Respeta los límites comprobados por `internal/archtest` y mantén los contratos alineados con los schemas de Python.

## Convenciones técnicas y pruebas

- Usa atributos en minúsculas en `Settings` (pydantic-settings) y variables de entorno en mayúsculas.
- Usa SDK asíncronos (OpenAI, Anthropic, Redis, SQLAlchemy async). Evita bloquear el event loop.
- Preserva contratos aditivos. Mantén las rutas y la forma del JSON existentes que consumen Go (y, a través de él, React).
- Devuelve errores saneados. Excluye trazas, claves, URLs internas y cuerpos de proveedor de las respuestas. Registra el detalle en el log sin datos sensibles.
- Escribe documentación, artefactos OpenSpec, comentarios y mensajes para el usuario en español. Conserva en inglés los encabezados estructurales de OpenSpec y las palabras normativas SHALL/MUST.
- Usa fakes, `fakeredis`, mocks HTTP (`httptest` en Go) y datos simulados. Las pruebas automatizadas jamás usan claves reales ni llaman a proveedores de IA reales. Las pruebas de persistencia usan PostgreSQL efímero de Compose.
- Para parchear `get_settings`, parchea también `app.dependencies.get_settings` mediante `patch_settings` en `tests/_fakes.py`. `get_session_store` consulta `app.config.get_settings()` en vivo porque algunas pruebas configuran el entorno mediante variables.
- Sin `REDIS_URL`, la caché semántica se desactiva. Al habilitarla usa Redis Stack con RediSearch.
- Conserva el orden de los campos de `EstimationResult` para la salida estructurada. Reutiliza la expresión de `halfvec_embedding()` al consultar índices HNSW halfvec. La dimensión, el cast y el operador deben coincidir con el índice.

## Comandos desde la raíz

```sh
docker compose -f docker-compose.verify.yml run --rm api-test
docker compose -f docker-compose.verify.yml run --rm api-test tests/test_x.py -k nombre
docker compose -f docker-compose.verify.yml run --rm api-lint
docker compose -f docker-compose.verify.yml run --rm api-lint check . --fix
docker compose -f docker-compose.verify.yml run --rm api-uv lock
docker compose -f docker-compose.verify.yml run --rm web-test
docker compose -f docker-compose.verify.yml run --rm web-lint
docker compose -f docker-compose.verify.yml run --rm web-go mod tidy
docker compose -f docker-compose.verify.yml run --rm react-test
docker compose -f docker-compose.verify.yml run --rm react-build
docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
docker compose up --build
```

`api-test` ejecuta `pytest -q`, `api-lint` ejecuta Ruff, `web-test` ejecuta `go test -p 1 ./...`, `web-lint` comprueba gofmt y ejecuta go vet, `react-test` ejecuta Vitest y `react-build` ejecuta `tsc` y `vite build` (ambos sin red). Si cambia `pyproject.toml`, reconstruye la imagen de pruebas con `docker compose -f docker-compose.verify.yml build api-test`. Verifica los cambios de aplicaciones con pruebas y lint en Docker. Usa siempre un nombre de proyecto propio (`-p <nombre>`) en las pruebas para no compartir redes, volúmenes ni contenedores entre sesiones, y no limpies Docker globalmente.

El Compose raíz levanta la pila de integración: solo React/Nginx publica `127.0.0.1:3001`; Go (3000), la API de IA (8000), Redis y PostgreSQL no publican puertos y se inspeccionan con sondas internas (`docker compose exec`). Desde Windows se accede con `ssh -N -L 3001:127.0.0.1:3001 <usuario>@<servidor>` y el navegador en `http://localhost:3001`. `estimador-cag/docker-compose.yml` levanta solo el backend con recarga y sin puertos; su perfil explícito `diagnostico` publica `127.0.0.1:8000` fuera de la integración. Los proyectos creados desde esos directorios tienen volúmenes separados. Los arneses de validación (red, extremo a extremo, integración Go↔Python, paridad y Nginx) viven en `verification/` (ver su README; `verification/prepare.sh` los prepara desde un clon limpio) y solo operan sobre proyectos `verify-<nombre>`, con `PROJECT=verify-<nombre>` y, si varias sesiones comparten el host, `HEAVY_LOCK=<archivo>` para serializar las operaciones pesadas.

## OpenSpec, secretos y Git

- Consulta la [guía de OpenSpec](openspec/README.md) para instalar el CLI, invocar los seis workflows, validar y gestionar las habilidades. Usa el CLI nativo para planificación y valida antes del archivado. No invoques superpowers.
- Mantén cada cambio OpenSpec con sus artefactos de especificación (`.openspec.yaml`, `proposal.md`, `design.md`, `tasks.md`, `specs/`) y, si hace falta, un único `verification.md` consolidado. Ningún componente activo (Compose, script, prueba o CI) depende de un cambio archivado.
- Incorpora los arneses reutilizables a `verification/` o a los directorios de pruebas del servicio. Sus resultados, cachés y evidencias van a `.verification/` (ignorado por Git). No crees directorios temporales por funcionalidad en la raíz del repositorio.
- Tras validar y respaldar el trabajo, retira snapshots, logs y recursos temporales, y comprueba que no quedan residuos antes de cerrar la funcionalidad.
- Carga los secretos desde el entorno o archivos locales excluidos, como `.env`. Revisa que las configuraciones versionadas incluyan solo información compartida y que las credenciales de IA lleguen exclusivamente a `estimador-cag`.
- Verifica la rama y el estado de Git antes de editar. Trabaja en la rama indicada para la tarea, con `master` como base habitual, y preserva los cambios ajenos. Revisa el diff y el resultado de las verificaciones antes de preparar un commit. Agrega archivos, crea commits o publica cambios cuando la tarea lo autorice.
