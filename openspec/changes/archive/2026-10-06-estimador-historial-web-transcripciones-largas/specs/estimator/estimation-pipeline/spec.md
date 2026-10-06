# Spec Delta

## Purpose

Concentrar la orquestación de una estimación estructurada en un servicio único, inyectable y sustituible en pruebas.

## MODIFIED Requirements

### Requirement: Pipeline centralizado
El sistema SHALL proveer un servicio `EstimationPipeline` que ejecute, en este orden: guardrails de entrada, caché exacta, caché semántica, renderizado del prompt, generación tipada, validación de salida y almacenamiento en las cachés. Devolverá el resultado, la versión de prompt, si procede de caché, su procedencia (`none`, `exact` o `semantic`) y las métricas de la llamada (modelo, tokens, latencia, costes y acierto de caché). Los routers SHALL delegar en él y no contener lógica de orquestación.

#### Scenario: Orden de etapas
- **WHEN** se ejecuta una solicitud sin aciertos de caché
- **THEN** las etapas se ejecutan en el orden indicado, el resultado se almacena en ambas cachés y la procedencia es `none`.

#### Scenario: Acierto de caché exacta
- **WHEN** existe una entrada exacta válida
- **THEN** se omiten la caché semántica, el render y la generación, `cached=true` y la procedencia es `exact`.

#### Scenario: Acierto de caché semántica
- **WHEN** no hay acierto exacto pero la caché semántica devuelve una entrada válida
- **THEN** se omiten el render y la generación, `cached=true` y la procedencia es `semantic`.

#### Scenario: Resultado cacheado inválido
- **WHEN** la entrada cacheada no pasa la validación de negocio
- **THEN** se trata como fallo de caché.
