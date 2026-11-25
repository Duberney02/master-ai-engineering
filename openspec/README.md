# OpenSpec en este repositorio

OpenSpec es la herramienta de desarrollo dirigido por especificaciones (SDD) del monorepo. El CLI se fija en **1.13.2** y el proyecto usa el esquema `spec-driven`. La planificación puede ejecutarse nativamente en Ubuntu. Usa Docker Compose para el ciclo completo de las aplicaciones, incluida la gestión de dependencias, compilación, pruebas, lint y ejecución.

## OpenSpec nativo en Ubuntu

Con NVM instalado y cargado en la sesión del usuario del homelab, instala Node.js 24 y OpenSpec con npm:

```bash
nvm install 24
nvm alias default 24
nvm use default

npm install -g @fission-ai/openspec@1.13.2

openspec --version
```

Ejecuta los comandos desde la raíz del repositorio en el homelab. En una shell no interactiva, carga NVM y selecciona la versión predeterminada antes de invocar el CLI. `openspec context --json` permite comprobar la raíz que encontró OpenSpec.

## Claude Code y Codex

Abre el repositorio como directorio de trabajo del asistente. Codex lee [AGENTS.md](../AGENTS.md) directamente. Claude Code lo carga mediante `@AGENTS.md` en [CLAUDE.md](../CLAUDE.md).

Las habilidades compartidas se versionan en `.agents/skills/` para Codex y `.claude/skills/` para Claude Code. Se conservan los archivos auxiliares generados que formen parte de la configuración compartida, como `.agents/skills/.openspec-target`. Los ajustes personales y permisos locales quedan fuera de Git mediante `.claude/settings.local.json`. Un checkout obtiene las habilidades versionadas sin regenerarlas. Recarga la sesión del asistente si aún no aparecen.

Para inicializarlas o regenerarlas cuando corresponda, comprueba primero `openspec --version` y ejecuta desde la raíz:

```bash
openspec init --tools claude,codex --language Spanish --no-animation
```

OpenSpec 1.13.2 reconoce `--language Spanish` en una configuración existente si el contexto conserva el bloque de idioma que genera el CLI. El perfil predeterminado `core` incluye los seis workflows de este repositorio. Si tu instalación usa un perfil personalizado, añade `--profile core` al comando para seleccionar ese conjunto. Revisa después los dos directorios generados y los cambios de configuración antes de incorporarlos a Git. Actualiza las habilidades solo mediante OpenSpec, manteniendo la misma versión para ambos asistentes.

## Workflows

En Claude Code usa el comando con `/`. En Codex escribe el nombre con `$` o elige la habilidad desde Skills cuando esté disponible.

| Workflow | Claude Code | Codex | Uso |
|---|---|---|---|
| `openspec-explore` | `/openspec-explore` | `$openspec-explore` | Investigar el problema y aclarar requisitos antes de implementar. |
| `openspec-propose` | `/openspec-propose` | `$openspec-propose` | Crear propuesta, diseño, deltas por capacidad y tareas verificables. |
| `openspec-apply-change` | `/openspec-apply-change` | `$openspec-apply-change` | Implementar las tareas del cambio y registrar la verificación. |
| `openspec-update-change` | `/openspec-update-change` | `$openspec-update-change` | Revisar los artefactos de planificación cuando cambien los requisitos o el diseño. |
| `openspec-sync-specs` | `/openspec-sync-specs` | `$openspec-sync-specs` | Integrar deltas aprobados en las especificaciones principales sin archivar el cambio. |
| `openspec-archive-change` | `/openspec-archive-change` | `$openspec-archive-change` | Finalizar un cambio completo, integrar deltas pendientes y moverlo al archivo. |

Planifica y revisa el alcance antes de implementar. Durante la implementación, ejecuta en Docker las pruebas y verificaciones de la aplicación y conserva su evidencia en el cambio. Valida los artefactos antes de archivar. El archivado se realiza después de completar y revisar las tareas.

```sh
openspec list
openspec status --change <nombre>
openspec validate <nombre> --strict
openspec validate --all --strict
```

## OpenSpec mediante Docker

El servicio `openspec` de `docker-compose.verify.yml` monta el repositorio y usa la imagen definida en `openspec/Dockerfile`, con la misma versión del CLI. Se puede usar para validaciones reproducibles, CI/CD y entornos sin Node.js u OpenSpec nativos.

```sh
docker compose -f docker-compose.verify.yml run --rm openspec --version
docker compose -f docker-compose.verify.yml run --rm openspec list
docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
docker compose -f docker-compose.verify.yml run --rm openspec archive <cambio> --yes
```

El último comando integra los deltas y mueve el cambio a `changes/archive/`. Úsalo para un cambio completo y revisado.

## Historial

Los cambios completados están en `changes/archive/`:
`2026-09-29-estimador-resilience-and-streaming`,
`2026-09-29-estimador-structured-prompts`,
`2026-10-05-estimador-structured-result-guardrails-cache`,
`2026-10-06-estimador-historial-web-transcripciones-largas`,
`2026-10-06-estimador-web-react`,
`2026-10-06-estimador-validar-antes-de-cachear`,
`2026-10-07-estimador-memoria-conversacional` y, de la sesión 5, `2026-10-09-estimador-memoria-resumen-anclas`,
`2026-10-09-estimador-audiencia-adaptativa`, `2026-10-09-estimador-actor-critic-boss`,
`2026-10-09-estimador-evaluacion-referencia`, `2026-10-09-estimador-practicas-complementarias` y, de la sesión 6
(ingesta, PII, persistencia y adjuntos), `2026-10-19-session-6-refined`.

Las especificaciones actuales viven en `specs/`; los cambios en curso y su
evidencia viven en `changes/`. Tras revisar un cambio completado puede archivarse
con `openspec archive <nombre>`, que integra los deltas en las especificaciones.
El historial previo permanece disponible, pero el trabajo nuevo usa OpenSpec.
Referencia oficial: https://github.com/Fission-AI/OpenSpec.
