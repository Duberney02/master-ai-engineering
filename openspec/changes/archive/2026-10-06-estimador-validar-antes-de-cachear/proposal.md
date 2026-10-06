# Proposal

## Why

La caché exacta de completions guarda cualquier respuesta del proveedor que termine bien, antes de la validación de negocio del pipeline. Si el modelo devuelve un resultado inválido (por ejemplo, fases cuya suma no coincide con `total_cost_eur`), esa respuesta queda cacheada 24 h: los reintentos de corrección reciben el mismo texto inválido desde la caché, se agotan los intentos y la API responde 502 a esa entrada hasta que expira la entrada. Las tres interfaces (Streamlit, Rails y React) muestran entonces «La API del estimador no pudo completar la solicitud».

## What Changes

- El pipeline estructurado SHALL indicar al wrapper qué completions son aceptables; el wrapper solo guarda en caché las que lo son (**validar antes de cachear**).
- Una entrada ya cacheada que no cumpla la validación SHALL tratarse como fallo de caché y regenerarse, de modo que las entradas inválidas que ya existen en Redis se recuperan solas, sin vaciar la caché.
- Sin cambios de contrato HTTP ni de configuración. El flujo de transcripción no cambia (no pasa criterio de aceptación).

## Capabilities

### New Capabilities

### Modified Capabilities
- `estimator/resilient-generation`: la caché exacta SHALL almacenar solo completions que superen el criterio de aceptación del llamador y SHALL ignorar las entradas que ya no lo superen.

## Impact

- Código: `estimador-cag/app/services/llm_wrapper.py`, `llm_service.py` (parámetro opcional `accept`) y `pipeline.py` (criterio de aceptación por defecto).
- Pruebas nuevas en `tests/` (wrapper y pipeline); sin dependencias nuevas.
- Datos: las entradas inválidas ya presentes en Redis dejan de servirse; no hace falta migración.
