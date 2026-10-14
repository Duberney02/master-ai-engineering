# OpenSpec en este repositorio

OpenSpec es el flujo SDD, no una dependencia del servidor Python. Configuración
verificada con CLI **1.13.2**, Node **24.14.1** y esquema `spec-driven`.
Los seis skills Codex están versionados en `.agents/skills/`.

En este repositorio no hace falta instalar Node ni el CLI en el host: el Compose de verificación
(`docker-compose.verify.yml`, imagen en `openspec/Dockerfile`) lo ejecuta en un contenedor con la versión fijada:

```sh
docker compose -f docker-compose.verify.yml run --rm openspec list
docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
docker compose -f docker-compose.verify.yml run --rm openspec archive <cambio> --yes
```

Para otra máquina sin Docker (Node 20.19 o posterior):

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
`2026-10-05-estimador-structured-result-guardrails-cache`,
`2026-10-06-estimador-historial-web-transcripciones-largas`,
`2026-10-06-estimador-web-react`,
`2026-10-06-estimador-validar-antes-de-cachear`,
`2026-10-07-estimador-memoria-conversacional` y, de la sesión 5, `2026-10-09-estimador-memoria-resumen-anclas`,
`2026-10-09-estimador-audiencia-adaptativa`, `2026-10-09-estimador-actor-critic-boss`,
`2026-10-09-estimador-evaluacion-referencia` y `2026-10-09-estimador-practicas-complementarias`.

Las especificaciones actuales viven en `specs/`; los cambios en curso y su
evidencia viven en `changes/`. Tras revisar un cambio completado puede archivarse
con `openspec archive <nombre>`, que integra los deltas en las especificaciones.
El historial previo permanece disponible, pero el trabajo nuevo usa OpenSpec.
Referencia oficial: https://github.com/Fission-AI/OpenSpec.
