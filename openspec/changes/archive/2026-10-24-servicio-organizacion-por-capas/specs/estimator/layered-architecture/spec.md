# Spec Delta

## Purpose

Organizar el servicio en capas con reglas de dependencia verificables, un único composition root y documentación del contrato de arquitectura.

## ADDED Requirements

### Requirement: Capas del servicio
`app/` SHALL organizarse en `foundation/`, `domain/`, `generation/{cag,rag,agentic,conversation}`, `ingestion/` y `api/`, con `config.py`, `dependencies.py` y `main.py` en la raíz. Los routers SHALL residir en `api/` y no contener lógica de negocio. Las rutas HTTP y la forma JSON de las respuestas SHALL permanecer sin cambios.

#### Scenario: Estructura esperada
- **WHEN** se inspecciona el árbol de `app/`
- **THEN** existen las capas indicadas y no existen `app/services/`, `app/routers/` ni `app/schemas/`.

#### Scenario: Contratos HTTP intactos
- **WHEN** se ejecuta la suite de pruebas de los endpoints existentes
- **THEN** todas pasan sin modificar sus aserciones sobre rutas o JSON.

### Requirement: Reglas de dependencias
Cada capa SHALL importar solo de las capas que tiene por encima: `foundation` solo de `config`; `domain/schemas` de `config` y `foundation`; cada hermano de `generation` de `config`, `foundation` y `domain/schemas` (y `agentic` además de `conversation`); `ingestion` de `config`, `foundation`, `domain/schemas` y `generation/rag`. Ninguna capa distinta de `api/` SHALL importar `app.dependencies`. Las excepciones existentes SHALL estar registradas con su motivo y no poder crecer.

#### Scenario: Violación nueva
- **WHEN** un módulo importa de una capa no permitida y no está en la lista de deuda
- **THEN** `tests/test_layer_dependencies.py` falla indicando la arista.

#### Scenario: Deuda resuelta
- **WHEN** una arista de la lista de deuda deja de ser una violación
- **THEN** la prueba falla pidiendo retirarla de la lista.

### Requirement: Composition root único
`app/dependencies.py` SHALL contener todas las fábricas de dependencias (pipeline, servicio de sesiones, orquestador Actor–Critic–Boss, historial, almacén de sesiones, chunker y embedder, y las de la ingesta). Las pruebas SHALL poder sustituir cualquiera con `app.dependency_overrides`.

#### Scenario: Sustitución en pruebas
- **WHEN** una prueba define `app.dependency_overrides[get_pipeline]`
- **THEN** el endpoint usa la implementación sustituida.

### Requirement: Hueco de la Sesión 8
`generation/rag/store/` y `generation/rag/retriever.py` SHALL existir solo como placeholders documentados, sin implementación.

#### Scenario: Placeholders
- **WHEN** se importan ambos módulos
- **THEN** no definen clases ni funciones y su docstring explica el hueco reservado.

### Requirement: Documentación de arquitectura
El repositorio SHALL incluir `estimador-cag/ARCHITECTURE.md` con las capas, las reglas de dependencia, el flujo de la petición, la tabla «¿dónde va mi código nuevo?», los contratos que no se rompen y el mapa de migración de rutas, y `CLAUDE.md` en la raíz con comandos Docker y convenciones.

#### Scenario: Ubicación de un módulo nuevo
- **WHEN** un desarrollador consulta la tabla «¿dónde va mi código nuevo?»
- **THEN** encuentra la capa de destino de cada tipo de módulo, incluidos los de la Sesión 7.
