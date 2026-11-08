## 1. Preparación
- [x] 1.1 Rama `session_09/pre-work` desde `master`; validar el cambio con `openspec validate`
- [x] 1.2 Levantar el stack con `docker compose up -d` y verificar la salud de los servicios

## 2. Sección 1 — Arquitectura actual
- [x] 2.1 Inspeccionar rutas, módulos y Compose reales
- [x] 2.2 Diagrama Mermaid de tres capas con el servicio IA a un nivel más, marcando dónde acaba lo implementado

## 3. Sección 2 — Trace de `02_ambiguous.txt`
- [x] 3.1 Ingestar el corpus de ejemplo (la base debe tener presupuestos)
- [x] 3.2 Paso 1: embedding de la transcripción (dimensión, norma, primera y última componente)
- [x] 3.3 Paso 2: `POST /search` con k=5, respuesta cruda
- [x] 3.4 Paso 3: lectura de cada chunk (presupuesto, sector, relevancia)

## 4. Secciones 3 y 4 — Diagnóstico y propuesta
- [x] 4.1 Cinco fallos con problema / causa / solución, referenciando el trace
- [x] 4.2 Segundo diagrama Mermaid con lo nuevo marcado y párrafo de ≤10 líneas

## 5. Cierre
- [x] 5.1 Revisar criterios de aceptación y `openspec validate --all --strict`
- [x] 5.2 Archivar el cambio (`openspec archive`) y sincronizar specs
- [x] 5.3 Commit en la rama, push y PR contra `master`
