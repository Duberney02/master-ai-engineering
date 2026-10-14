# Tasks

Todas las verificaciones se ejecutan en contenedores Docker (`docker compose -f docker-compose.verify.yml ...`).

## 1. Herramientas de desarrollo

- [x] 1.1 Añadir `ruff` y `fakeredis` al grupo `dev`, la configuración de Ruff, regenerar `uv.lock` con el servicio `api-uv` y corregir los avisos existentes; verificar con `api-lint` («All checks passed!») y comprobando que la imagen `runtime` no contiene ninguno de los dos.
- [x] 1.2 Crear `docker-compose.verify.yml` y `openspec/Dockerfile` (pruebas, lint, evaluación, `uv`, OpenSpec); verificar ejecutando cada servicio.

## 2. Entorno

- [x] 2.1 Restringir `APP_ENV` y `LOG_LEVEL` en `config.py` con normalización y actualizar `.env.example`; verificar con `tests/test_config.py` (valores válidos, normalización, inválidos) y que la suite sigue pasando.

## 3. Caché

- [x] 3.1 Escribir `tests/test_cache_fakeredis.py` (ida y vuelta, no ASCII, claves inexistentes, caché desactivada, valores corruptos, valor no serializable, TTL y caducidad, claves de resultado); verificar en el contenedor de pruebas.

## 4. Librerías

- [x] 4.1 Escribir `docs/evaluacion-instructor-litellm.md` con criterio, hallazgos y decisión; verificar que `generate_structured` está cubierta por `tests/test_structured.py`.

## 5. Cierre

- [x] 5.1 Actualizar README raíz y de `estimador-cag` (comandos Docker, tabla de variables, sesiones, ACB, evaluación); ejecutar `ruff`, `pytest`, `openspec validate --all --strict` y la construcción de la imagen de producción en contenedores y registrar el resultado en `verification.md`.
