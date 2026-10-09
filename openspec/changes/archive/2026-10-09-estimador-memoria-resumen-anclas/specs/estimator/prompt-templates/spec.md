# Spec Delta

## Purpose

Versionar las plantillas de las llamadas auxiliares con las mismas garantías que las de estimación.

## ADDED Requirements

### Requirement: Plantillas auxiliares versionadas
El sistema SHALL renderizar los prompts de resumen y de detección de anclas desde plantillas Jinja2 versionadas (`auxiliary/<tarea>/<vN>/`), con el mismo loader, `StrictUndefined` y validación de nombres de versión que las plantillas de estimación. Una tarea o versión inexistente SHALL producir un error explícito, y una variable ausente en el contexto SHALL fallar en lugar de renderizar vacío.

#### Scenario: Render del resumen
- **WHEN** se renderiza la plantilla de resumen con resumen previo y turnos
- **THEN** el prompt de usuario contiene ambos y el prompt de sistema está en español.

#### Scenario: Versión inválida
- **WHEN** se pide una versión con formato inválido o inexistente
- **THEN** se lanza `UnknownPromptVersionError`.

#### Scenario: Variable ausente
- **WHEN** falta una variable obligatoria en el contexto
- **THEN** el render falla en lugar de producir texto incompleto.
