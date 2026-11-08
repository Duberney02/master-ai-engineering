## Why

La Sesión 09 pide, como pre-work, un **diagnóstico** (no una construcción) del sistema RAG tal como queda al cierre de
la Sesión 08: el servicio sabe ingestar presupuestos, vectorizarlos y buscar por similitud (`POST /search`), pero no
sabe convertir una transcripción de reunión en una estimación apoyada en esos presupuestos. Antes de construir hay que
dejar por escrito qué existe, qué pasa de verdad cuando entra una transcripción ambigua y qué piezas faltan.

## What Changes

- Nuevo documento `arquitectura-actual.md` en la raíz del repo, a partir de `examples/transcripts/TEMPLATE.md`, con
  cuatro secciones: (1) diagrama Mermaid de la arquitectura actual, (2) trace anotado de `02_ambiguous.txt` contra el
  stack en Docker, (3) cinco fallos con evidencia del trace, (4) propuesta de evolución con segundo diagrama.
- Material de apoyo ya presente en `examples/` (`transcripts/`, `trace_s09.py`) se incorpora al repositorio; el script
  es solo un cliente del trace.

### Fuera de alcance (non-goals)

Reformulación de queries, reranking, nuevo retriever o módulo de generación; cambios en `/search`; endpoints nuevos;
cualquier código de servicio. El cambio no toca `estimador-cag/app/`.

## Capabilities

### New Capabilities
- `architecture-diagnosis`: el repositorio conserva un diagnóstico arquitectónico versionado del flujo RAG.

## Impact

- Archivos nuevos: `arquitectura-actual.md`, `examples/`. Sin cambios de código, contratos ni infraestructura.
