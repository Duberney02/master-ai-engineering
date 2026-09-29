# Proposal

## Why

El estimador ya valida sus resultados y usa SDK asíncronos, pero repite llamadas idénticas, no calcula costes ni ofrece streaming HTTP o recuperación entre proveedores. Incorporar OpenSpec hace trazables estas mejoras sin reemplazar las garantías existentes.

## What Changes

- Adoptar OpenSpec en la raíz con integración Codex y documentación reproducible.
- Añadir caché Redis asíncrona opcional con TTL, claves completas y conservación de metadatos reales.
- Separar políticas de proveedores, coste, fallback y observabilidad; conservar SDK asíncronos nativos.
- Incorporar timeout y reintentos configurables, fallback explícito y métricas del proveedor efectivo.
- Exponer SSE con eventos de texto, métricas, finalización y error saneado; conectar Streamlit por HTTP.
- Calcular costes con tarifas configurables y representar precios desconocidos como null.
- Añadir logs JSON en producción, demo HTML, Redis en Compose y pruebas de comportamiento.
- Incorporar presupuesto opcional de razonamiento Anthropic y presupuesto económico opcional del proyecto con tarifas por rol.

## Capabilities

### New Capabilities

- `estimator/resilient-generation`: caché, políticas de proveedores, costes y observabilidad.
- `estimator/http-streaming`: contrato SSE, cliente Streamlit y demostración HTML.
- `estimator/estimation-options`: razonamiento y presupuesto económico opcionales sin cambiar la salida predeterminada.

### Modified Capabilities

Ninguna: el repositorio no tenía especificaciones OpenSpec.

## Impact

Cambios aditivos al contrato de `/api/v1/estimate`, nuevo `/api/v1/estimate/stream`, configuración y servicios de `estimador-cag`, dependencias Redis/httpx, Compose, CI y documentación. OpenSpec es herramienta de desarrollo; no dependencia de ejecución Python. El historial anterior se conserva sin utilizar superpowers. No incluye publicación ni llamadas pagadas para verificación.
