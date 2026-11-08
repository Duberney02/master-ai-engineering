## 1. Backend Go: API JSON (commit «feat(web-go): API JSON bajo /api»)

- [x] 1.1 Crear `internal/httpapi` (transporte JSON): router con `GET /up`, recuperación de pánicos, límite de cuerpo y registro; helper de errores `{"detail"}` con el mapeo de `ARCHITECTURE.md`.
- [x] 1.2 `POST /api/conversations` y `POST /api/conversations/{id}/estimations` (multipart, validación con `internal/estimation`, 404 por sesión caducada), con pruebas contra una API de IA simulada.
- [x] 1.3 `GET /api/estimations`, `GET /api/estimations/{id}` y `GET /api/prompt-preview`, con pruebas.
- [x] 1.4 Chunking Lab: `GET /api/chunking-comparisons/options`, `GET|POST /api/chunking-comparisons`, `GET /api/chunking-comparisons/{id}` (historial en PostgreSQL, `saved:false`, 503 sin BD), con pruebas unitarias y de integración.
- [x] 1.5 Ajustes: `GET|PUT /api/ai-settings` y `GET /api/primary-model` (caché 15 s, invalidación al guardar), con pruebas.
- [x] 1.6 `web-test` y `web-lint` en verde.

## 2. React: pantallas migradas y cliente HTTP (commit «feat(react): Chunking Lab, Ajustes y backend Go»)

- [x] 2.1 Repuntar `src/api/estimatorApi.ts` (y tipos) a `/api/conversations`, `/api/estimations`, `/api/prompt-preview`; ajustar mocks y pruebas existentes.
- [x] 2.2 `chunkingApi.ts`, `settingsApi.ts` y `primaryModel` con sus pruebas.
- [x] 2.3 Páginas `ChunkingLabPage`, `ChunkingHistoryPage`, `ChunkingResultPage` con pruebas (formulario, avisos de coste, errores, resultado, historial vacío/503).
- [x] 2.4 `SettingsPage` y `PrimaryModelBadge` en `Layout` con pruebas; enlaces «Chunking Lab» y «Ajustes» y rutas en `App.tsx`.
- [x] 2.5 nginx: `API_UPSTREAM` hacia `estimator-web`, timeout 600 s para el Lab, eliminar `location = /health`; actualizar `README.md` de React.
- [x] 2.6 Añadir `web-react-test` y `web-react-lint` a `docker-compose.verify.yml` y dejarlos en verde.

## 3. Backend Go: eliminar la parte web (commit «refactor(web-go): elimina HTML, sesión y CSRF»)

- [x] 3.1 Borrar `internal/web/templates`, `internal/web/public`, `templates.go`, `format.go` y sus pruebas, el handler `home`, `_method`, CSRF y `internal/session`; quitar `SECRET_KEY_BASE` de `config`.
- [x] 3.2 Limpiar dependencias y código muerto (`html/template`, `embed`, helpers sin uso); `web-go mod tidy`.
- [x] 3.3 Actualizar `internal/archtest` y `cmd/server/main.go`; `web-test` y `web-lint` en verde.
- [x] 3.4 Actualizar `estimator-web-go/ARCHITECTURE.md` y `README.md`.

## 4. Streamlit independiente (commit «feat(streamlit): cliente independiente del backend Go»)

- [x] 4.1 Crear `estimator-streamlit/` con `Dockerfile`, `pyproject.toml`, `uv.lock`, `README.md`, `.dockerignore`.
- [x] 4.2 Mover y adaptar `streamlit_app.py`, el cliente y el soporte; `models.py` local; `ESTIMATOR_WEB_URL`; prompt vía `/api/prompt-preview`; sin imports de `estimador-cag`; sin código muerto.
- [x] 4.3 Mover y adaptar los tests (`test_streamlit_app.py`, `test_streamlit_support.py`) con el backend simulado; añadir prueba de «sin referencias a `estimador-cag`».
- [x] 4.4 Añadir `streamlit-test` y `streamlit-lint` a `docker-compose.verify.yml` y dejarlos en verde.

## 5. Limpieza de `estimador-cag` (commit «refactor(cag): retira Streamlit del servicio de IA»)

- [x] 5.1 Borrar `streamlit_app.py`, `app/streamlit_client.py`, `app/streamlit_support.py` y sus tests; quitar `streamlit` de `pyproject.toml` y regenerar `uv.lock` con `api-uv lock`; reconstruir `api-test`.
- [x] 5.2 Quitar el `COPY streamlit_app.py` del `Dockerfile`, el servicio/volumen de Streamlit de `estimador-cag/docker-compose.yml` y la variable de `.env.example`.
- [x] 5.3 Actualizar `ARCHITECTURE.md` (incluida la línea «fuera de las capas»), `README.md` y `tests/test_layer_dependencies.py` si lo referencia; `api-test` y `api-lint` en verde.

## 6. Compose y documentación (commit «chore: Compose en tres capas y documentación»)

- [x] 6.1 `docker-compose.yml`: `estimador-cag-chat` desde `estimator-streamlit/` dependiendo de `estimator-web`; `estimator-web-react` hacia `estimator-web`; retirar `SECRET_KEY_BASE`; `docker compose config` válido.
- [x] 6.2 Actualizar `CLAUDE.md`, `README.md` raíz y `arquitectura-actual.md` (estado resultante).
- [x] 6.3 Verificar con `grep` que React y Streamlit no tienen referencias a `estimador-cag`, `:8000` ni `/api/v1`.

## 7. Verificación y cierre

- [x] 7.1 `docker compose up --build`: stack sano (API 8000, backend Go 3000, React 3001, Streamlit 8501) y un flujo E2E por cada cliente a través del backend (estimar, historial; en React además Lab y Ajustes).
- [x] 7.2 Tests y lint en verde en Docker para `estimador-cag`, `estimator-web-go`, `estimator-web-react` y `estimator-streamlit`.
- [x] 7.3 `openspec validate --all --strict` antes y después de implementar.
- [x] 7.4 Sincronizar specs, completar el `Purpose` de `streamlit-client`, archivar el cambio y abrir el PR contra `master`.
