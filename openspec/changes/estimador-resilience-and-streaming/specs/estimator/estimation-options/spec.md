# Spec Delta

## Purpose

Ampliar las opciones de estimación con razonamiento y presupuesto económico sin alterar las respuestas predeterminadas en español.

## ADDED Requirements

### Requirement: Presupuesto de razonamiento explícito
El sistema SHALL aceptar thinking_budget opcional entre 1024 y 15000 para modelos Anthropic, ajustar el máximo de salida para dejar al menos 1024 tokens de respuesta y rechazar combinaciones incompatibles antes de llamar al proveedor. SHALL aplicar el presupuesto solo a la fase de estimación.

#### Scenario: Anthropic seleccionado
- **WHEN** se solicita thinking_budget=2048 con proveedor Anthropic
- **THEN** se habilita razonamiento con ese presupuesto y max_tokens es al menos 3072.

#### Scenario: Proveedor incompatible
- **WHEN** se pide thinking_budget con OpenAI
- **THEN** se rechaza con 422 sin llamar al proveedor.

### Requirement: Presupuesto económico opcional
El sistema SHALL admitir include_project_costs y tarifas positivas configurables de desarrollo y diseño en EUR/hora. Cuando se active SHALL solicitar una tabla económica adicional con rol, horas, tarifa y coste, y evaluar su coherencia numérica sin eliminar las comprobaciones de horas existentes.

#### Scenario: Activado
- **WHEN** el usuario activa costes de proyecto
- **THEN** el prompt incluye tarifas y el resultado evaluado informa si las multiplicaciones y el total económico coinciden.

#### Scenario: Compatibilidad
- **WHEN** no se activan las opciones nuevas
- **THEN** se mantiene la estructura española existente y no se exige tabla económica.
