# Verificación: migración del backend Rails a Go

Rama `feature/migration_backend_service`. Todo se ejecutó en Docker.

## Resultados

| Comprobación | Comando | Resultado |
|---|---|---|
| Pruebas del servicio Go (más de 190 pruebas: unitarias, endpoints, persistencia con PostgreSQL real, arquitectura) | `docker compose -f docker-compose.verify.yml run --rm web-test` | ✅ todos los paquetes `ok` |
| Lint Go (gofmt + go vet) | `… run --rm web-lint` | ✅ limpio |
| Lint Python | `… run --rm api-lint` | ✅ |
| Pruebas Python (la API no se modificó; solo `test_project_structure.py`, ver abajo) | `… run --rm api-test` | ✅ 1202 passed, 13 skipped |
| Specs | `… run --rm openspec validate --all --strict` | ✅ 54/54 |
| Stack completo | `docker compose up --build -d` | ✅ 7 servicios `healthy` (API, chat, web Go, web React, Redis, 2× PostgreSQL); ningún servicio Rails |

## Comparación con Rails (misma API de IA real, bases separadas)

Se levantó temporalmente el cliente Rails original junto al servicio Go (ambos contra la API Python del stack) y se
compararon los HTML normalizados (etiquetas, atributos, texto; sin tokens CSRF, fechas ni duraciones) en 26 casos.

- **Idénticos**: inicio, historial de estimaciones, Chunking Lab (formulario, historial, detalle de una ejecución real con
  estrategias gratuitas, error «sin estrategias»), Ajustes (lectura y modelo rechazado por la API real), 404 de
  estimación/ejecución/ruta, redirecciones de `POST /conversation`, `PATCH /ai_settings` sin modelos y `POST /rag/…`.
- **Diferencias cosméticas aceptadas** (sin efecto funcional):
  1. Rails envuelve en `<div class="field_with_errors">` los campos con error del formulario de estimación; Go no
     (no hay CSS asociado).
  2. En el `<script>` del formulario Go emite `var max = 80000 ;` (espacio de `html/template`) frente a `80000;`.
  3. Las redirecciones de Rails llevan URL absoluta en `Location`; las de Go, ruta relativa (válido en HTTP).
- **Compatibilidad de datos**: el servicio Go leyó y amplió la tabla `chunking_comparisons` de un volumen creado por Rails
  (la nueva ejecución recibió el id 2) y el historial sobrevivió a un reinicio del contenedor.

## Equivalencia funcional cubierta por pruebas automáticas

Las 1 961 líneas de Minitest/WebMock se portaron escenario a escenario (formulario, adjuntos, conversación, metadatos,
sesión caducada, errores saneados, barra lateral, Lab con fallo de BD, Ajustes, indicador con caché de 15 s, navegación
activa). Añadidas para lo nuevo: CSRF (campo, cabecera, token ajeno), `_method`, cookie manipulada, tamaño de cookie,
límite de cuerpo, recuperación de pánicos y reglas de dependencias entre paquetes.

## Diferencias respecto a Rails

1. La cookie de sesión no es la de Rails (JSON firmado con HMAC en lugar de cifrada): las conversaciones abiertas se
   reinician una vez al desplegar.
2. Si la API cae al abrir la conversación de reemplazo tras una sesión caducada, Rails devolvía 500; Go muestra el error
   saneado en el formulario (422).
3. El *read timeout* cubre la respuesta completa, no cada lectura de socket.
4. La base se inicializa con `CREATE TABLE IF NOT EXISTS` (mismo esquema); no crea `schema_migrations`.
5. Un `SECRET_KEY_BASE` ausente genera un secreto efímero (con aviso) en lugar de impedir el arranque.

## Cambios fuera del servicio web (mínimos y necesarios)

- `estimador-cag/tests/test_project_structure.py`: la prueba de estructura del Compose apuntaba a `estimator-web` (Rails,
  `USER rails`, `/up` literal en el healthcheck). Ahora comprueba `estimator-web-go` y el healthcheck del binario.
  No se tocó código de la aplicación Python.
- Documentación: menciones a «Rails» en `estimador-cag/README.md`, `estimador-cag/ARCHITECTURE.md` y
  `estimator-web-react/README.md`.
- Quedan menciones históricas a Rails en **comentarios** de código Python/React (p. ej. docstring de
  `estimador-cag/app/api/prompts.py`) y en el cuerpo de specs no modificadas (`web-react-client`, `prompt-preview`): no
  ejecutan nada y se dejaron sin tocar para no salir del alcance.

## Limitaciones

- No se ejecutó una estimación real con LLM (coste y claves reales): el envío multipart, los adjuntos, la sesión caducada
  y el mapeo de errores se verifican contra una API simulada, no contra un proveedor.
- Los clientes «de Rails» eran solo navegadores: la SPA React y el chat Streamlit nunca pasaron por Rails y no se
  modificaron.
