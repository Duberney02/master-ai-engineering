# estimator/architecture-diagnosis Specification

## Purpose
Conservar en el repositorio un diagnóstico arquitectónico versionado del flujo RAG (diagrama, trace, fallos y propuesta), de modo que las decisiones de la sesión siguiente partan de evidencia reproducible.

## Requirements

### Requirement: Diagnóstico arquitectónico versionado
El repositorio SHALL contener `arquitectura-actual.md` en su raíz con cuatro secciones: diagrama de la arquitectura
actual, trace anotado de una transcripción, fallos identificados y propuesta de evolución.

#### Scenario: El trace es reproducible
- **WHEN** se lee la sección del trace
- **THEN** cada paso incluye el comando exacto ejecutado contra el stack en Docker y la respuesta cruda del sistema

#### Scenario: Los fallos se apoyan en evidencia
- **WHEN** se lee un fallo del diagnóstico
- **THEN** su problema observado referencia una observación concreta del trace
