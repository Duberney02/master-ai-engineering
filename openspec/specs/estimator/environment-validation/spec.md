# estimator/environment-validation Specification

## Purpose
Evitar configuraciones de entorno y logging con valores inválidos que degradan el comportamiento en silencio.

## Requirements

### Requirement: Entorno y nivel de log válidos
El sistema SHALL aceptar para `APP_ENV` únicamente `development`, `test`, `staging` o `production`, y para `LOG_LEVEL` únicamente `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL`. SHALL normalizar mayúsculas, minúsculas y espacios alrededor del valor y SHALL rechazar cualquier otro valor al arrancar con un error de configuración. Los valores por defecto SHALL seguir siendo `development` y `DEBUG`.

#### Scenario: Valores por defecto
- **WHEN** no se definen las variables
- **THEN** `APP_ENV` es `development` y `LOG_LEVEL` es `DEBUG`.

#### Scenario: Normalización
- **WHEN** `APP_ENV=Production` y `LOG_LEVEL=warning`
- **THEN** los valores son `production` y `WARNING`.

#### Scenario: Valor inválido
- **WHEN** `APP_ENV=prod`, `APP_ENV=` o `LOG_LEVEL=verbose`
- **THEN** la validación de la configuración falla.
