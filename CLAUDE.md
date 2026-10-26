# CLAUDE.md

Guía para trabajar en este repositorio. Los artefactos de OpenSpec y la documentación se escriben en español;
los encabezados estructurales y las palabras SHALL/MUST de las specs, en inglés.

## Estructura

Monorepo del máster en AI Engineering. Un mismo producto (estimador de proyectos con IA) con varios proyectos:

- `estimador-cag/`: servicio FastAPI (Python 3.11, uv). **Todo el trabajo de IA vive aquí.**
- `estimator-web/`: cliente Rails 8 organizado por contextos ([`ARCHITECTURE.md`](estimator-web/ARCHITECTURE.md)): Faraday, Minitest, WebMock y PostgreSQL solo para el historial del Chunking Lab.
- `estimator-web-react/`: el mismo cliente en React + TypeScript.
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
docker compose -f docker-compose.verify.yml run --rm web-test              # cliente Rails: bin/rails test (con PostgreSQL efímero)
docker compose -f docker-compose.verify.yml run --rm web-lint              # cliente Rails: RuboCop
docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
docker compose up --build                                                   # stack completo (API 8000, Rails 3000, React 3001, Streamlit 8501)
```

Si cambian las dependencias (`pyproject.toml`), reconstruye la imagen de pruebas:
`docker compose -f docker-compose.verify.yml build api-test`. Un cambio está hecho cuando tiene los tests en
verde y el lint limpio, ejecutados en Docker. Las pruebas nunca usan claves reales (fakes, `fakeredis`, WebMock).

Hay dos Compose distintos: el de la raíz (stack completo) y `estimador-cag/docker-compose.yml` (solo backend con
recarga). Lanzarlos desde sitios distintos crea proyectos distintos y volúmenes no compartidos.

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
- **Contratos aditivos**: no cambies rutas ni la forma JSON que consumen Rails, React y Streamlit.
- Salida de usuario y comentarios en español.

## Trampas

- Los tests que parchean `get_settings` deben parchear también `app.dependencies.get_settings` (usa `patch_settings`
  en `tests/_fakes.py`).
- `get_session_store` lee `app.config.get_settings()` en vivo, a propósito: algunos tests fijan la configuración con
  variables de entorno.
- La caché semántica necesita Redis Stack (RediSearch); sin `REDIS_URL` se desactiva.
- Rama de trabajo de la Sesión 7: `session_07/refined` (base `master`; este repo no tiene `main`).
