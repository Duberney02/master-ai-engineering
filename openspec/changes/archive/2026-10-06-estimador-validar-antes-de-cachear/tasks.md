# Tasks

## 1. Wrapper: cachear solo lo aceptable

- [x] 1.1 Añadir el parámetro opcional `accept` a `LLMWrapper.complete` y aplicarlo en `_finish` (escritura) y `_cached` (lectura), tratando una excepción del criterio como «no aceptable»; verificar con pruebas de `tests/test_resilient_generation.py` que cubran los escenarios «Respuesta no aceptada» y «Entrada cacheada que ya no es aceptable» y que siguen pasando las existentes de caché.
- [x] 1.2 Propagar `accept` por `llm_service._complete` y `generate_from_prompts` (parámetro opcional, valor por defecto `None`); verificar que `uv run pytest -q tests/test_llm_service.py tests/test_generation_flow.py` pasa.

## 2. Pipeline: criterio de negocio

- [x] 2.1 Definir en `pipeline.py` el criterio `_is_valid_text` (basado en `validate_text`) y usarlo en el generador por defecto, conservando el parámetro `generate` inyectable; verificar con una prueba de pipeline que reproduce el caso real (suma de fases ≠ total repetida) y comprueba que el segundo intento vuelve a invocar al proveedor y se recupera, y que una entrada inválida previa en la caché no se sirve.
- [x] 2.2 Documentar el comportamiento en `estimador-cag/README.md` (sección de caché) y verificar con la suite completa `uv run pytest -q` sin `.env` (contenedor Linux): sin fallos nuevos.
