# Spec Delta

## MODIFIED Requirements

### Requirement: Capas del servicio
`app/` SHALL organizarse en `foundation/`, `domain/`, `generation/{cag,rag,agentic,conversation}`, `ingestion/` y `api/`, con `config.py`, `dependencies.py` y `main.py` en la raíz. Los routers SHALL residir en `api/` y no contener lógica de negocio. Las rutas y la forma JSON de la API de IA SHALL permanecer sin cambios. La demo HTML de navegador SHALL retirarse del montaje estático.

#### Scenario: Estructura esperada
- **WHEN** se inspecciona el árbol de `app/`
- **THEN** existen las capas indicadas y no existen `app/services/`, `app/routers/` ni `app/schemas/`.

#### Scenario: Contratos HTTP intactos
- **WHEN** se ejecuta la suite de pruebas de los endpoints existentes
- **THEN** todas pasan sin modificar sus aserciones sobre rutas o JSON.

#### Scenario: Demo retirada
- **WHEN** se intenta abrir la antigua demo HTML de SSE
- **THEN** la API no sirve la página y su endpoint SSE conserva el contrato.

## ADDED Requirements

### Requirement: Responsabilidades de la aplicación consolidada
React SHALL encargarse de presentación e interacción. Go SHALL componer los contextos de aplicación, proteger sus operaciones, persistir el Lab y llamar por HTTP a la API de IA exclusivamente mediante su adaptador. Las validaciones y la lógica de IA SHALL permanecer en estimador-cag. Go SHALL conservar las sondas operativas y retirar la presentación HTML tras paridad.

#### Scenario: Revisión de límites
- **WHEN** se ejecutan las pruebas arquitectónicas y se inspeccionan los recorridos de Ajustes y Lab tras el corte
- **THEN** React usa solo contratos Go, las validaciones de IA se ejecutan en Python, el Lab persiste en Go y su backend carece de rutas de renderizado
