# CLAUDE.md

Guía para trabajar en este repositorio. Los artefactos de OpenSpec y la documentación se escriben en español;
los encabezados estructurales y las palabras SHALL/MUST de las specs, en inglés.

## Estructura

Monorepo del máster en AI Engineering. Un mismo producto (estimador de proyectos con IA) con varios proyectos, en **tres capas estrictas**: frontends → backend de negocio → servicio de IA. **Solo `estimator-web-go` llama a `estimador-cag`**: React y Streamlit hablan únicamente con el backend (nunca con `API_UPSTREAM`/`ESTIMATOR_API_BASE_URL` apuntando al servicio de IA).

- `estimador-cag/`: servicio de IA, capa 3 (FastAPI, Python 3.11, uv). **Todo el trabajo de IA vive aquí.** Sin clientes embebidos.
- `estimator-web-go/`: backend de negocio, capa 2 (Go, net/http): **API JSON bajo `/api/` + `/up`, sin HTML ni sesión de navegador**, organizado por contextos ([`ARCHITECTURE.md`](estimator-web-go/ARCHITECTURE.md)). Único cliente del servicio de IA. `go test` con la API de IA simulada y PostgreSQL solo para el historial del Chunking Lab (servicio `estimator-web` del Compose, puerto 3000).
- `estimator-web-react/`: cliente web, capa 1 (React + TypeScript; nginx reenvía `/api/` al backend Go): estimaciones, Chunking Lab y Ajustes.
- `estimator-streamlit/`: chat Streamlit, capa 1 (Python 3.11, uv), proyecto independiente: solo HTTP con el backend Go (`ESTIMATOR_WEB_URL`), sin imports de `estimador-cag`.
- `openspec/`: specs (`specs/estimator/`) y cambios (`changes/`). El trabajo nuevo sigue OpenSpec.
- `.agents/skills/`: skills de OpenSpec (`openspec-propose`, `-apply-change`, `-sync-specs`, `-archive-change`).

## Todo se ejecuta en Docker

Nada se ejecuta en el host. Desde la raíz:

```sh
docker compose -f docker-compose.verify.yml run --rm api-test              # pytest -q
docker compose -f docker-compose.verify.yml run --rm api-test tests/test_x.py -k nombre
docker compose -f docker-compose.verify.yml run --rm api-lint              # ruff check
docker compose -f docker-compose.verify.yml run --rm api-lint check . --fix
docker compose -f docker-compose.verify.yml run --rm api-uv lock           # regenerar uv.lock
docker compose -f docker-compose.verify.yml run --rm web-test              # backend Go: go test -p 1 ./... (con PostgreSQL efímero)
docker compose -f docker-compose.verify.yml run --rm web-lint              # backend Go: gofmt + go vet
docker compose -f docker-compose.verify.yml run --rm web-react-test        # React: vitest run (node_modules en un volumen)
docker compose -f docker-compose.verify.yml run --rm web-react-lint        # React: tsc --noEmit
docker compose -f docker-compose.verify.yml run --rm streamlit-test        # Streamlit: pytest -q
docker compose -f docker-compose.verify.yml run --rm streamlit-lint        # Streamlit: ruff check
docker compose -f docker-compose.verify.yml run --rm streamlit-uv lock     # regenerar el uv.lock de Streamlit
docker compose -f docker-compose.verify.yml run --rm web-go mod tidy      # dependencias del módulo Go
docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
docker compose up --build                                                   # stack completo (API 8000, web Go 3000, React 3001, Streamlit 8501)
```

Si cambian las dependencias (`pyproject.toml`), reconstruye la imagen de pruebas:
`docker compose -f docker-compose.verify.yml build api-test` (y `streamlit-test` para el chat). Un cambio está hecho cuando tiene los tests en
verde y el lint limpio, ejecutados en Docker, en **todos** los proyectos tocados. Las pruebas nunca usan claves reales (fakes, `fakeredis`, servidor simulado de la API de IA).

Hay dos Compose distintos: el de la raíz (stack completo) y `estimador-cag/docker-compose.yml` (solo backend con
recarga, solo el servicio de IA). Lanzarlos desde sitios distintos crea proyectos distintos y volúmenes no compartidos.

## Arquitectura del servicio

Contrato completo en [`estimador-cag/ARCHITECTURE.md`](estimador-cag/ARCHITECTURE.md). Resumen:

```
app/
├── config.py · dependencies.py · main.py   # settings, composition root, factory FastAPI
├── foundation/   llm · prompts · guardrails · attachments · persistence   (sin opinión de IA)
├── domain/       schemas/ (contrato con los clientes) + conductor (pipeline, session_estimation, acb)
├── generation/   cag/ · rag/ · agentic/ · conversation/                  (no se importan entre sí)
├── ingestion/    pipeline batch offline
└── api/          routers finos (sin lógica de negocio)
```

Reglas: cada capa solo importa de las de arriba; los hermanos de `generation/` solo se encuentran en el
conductor (`agentic` puede usar `conversation`); **todas las fábricas viven en `app/dependencies.py`**.
`tests/test_layer_dependencies.py` lo verifica; no añadas violaciones nuevas.

## Convenciones

- Settings en minúsculas en `Settings` (pydantic-settings); variables de entorno en mayúsculas.
- SDK **asíncronos** (OpenAI, Anthropic, Redis, SQLAlchemy async). No bloquees el event loop.
- **Errores saneados**: nunca devuelvas trazas, claves, URLs internas ni cuerpos de proveedor; el detalle va al log.
- **Contratos aditivos**: no cambies rutas ni la forma JSON de `estimador-cag` (las consume el backend Go); los endpoints nuevos para los clientes viven en el backend Go (`/api/...`). Streamlit y React no importan ni llaman al servicio de IA.
- Salida de usuario y comentarios en español.

## Trampas

- Los tests que parchean `get_settings` deben parchear también `app.dependencies.get_settings` (usa `patch_settings`
  en `tests/_fakes.py`).
- `get_session_store` lee `app.config.get_settings()` en vivo, a propósito: algunos tests fijan la configuración con
  variables de entorno.
- La caché semántica necesita Redis Stack (RediSearch); sin `REDIS_URL` se desactiva.
- Rama de trabajo de la Sesión 7: `session_07/refined` (base `master`; este repo no tiene `main`).
