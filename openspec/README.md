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

El cambio `estimador-resilience-and-streaming` contiene propuesta, diseño,
especificaciones por capacidad y tareas verificables:

```sh
openspec status --change estimador-resilience-and-streaming
openspec instructions apply --change estimador-resilience-and-streaming --json
openspec validate estimador-resilience-and-streaming --strict
```

Las especificaciones actuales viven en `specs/`; los cambios en curso y su
evidencia viven en `changes/`. Tras revisar un cambio completado puede archivarse
con `openspec archive <nombre>`, que integra los deltas en las especificaciones.
El historial previo permanece disponible, pero el trabajo nuevo usa OpenSpec.
Referencia oficial: https://github.com/Fission-AI/OpenSpec.
