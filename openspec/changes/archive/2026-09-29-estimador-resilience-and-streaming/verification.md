# Verificación

Fecha: 2026-09-29. Base: master `18f47442e03e456789e5f77eeb72c03878548b10`.

## Resultados de la implementación inicial

- Línea base antes de implementación: **154 passed**.
- Suite completa final: `uv run pytest -q` → **214 passed**, 16.17 s.
- Advertencia preexistente: alias BlockingPortal de AnyIO usado por Starlette TestClient.
- `uv run python -m compileall -q app streamlit_app.py` → correcto.
- `git diff --check` → correcto.
- `openspec validate --all --strict` → **4 passed, 0 failed** (cambio y tres capacidades).
- `docker compose config --quiet` → correcto.
- `docker build -t estimador-cag:openspec-check .` → imagen construida con lock congelado.
- Usuario de imagen comprobado con `id -u` → **10001**.
- API real en contenedor con clave ficticia: HTTP 200 en `/health`, `/docs`,
  `/openapi.json`, `/static/sse_demo.html`; ruta SSE presente en OpenAPI.
- Chat real en contenedor **sin OPENAI_API_KEY ni ANTHROPIC_API_KEY**:
  `/_stcore/health` → HTTP 200. Comportamiento UI comprobado además con AppTest.
- Redis 7 real: escritura/lectura, expiración con TTL=1, segunda llamada del
  wrapper sin invocar proveedor simulado, tokens conservados, coste de solicitud 0.

## Seguimiento: migración a structlog

- Dependencia instalada y fijada en `uv.lock`: structlog 26.1.0.
- Todos los loggers de aplicación usan `structlog.get_logger(__name__)`.
- `tests/test_logging.py`: cinco pruebas para JSON y campos tipados, filtrado de
  campos sensibles y excepciones, interoperabilidad con logging estándar,
  consola/niveles y eventos de generación con SDK simulado.
- Suite completa posterior: `uv run pytest -q` → **218 passed**, 11.26 s,
  con la misma advertencia preexistente de Starlette/AnyIO.
- Compilación de sintaxis y `git diff --check` → correctos.
- `openspec validate --all --strict` → **4 passed, 0 failed**.
- Las comprobaciones Docker anteriores corresponden a la implementación inicial;
  la imagen no se reconstruyó para este seguimiento de logging.

## Trazabilidad

Seguimiento de tarifas (2026-09-29): `.env.example` contiene 13 entradas para
modelos y snapshots, consultadas en las fuentes oficiales enlazadas en el archivo.
Se validó la lectura con `dotenv_values`, JSON y `TypeAdapter(dict[str, ModelPrice])`,
incluida la cobertura del modelo predeterminado y la igualdad de tarifas de los
alias/snapshots de GPT-4o mini y Haiku 4.5. `git diff --check` correcto.
Son tarifas Standard de texto, sin caché del proveedor ni recargos; no se modificó
el `.env` local ni se realizaron llamadas de inferencia.

| Capacidad | Evidencia principal |
|---|---|
| Caché, claves, corrupción, TTL, costes y fallback | `tests/test_resilient_generation.py`, smoke con Redis real |
| Cierre/cancelación/truncamiento y SDK | `tests/test_resilient_generation.py`, `tests/test_llm_service_streaming.py` |
| SSE, dos fases, errores saneados, parser | `tests/test_sse_and_options.py` |
| Cliente HTTP, historial, borrado y métricas | `tests/test_streamlit_app.py` |
| Razonamiento y presupuesto económico | `tests/test_sse_and_options.py` |
| Validación de configuración | `tests/test_config.py` |
| Compatibilidad API/prompt/evaluación | Suite original conservada; expectativa de campos aditivos actualizada |

Dos pruebas UI excedieron inicialmente el timeout predeterminado de 3 s durante
la compilación Docker. El timeout de AppTest se ajustó a 10 s para Windows/CI;
la repetición dirigida y la suite completa posterior pasaron.

## Alcance y límites

No hubo llamadas pagadas ni validación con claves reales. Fallback se probó con
los adaptadores reales de la aplicación y respuestas/excepciones SDK simuladas.
No se midieron ahorros, rendimiento bajo carga ni calidad semántica de estimaciones.
Precios se configuran explícitamente; no se asumen tarifas comerciales actuales.
CI quedó actualizado pero no se ejecutó en GitHub, porque no se hizo push.
Cambio y especificaciones quedan sincronizados y disponibles para revisión;
no se crea commit, PR ni despliegue. Se conserva el historial de diseño anterior.
