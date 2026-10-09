# Spec Delta

## Purpose

Añadir una versión del prompt de estimación adaptada a la audiencia.

## ADDED Requirements

### Requirement: Prompt v4 adaptado a la audiencia
El sistema SHALL ofrecer la versión `v4` de la plantilla de estimación, en español y con el mismo contrato estructurado de salida, que ajusta el enfoque a la audiencia: para `executive`, riesgos, síntesis y lenguaje accesible; para `pm`, hitos, entregables y dependencias; para `developer`, tecnologías, integraciones y supuestos técnicos; para `default`, un enfoque general. Las versiones `v1`, `v2` y `v3` SHALL producir el mismo texto que antes.

#### Scenario: Enfoque por audiencia
- **WHEN** se renderiza `v4` para cada audiencia
- **THEN** el prompt contiene el enfoque propio de esa audiencia y no el de las demás, y contiene el contrato de salida JSON.

#### Scenario: Versiones anteriores intactas
- **WHEN** se renderiza `v1`, `v2` o `v3`
- **THEN** el texto no contiene la sección de audiencia y es idéntico al anterior a este cambio.

#### Scenario: Versión disponible
- **WHEN** se listan las versiones de prompt
- **THEN** `v4` aparece y la versión por defecto de `POST /estimate` sigue siendo `v3`.
