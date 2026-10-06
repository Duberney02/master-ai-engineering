# Spec Delta

## Purpose

Reutilizar estimaciones de solicitudes semánticamente equivalentes sin mezclar versión de prompt, tipo de proyecto, nivel de detalle ni formato de salida.

## ADDED Requirements

### Requirement: Omisión por longitud del texto
La caché semántica SHALL omitirse, tanto en consulta como en almacenamiento, cuando el texto a embeber supere `SEMANTIC_CACHE_MAX_CHARS` (por defecto 8000 caracteres), sin calcular embeddings ni tocar Redis. La solicitud SHALL continuar con la caché exacta y la generación.

#### Scenario: Transcripción larga
- **WHEN** el texto de la solicitud supera el máximo
- **THEN** no se calcula ningún embedding, la consulta es un fallo de caché y no se almacena ninguna entrada semántica.

#### Scenario: Texto dentro del límite
- **WHEN** el texto tiene como máximo el límite configurado
- **THEN** la caché semántica funciona con normalidad.
