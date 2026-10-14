# Spec Delta

## Purpose

Configurar el límite de iteraciones del Boss.

## ADDED Requirements

### Requirement: Máximo de iteraciones del Boss
El sistema SHALL aceptar `BOSS_MAX_ITERATIONS` entre 1 y 5 (por defecto 3) y SHALL rechazar valores fuera de ese rango al arrancar.

#### Scenario: Valor por defecto
- **WHEN** no se define la variable
- **THEN** el máximo es 3.

#### Scenario: Fuera de rango
- **WHEN** la variable vale 0 o 6
- **THEN** la validación de la configuración falla.
