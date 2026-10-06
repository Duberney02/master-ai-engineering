# Spec Delta

## Purpose

Exponer por HTTP el prompt de sistema renderizado y sus ejemplos few-shot, para que clientes sin las plantillas (la web Rails) muestren el contexto del prompt como el cliente Streamlit.

## ADDED Requirements

### Requirement: Vista previa del prompt de estimación
`GET /api/v1/prompts/estimation` SHALL devolver `{prompt_version, system_prompt, examples}` para una `prompt_version` (por defecto `v3`) y unos `project_type`, `detail_level` y `output_format` (por defecto `mobile_app`, `medium` y `phases_table`). `examples` SHALL contener el título y la descripción de cada ejemplo few-shot del prompt. Una versión desconocida o un valor fuera de los enumerados SHALL rechazarse con 422. El endpoint SHALL NOT invocar al proveedor ni usar datos de usuario.

#### Scenario: Valores por defecto
- **WHEN** se llama sin parámetros
- **THEN** la respuesta es 200 con `prompt_version="v3"`, el prompt de sistema y los ejemplos few-shot de `v3`.

#### Scenario: Versión y opciones
- **WHEN** se llama con `prompt_version=v2&detail_level=detailed`
- **THEN** el prompt corresponde a `v2` con ese nivel de detalle e incluye el contrato JSON.

#### Scenario: Valores inválidos
- **WHEN** se llama con `prompt_version=v9`, con una ruta como versión o con un `project_type` inexistente
- **THEN** la respuesta es 422.
