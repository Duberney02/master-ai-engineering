# Spec Delta

## Purpose

Configurar la versión del prompt de las conversaciones.

## ADDED Requirements

### Requirement: Versión del prompt conversacional
El sistema SHALL aceptar `CONVERSATION_PROMPT_VERSION` con el formato `vN` (por defecto `v4`) y SHALL rechazar cualquier otro formato al arrancar.

#### Scenario: Valor por defecto
- **WHEN** no se define la variable
- **THEN** la versión conversacional es `v4`.

#### Scenario: Formato inválido
- **WHEN** la variable vale `latest` o `../v3`
- **THEN** la validación de la configuración falla.
