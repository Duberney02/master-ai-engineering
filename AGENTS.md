# Guía compartida del repositorio

Monorepo del máster en AI Engineering para un estimador de proyectos con IA. Codex lee este archivo directamente y Claude Code lo importa desde `CLAUDE.md`.

## Estructura y arquitectura implementada

- `estimador-cag/`: API de IA en Python 3.11 con FastAPI y uv. Contiene la lógica de estimación, CAG, RAG, agentes, conversación e ingesta, además del chat Streamlit (`estimador-cag-chat` en Compose). Consulta [la arquitectura del servicio](estimador-cag/ARCHITECTURE.md).
- `estimator-web-go/`: servicio `estimator-web`, sustituto del cliente Rails original. Usa `net/http` y `html/template`, organiza los paquetes por contexto, llama por HTTP a la API de IA y persiste el historial del Chunking Lab en su PostgreSQL. Consulta [la arquitectura de Go](estimator-web-go/ARCHITECTURE.md).
- `estimator-web-react/`: cliente React y TypeScript. En el Compose actual, su proxy nginx apunta a `estimador-cag`. Streamlit también llama directamente a esa API mediante `ESTIMATOR_API_BASE_URL`. La intermediación exclusiva de Go está pendiente.
- El Compose raíz define PostgreSQL con pgvector para IA, un PostgreSQL separado para el historial de Go y Redis Stack. La configuración actual admite OpenAI y Anthropic para generación y usa OpenAI para embeddings. La reutilización de infraestructura del homelab y el soporte de Ollama son objetivos de integración.
- `examples/`: ejemplos y trazas. [El diagnóstico de arquitectura](arquitectura-actual.md) retrata el cierre de la Sesión 08. Para la evolución posterior de RAG, consulta la arquitectura del servicio de IA.
- `openspec/`: especificaciones en `specs/` (capacidades en `specs/estimator/`), cambios en `changes/` y archivo en `changes/archive/`. Las habilidades de ambos asistentes viven en `.agents/skills/` y `.claude/skills/`.

## Arquitectura objetivo aprobada

Estas decisiones rigen los próximos cambios de integración. Su implementación requiere cambios OpenSpec propios.

| Decisión | Restricción |
|---|---|
| DA-01 · Windows como cliente | Usar Windows exclusivamente con VS Code Remote SSH y navegador. El flujo prescinde de Docker Desktop, Node.js, Python, Go y una copia local del repositorio en Windows. |
| DA-02 · Homelab centralizado | Alojar el código fuente, las herramientas, las aplicaciones y la infraestructura en el homelab. |
| DA-03 · Comunicación de clientes | React y Streamlit llaman exclusivamente al backend Go. Se prohíbe el acceso directo desde estos clientes a `estimador-cag`, PostgreSQL, Redis u Ollama. |
| DA-04 · Entrada por Go | Entre los componentes de aplicación, solo Go llama a `estimador-cag`. Go intermedia y toda la lógica de IA permanece en `estimador-cag`. |
| DA-05 · Generación | Soportar Ollama, Anthropic y OpenAI mediante abstracciones que mantengan la lógica de negocio independiente del proveedor. |
| DA-06 · Credenciales | Las credenciales de proveedores de IA se inyectan exclusivamente en `estimador-cag`. Nunca exponerlas a Go, React o Streamlit ni versionar secretos, tokens, claves API o credenciales. |
| DA-07 · Infraestructura existente | Reutilizar PostgreSQL, pgvector y Ollama del homelab cuando sea seguro. Mantener bases y usuarios independientes por responsabilidad y evitar instancias redundantes. |
| DA-08 · Redis Stack | Mantener Redis Stack y las capacidades RediSearch que usan funcionalidades como la caché semántica. |
| DA-09 · Docker y OpenSpec | Usar Docker y Docker Compose para desarrollar, gestionar dependencias, compilar, probar, ejecutar, verificar, aplicar lint y desplegar las aplicaciones. Especificar y planificar con OpenSpec antes de implementar cambios funcionales o arquitectónicos. |
| DA-10 · Generación y embeddings | Configurar proveedor y modelo por separado para cada función. Anthropic participa solo en generación. Nunca mezclar espacios de modelos de embeddings distintos, incluso si tienen la misma dimensión. |
| DA-11 · Herramientas nativas | Git, Claude Code, Codex CLI, NVM, Node.js, npm, OpenSpec, Docker y Docker Compose pueden instalarse y ejecutarse en Ubuntu. Node.js nativo sirve para herramientas de desarrollo como OpenSpec. El ciclo de las aplicaciones se ejecuta en Docker. |
| DA-12 · Instrucciones compartidas | Mantener la guía común en `AGENTS.md` y las particularidades de cada asistente en su propia configuración. `CLAUDE.md` importa `AGENTS.md` mediante `@AGENTS.md`. |
| DA-13 · Habilidades versionadas | Versionar esta guía, `CLAUDE.md`, `.agents/skills/` y `.claude/skills/`, junto con la configuración compartida pertinente. Excluir ajustes personales, permisos locales y secretos, como `.claude/settings.local.json`. Mantener ambos juegos de habilidades sincronizados con la misma versión de OpenSpec y regenerarlos con el CLI, sin ediciones manuales. |
| DA-14 · OpenSpec reproducible | Usar OpenSpec 1.13.2 en Ubuntu y en Docker. Priorizar el CLI nativo para desarrolladores y asistentes. Mantener el servicio Compose existente para validaciones reproducibles, CI/CD y entornos sin Node.js u OpenSpec nativos. Usar Docker Compose directamente, sin wrappers adicionales. |

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
- Preserva contratos aditivos. Mantén las rutas y la forma del JSON existentes que consumen Go, React y Streamlit.
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
docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
docker compose up --build
```

`api-test` ejecuta `pytest -q`, `api-lint` ejecuta Ruff, `web-test` ejecuta `go test -p 1 ./...` y `web-lint` comprueba gofmt y ejecuta go vet. Si cambia `pyproject.toml`, reconstruye la imagen de pruebas con `docker compose -f docker-compose.verify.yml build api-test`. Verifica los cambios de aplicaciones con pruebas y lint en Docker.

El Compose raíz levanta la pila completa (API 8000, Go 3000, React 3001, Streamlit 8501). `estimador-cag/docker-compose.yml` levanta solo el backend con recarga. Los proyectos creados desde esos directorios tienen volúmenes separados.

## OpenSpec, secretos y Git

- Consulta la [guía de OpenSpec](openspec/README.md) para instalar el CLI, invocar los seis workflows, validar y gestionar las habilidades. Usa el CLI nativo para planificación y valida antes del archivado. No invoques superpowers.
- Carga los secretos desde el entorno o archivos locales excluidos, como `.env`. Revisa que las configuraciones versionadas incluyan solo información compartida y que las credenciales de IA lleguen exclusivamente a `estimador-cag`.
- Verifica la rama y el estado de Git antes de editar. Trabaja en la rama indicada para la tarea, con `master` como base habitual, y preserva los cambios ajenos. Revisa el diff y el resultado de las verificaciones antes de preparar un commit. Agrega archivos, crea commits o publica cambios cuando la tarea lo autorice.
