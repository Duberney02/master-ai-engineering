# Design

## Context

`EstimationPipeline._generate_validated` pide la completion con `generate_from_prompts`, que pasa por `LLMWrapper.complete`. El wrapper guarda en `_finish` toda completion con `finish_reason` correcto y la sirve en `_cached` para el mismo `system`+`user`. La validación de negocio (`validate_text`) ocurre después, en el pipeline. Consecuencia observada en producción local: una respuesta con la suma de fases ≠ total se cachea y los reintentos la reciben idéntica (ver proposal.md).

El pipeline ya valida antes de guardar en sus cachés de resultado (exacta y semántica); el hueco es solo la caché de completions del wrapper.

## Goals / Non-Goals

**Goals:**
- Que una completion inválida no se almacene nunca y que las ya almacenadas no se sirvan.
- Mantener la firma `Generator = (system, user) -> Completion` que inyectan las pruebas.

**Non-Goals:**
- Recalcular totales en lugar de rechazar (decisión de producto aparte).
- Cambiar los logs operativos o `SAFE_FIELDS`.
- Tocar el flujo de transcripción, que no tiene criterio de aceptación.

## Decisions

**1. Criterio de aceptación inyectado (`accept: Callable[[str], bool]`) en el wrapper.** `LLMWrapper.complete` y `generate_from_prompts` reciben `accept` opcional (`stream` no cambia: ningún llamador define criterio). `_finish` cachea solo si `_cacheable(result) and accept(result.text)`; `_cached` devuelve `None` si la entrada no lo cumple. Alternativas: (a) borrar la clave desde el pipeline tras un fallo — el pipeline tendría que conocer la clave y no cubriría entradas ya envenenadas; (b) saltarse la caché de completions en el pipeline — pierde la reutilización legítima y no resuelve el diseño. Con `accept` el wrapper sigue sin conocer reglas de negocio.

**2. El pipeline define el criterio con `validate_text`.** Un generador por defecto `_generate_checked(system, user)` llama a `generate_from_prompts(..., accept=_is_valid_text)`, donde `_is_valid_text` aplica `validate_text` y devuelve `False` ante `ResultValidationError`. Se mantiene el parámetro `generate` del constructor, así que las pruebas con generadores falsos no cambian.

**3. Entradas ya envenenadas se autocorrigen.** Al ser `_cached` quien aplica `accept`, las entradas inválidas existentes se ignoran y la completion nueva, si es válida, sobrescribe la clave (`setex`). No se necesita `FLUSHALL` ni migración.

**4. `accept` no debe lanzar.** El wrapper protege la llamada: una excepción del criterio cuenta como «no aceptable» para no convertir un fallo del validador en un 500.

## Risks / Trade-offs

- [Un prompt que el modelo resuelve mal siempre vuelve a llamar al proveedor] → es el comportamiento deseado: antes fallaba permanentemente; ahora cada intento puede acertar y el coste queda acotado por `VALIDATION_MAX_ATTEMPTS`.
- [`validate_text` se ejecuta una vez más por lectura de caché] → es una validación pura, de microsegundos.
- [Firma pública nueva en `generate_from_prompts`] → parámetro opcional con valor por defecto `None`, sin impacto en llamadas existentes.
