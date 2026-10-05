# Spec Delta

## Purpose

Concentrar la orquestación de una estimación estructurada en un servicio único, inyectable y sustituible en pruebas.

## ADDED Requirements

### Requirement: Pipeline centralizado
El sistema SHALL proveer un servicio `EstimationPipeline` que ejecute, en este orden: guardrails de entrada, caché exacta, caché semántica, renderizado del prompt, generación tipada, validación de salida y almacenamiento en las cachés. Devolverá el resultado, la versión de prompt y si procede de caché. Los routers SHALL delegar en él y no contener lógica de orquestación.

#### Scenario: Orden de etapas
- **WHEN** se ejecuta una solicitud sin aciertos de caché
- **THEN** las etapas se ejecutan en el orden indicado y el resultado se almacena en ambas cachés.

#### Scenario: Acierto de caché exacta
- **WHEN** existe una entrada exacta válida
- **THEN** se omiten la caché semántica, el render y la generación, y `cached=true`.

#### Scenario: Resultado cacheado inválido
- **WHEN** la entrada cacheada no pasa la validación de negocio
- **THEN** se trata como fallo de caché.

### Requirement: Inyección por dependencia
El pipeline SHALL inyectarse en los endpoints mediante `Depends(get_pipeline)` de FastAPI, de modo que las pruebas puedan sustituirlo con `app.dependency_overrides`.

#### Scenario: Sustitución en pruebas
- **WHEN** una prueba registra un pipeline falso en `dependency_overrides`
- **THEN** el endpoint lo usa sin invocar guardrails, cachés ni proveedor reales.
