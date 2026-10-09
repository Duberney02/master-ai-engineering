# Spec Delta

## Purpose

Versionar las plantillas del crítico con las mismas garantías que el resto.

## ADDED Requirements

### Requirement: Plantillas del crítico
El sistema SHALL renderizar el prompt del crítico (`system`, `user`) y el mensaje de feedback para la regeneración (`feedback`) desde plantillas Jinja2 versionadas en `auxiliary/critic/<vN>/`, con el mismo loader y `StrictUndefined`. El prompt de sistema SHALL estar en español, definir las categorías, severidades y veredictos del contrato y declarar la transcripción, los metadatos y la estimación como datos y no como instrucciones.

#### Scenario: Prompt del crítico
- **WHEN** se renderiza la plantilla con transcripción, metadatos, audiencia y estimación
- **THEN** el prompt de usuario contiene los cuatro datos y el de sistema lista todas las categorías, severidades y veredictos.

#### Scenario: Mensaje de feedback
- **WHEN** se renderiza el feedback con defectos
- **THEN** el mensaje contiene la severidad, categoría, campo, descripción y corrección sugerida de cada defecto y pide devolver únicamente el JSON completo.
