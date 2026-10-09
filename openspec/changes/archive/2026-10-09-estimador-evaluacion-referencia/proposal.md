# Proposal

## Why

La evaluación existente (`app/services/evaluation.py`) comprueba el formato Markdown del flujo de transcripción, pero no hay una forma repetible de medir la calidad del flujo estructurado y conversacional: ni casos de referencia, ni métricas del contenido, ni un modo de comparar el actor solo frente al flujo con crítico. Sin ello, cambiar un prompt, un modelo o la memoria es una apuesta.

## What Changes

- **Dataset de referencia versionado** (`evals/datasets/reference_v1.json`) con 16 casos que cubren SaaS, aplicaciones móviles, herramientas internas, pipelines de datos, entradas vagas, entradas adversariales, restricciones regulatorias y plazos exigentes. Cada caso define requisitos o tecnologías esperados y rangos de fases, coste y duración cuando corresponden.
- **Métricas deterministas** (sin LLM): `schema_adherence` (coherencia estructural y número de fases), `cost_bounds` (rangos de coste y duración y resultado fuera de alcance) y `content_recall` (presencia de requisitos y tecnologías esperados). Las evaluaciones existentes no se tocan.
- **Runner** `python -m evals.runner`: ejecuta el dataset en modo `actor` (`/estimate`) o `acb` (`/estimate-acb`), en proceso con `TestClient` o contra una URL HTTP; permite limitar casos y exportar resultados; cada caso usa una sesión independiente; el proceso devuelve código de salida distinto de cero si algún caso no supera la evaluación.
- **Reporte JSON**: por caso, identificador, latencia, métricas, aprobado/fallido, resumen de la estimación, versión del prompt y decisión final ACB; errores y totales de casos evaluados y aprobados.

**No incluido**: juez LLM, evaluación de la calidad del texto libre, integración en CI con proveedores reales (el CI no tiene claves), comparación automática entre ejecuciones.

## Capabilities

### New Capabilities
- `estimator/evaluation-dataset`: formato, versionado y cobertura del dataset de referencia.
- `estimator/evaluation-metrics`: métricas deterministas por caso.
- `estimator/evaluation-runner`: ejecución, códigos de salida y reportes JSON.

### Modified Capabilities
- Ninguna: `evaluation.py` y sus pruebas permanecen igual.

## Impact

- Código: paquete nuevo `estimador-cag/evals/` (fuera de `app/`, no se incluye en la imagen de producción); servicio `api-eval` en `docker-compose.verify.yml`.
- Dependencias: ninguna nueva (usa `httpx` y `fastapi.testclient`, ya presentes).
- Las pruebas habituales usan dobles de los proveedores; ejecutar el dataset contra un proveedor real es una acción explícita del usuario con claves propias.
