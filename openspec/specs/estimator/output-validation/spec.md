# estimator/output-validation Specification

## Purpose
Garantizar que el resultado devuelto es coherente según reglas de negocio y que las estimaciones sin base suficiente se presentan como no estimables.

## Requirements

### Requirement: Resultado estructurado de la estimación
El sistema SHALL representar la estimación como `EstimationResult` con `summary`, `confidence_pct` (0–100), `phases`, `total_duration_weeks` y `total_cost_eur`, y cada `Phase` con `name`, `description`, `duration_weeks` (> 0) y `cost_eur` (≥ 0). `EstimationResult` SHALL exponer `out_of_scope`, verdadero cuando `confidence_pct` es inferior a 30.

#### Scenario: Resultado válido
- **WHEN** el modelo devuelve un JSON con todos los campos
- **THEN** se parsea a `EstimationResult`.

#### Scenario: Campo fuera de rango
- **WHEN** `confidence_pct` es 120 o una fase tiene coste negativo
- **THEN** el resultado se considera inválido y se pide una corrección.

### Requirement: Validación de negocio con corrección automática
El sistema SHALL exigir que la suma de `cost_eur` de las fases coincida con `total_cost_eur` (tolerancia de 0,01 EUR) y que, con `confidence_pct` inferior a 30, `summary` empiece por `Out of scope:`. Si el JSON no se puede parsear o una regla falla, SHALL volver a pedir la respuesta al modelo incluyendo el error concreto, hasta `VALIDATION_MAX_ATTEMPTS` intentos. Agotados los intentos SHALL responder 502 saneado. Los tokens y costes de todos los intentos SHALL sumarse.

#### Scenario: Suma incorrecta corregida
- **WHEN** el primer intento tiene fases que suman 100 y un total de 120, y el segundo es coherente
- **THEN** la respuesta es 200 con el segundo resultado y se hicieron dos llamadas, la segunda con el error de la suma en el mensaje de usuario.

#### Scenario: Confianza baja sin prefijo
- **WHEN** `confidence_pct` es 20 y `summary` no empieza por `Out of scope:`
- **THEN** se solicita una corrección.

#### Scenario: Intentos agotados
- **WHEN** todos los intentos son inválidos
- **THEN** la respuesta es 502 con un mensaje saneado que no incluye la salida del modelo.

### Requirement: Estimaciones fuera de alcance
Cuando un resultado válido tiene `confidence_pct` inferior a 30, el sistema SHALL normalizarlo con una única fase placeholder (`name="No estimable"`, `cost_eur=0`, `duration_weeks=1`), `total_cost_eur=0` y `total_duration_weeks=1`, conservando `summary` con el prefijo `Out of scope:`. El cliente SHALL mostrar un aviso claro de «no estimable» en lugar de una tabla de fases con cifras.

#### Scenario: Normalización
- **WHEN** el modelo devuelve confianza 15 con varias fases y costes
- **THEN** el resultado tiene una fase placeholder de coste 0 y una semana, y suma de costes igual al total.

#### Scenario: Presentación
- **WHEN** el cliente recibe `out_of_scope=true`
- **THEN** muestra «No estimable» con el resumen y no presenta importes ni duración.
