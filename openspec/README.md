# OpenSpec en este repositorio

OpenSpec es el flujo SDD, no una dependencia del servidor Python. Configuración
verificada con CLI **1.13.2**, Node **24.14.1** y esquema `spec-driven`.
Los seis skills Codex están versionados en `.agents/skills/`.

Para otra máquina (Node 20.19 o posterior):

```sh
npm install -g @fission-ai/openspec@1.13.2
openspec --version
openspec list
openspec validate --all --strict
```

En Codex, invocar `$openspec-propose`, `$openspec-apply-change`,
`$openspec-sync-specs` y `$openspec-archive-change`. En escritorio pueden
seleccionarse desde Skills; recargar la sesión si no aparecen tras clonar.
No se requiere regenerarlos en cada checkout. Para añadir otro agente:
`openspec init --tools <id>` (consultar `openspec init --help`).

Cada cambio contiene propuesta, diseño, especificaciones por capacidad, tareas
verificables y evidencia de verificación. Para consultar uno en curso:

```sh
openspec list
openspec status --change <nombre>
openspec validate <nombre> --strict
```

Los cambios completados están en `changes/archive/`:
`2026-09-29-estimador-resilience-and-streaming`,
`2026-09-29-estimador-structured-prompts`,
`2026-10-05-estimador-structured-result-guardrails-cache` y
`2026-10-06-estimador-historial-web-transcripciones-largas`.

Las especificaciones actuales viven en `specs/`; los cambios en curso y su
evidencia viven en `changes/`. Tras revisar un cambio completado puede archivarse
con `openspec archive <nombre>`, que integra los deltas en las especificaciones.
El historial previo permanece disponible, pero el trabajo nuevo usa OpenSpec.
Referencia oficial: https://github.com/Fission-AI/OpenSpec.
