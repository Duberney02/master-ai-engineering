# estimator/audience-resolution Specification

## Purpose
Determinar para quién se redacta una estimación y poder explicar y corregir esa decisión.

## Requirements

### Requirement: Perfiles de audiencia
El sistema SHALL soportar los perfiles `executive`, `pm`, `developer` y `default`.

#### Scenario: Perfiles disponibles
- **WHEN** se consultan los perfiles soportados
- **THEN** son exactamente `executive`, `pm`, `developer` y `default`.

### Requirement: Resolución por reglas ordenadas
El sistema SHALL resolver la audiencia evaluando en orden reglas sobre la transcripción y los metadatos, y SHALL aplicar la primera que coincida: confidencialidad o contexto regulatorio → `executive`; presencia de varios términos técnicos (al menos tres distintos, contando las tecnologías de los metadatos) → `developer`; equipo pequeño indicado en los metadatos (cinco personas o menos) → `pm`. Sin coincidencias SHALL resolver `default`. El resultado SHALL incluir el nombre de la regla aplicada.

#### Scenario: Contexto regulatorio
- **WHEN** la transcripción menciona el RGPD o un acuerdo de confidencialidad
- **THEN** la audiencia es `executive` con la regla `confidentiality_or_regulatory`, aunque haya términos técnicos y equipo pequeño.

#### Scenario: Varios términos técnicos
- **WHEN** la transcripción o las tecnologías de los metadatos suman al menos tres términos técnicos distintos y no hay contexto regulatorio
- **THEN** la audiencia es `developer` con la regla `technical_terms`.

#### Scenario: Equipo pequeño
- **WHEN** los metadatos indican un equipo de cinco personas o menos y no coincide ninguna regla anterior
- **THEN** la audiencia es `pm` con la regla `small_team`.

#### Scenario: Sin coincidencias
- **WHEN** ninguna regla coincide
- **THEN** la audiencia es `default` con la regla `no_match`.

### Requirement: Audiencia explícita
El sistema SHALL permitir indicar la audiencia con el parámetro opcional `tier` y esa selección SHALL prevalecer sobre las reglas automáticas, con el nombre de regla `explicit`. Un valor no soportado SHALL rechazarse sin llamar al LLM.

#### Scenario: Selección explícita
- **WHEN** se envía `tier=pm` y el texto es regulatorio
- **THEN** la audiencia resuelta es `pm` con la regla `explicit`.

#### Scenario: Valor inválido
- **WHEN** se envía `tier=ceo`
- **THEN** la respuesta es 422 y la sesión no cambia.

### Requirement: Última audiencia en la sesión
La sesión SHALL conservar la última audiencia resuelta y el nombre de la regla aplicada tras cada turno completado, y SHALL no modificarlos si el turno falla.

#### Scenario: Turno completado
- **WHEN** se completa una estimación
- **THEN** la sesión guarda la audiencia y la regla de ese turno.

#### Scenario: Turno fallido
- **WHEN** la estimación falla
- **THEN** la audiencia y la regla anteriores se conservan.
