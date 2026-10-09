# estimator/task-model-configuration Specification

## Purpose
Permitir un modelo distinto por tarea del LLM (estimador, metadatos, resumen, crítico) y configurar la detección de anclas sin alterar el comportamiento por defecto.

## Requirements

### Requirement: Modelo por tarea
El sistema SHALL aceptar `ESTIMATOR_MODEL`, `METADATA_MODEL`, `SUMMARY_MODEL` y `CRITIC_MODEL`. Una tarea sin modelo configurado SHALL usar el modelo efectivo global. El modelo de cada tarea SHALL formar parte de la clave de la caché de completions y SHALL usarse en las llamadas de esa tarea.

#### Scenario: Sin configuración
- **WHEN** no se define ninguna variable por tarea
- **THEN** todas las tareas usan el modelo efectivo actual.

#### Scenario: Modelo de resumen distinto
- **WHEN** `SUMMARY_MODEL` está definido
- **THEN** la llamada del resumidor usa ese modelo y la del estimador conserva el suyo.

### Requirement: Modo de detección de anclas
El sistema SHALL aceptar `ANCHOR_DETECTION_MODE` con los valores `heuristic` (por defecto) y `llm`, y SHALL rechazar cualquier otro valor al arrancar.

#### Scenario: Valor inválido
- **WHEN** `ANCHOR_DETECTION_MODE` tiene un valor desconocido
- **THEN** la validación de la configuración falla.

### Requirement: Versión del prompt conversacional
El sistema SHALL aceptar `CONVERSATION_PROMPT_VERSION` con el formato `vN` (por defecto `v4`) y SHALL rechazar cualquier otro formato al arrancar.

#### Scenario: Valor por defecto
- **WHEN** no se define la variable
- **THEN** la versión conversacional es `v4`.

#### Scenario: Formato inválido
- **WHEN** la variable vale `latest` o `../v3`
- **THEN** la validación de la configuración falla.

### Requirement: Máximo de iteraciones del Boss
El sistema SHALL aceptar `BOSS_MAX_ITERATIONS` entre 1 y 5 (por defecto 3) y SHALL rechazar valores fuera de ese rango al arrancar.

#### Scenario: Valor por defecto
- **WHEN** no se define la variable
- **THEN** el máximo es 3.

#### Scenario: Fuera de rango
- **WHEN** la variable vale 0 o 6
- **THEN** la validación de la configuración falla.
