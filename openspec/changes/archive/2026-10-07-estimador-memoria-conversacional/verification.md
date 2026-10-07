# Verification

Todas las comprobaciones se ejecutaron en contenedores Docker (nada en el host). Fecha: 2026-10-07.

## Resultados

| Comprobación | Comando (contenedor) | Resultado |
|---|---|---|
| API + Streamlit | `docker run --rm -v "$PWD:/app" estimador-cag:test` (etapa `test` del Dockerfile) | 612 passed, 7 skipped (PostgreSQL real: requiere `TEST_DATABASE_URL`); línea base antes del cambio: 471 passed, 7 skipped |
| Web React | `npm test` y `npm run build` en `node:22-alpine` | 113 passed (9 archivos); `tsc` y `vite build` correctos |
| Web Rails | `bin/rails test` en `ruby:3.4` | 97 runs, 490 assertions, 0 failures (línea base: 61 runs) |
| OpenSpec | `openspec validate --all --strict` | 15 passed, 0 failed |
| Imágenes de producción | `docker build` de `estimador-cag`, `estimator-web`, `estimator-web-react` | las tres se construyen |
| Smoke contra la imagen real | contenedor `estimador-cag:verify` + cliente `httpx` en la misma red | 10/10: `POST /sessions` 201 con UUID v4, ruta multipart en OpenAPI, 404, 422, 415 (txt y PDF falso), 400 de guardrail, PDF+DOCX hasta el LLM (502 saneado con clave ficticia), endpoint sin sesión intacto |

## Trazabilidad

| Requisito | Pruebas |
|---|---|
| Ventana deslizante y `MAX_TURNS` | `tests/test_sessions.py`, `tests/test_sessions_api.py::test_history_respects_max_turns_after_eight_turns` |
| Almacén volátil (TTL, tope, UUID v4) | `tests/test_sessions.py`, `test_expired_session_is_404` |
| Extracción de PDF/Word y separadores | `tests/test_attachments.py`, `test_pdf_attachment_reaches_the_llm_and_influences_the_estimation` |
| Límites y errores de adjuntos | `tests/test_attachments.py`, `tests/test_sessions_api.py` (413/415/422) |
| Metadatos: modelo, bloque en el prompt, fusión | `tests/test_sessions.py`, `tests/prompts/test_project_metadata.py`, `test_two_requests_in_one_session_update_project_metadata` |
| Extracción inválida o fallida no rompe la estimación | `test_invalid_metadata_extraction_keeps_the_estimate_and_previous_metadata`, `test_provider_failure_during_metadata_extraction_does_not_fail_the_estimate` |
| Endpoints de sesión | `tests/test_sessions_api.py` |
| Streamlit, React y Rails | `tests/test_streamlit_app.py`, `src/pages/conversation.test.tsx`, `src/api/sessionApi.test.ts`, `src/lib/attachments.test.ts`, `test/controllers/conversation_test.rb`, `test/services/estimator_api_session_test.rb`, `test/models/estimation_form_attachments_test.rb` |

## Limitaciones y observaciones

- Las sesiones son volátiles por diseño (memoria de un único proceso); no hay persistencia ni memoria híbrida.
- La calidad de la extracción de metadatos depende del modelo; las pruebas usan un LLM guionizado y no miden calidad real.
- No se ejecutó ninguna llamada a un proveedor con clave real; el smoke test usó una clave ficticia.
- `test_history_postgres.py` sigue omitido en local (se activa con `TEST_DATABASE_URL`, como en CI).
- El cliente Rails guarda los metadatos compactados en la cookie de sesión (límite de ~4 KB).
