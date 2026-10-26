# Spec Delta

## Purpose

Reutilizar estimaciones de solicitudes semánticamente equivalentes sin mezclar versión de prompt, tipo de proyecto, nivel de detalle, formato de salida ni modelo.

## MODIFIED Requirements

### Requirement: Aislamiento por atributos
Cada entrada SHALL almacenarse con `prompt_version`, `project_type`, `detail_level`, `output_format` y `model` (el LLM que la generó), y cada consulta SHALL filtrar por igualdad de los cinco, usando como modelo el primario efectivo de la solicitud. El índice SHALL incluir modelo y dimensiones de embedding en su nombre y un sufijo que identifique el esquema con el filtro de modelo.

#### Scenario: Atributo distinto
- **WHEN** existe una entrada idéntica en texto pero con otro `detail_level`
- **THEN** no se devuelve como acierto.

#### Scenario: Modelo distinto
- **WHEN** existe una entrada idéntica en texto generada por `gpt-4o-mini` y la solicitud usa `claude-sonnet-4-5`
- **THEN** no se devuelve como acierto, y sí con `gpt-4o-mini`.

#### Scenario: Entrada sin modelo
- **WHEN** una entrada no indica modelo
- **THEN** se almacena bajo el primario configurado.
