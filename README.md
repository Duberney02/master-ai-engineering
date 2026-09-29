# Master AI Engineering

Monorepo de proyectos prácticos para el máster/especialización en **AI
Engineering**: diseño, construcción y despliegue de productos de IA
end-to-end — arquitecturas CAG y RAG, bases de datos vectoriales y
embeddings, orquestación de agentes, evaluación, monitorización y puesta en
producción con criterios reales de seguridad, coste y escalabilidad.

Cada subcarpeta de este repositorio es un proyecto independiente y
autocontenido (su propio `pyproject.toml`/dependencias y su propio
`README.md` con instrucciones de instalación y uso). Este README raíz solo
indexa el repositorio; el detalle técnico de cada proyecto vive en su propia
carpeta.

## Estructura del repositorio

```
master-ai-engineering/
├── README.md                     ← este archivo (índice del repo)
├── estimador-cag/                ← proyecto 1: API de estimación de software con CAG
│   ├── app/                      ← código FastAPI (routers, services, schemas, config)
│   ├── tests/                    ← suite de pytest
│   ├── docs/                    ← documentación e historial de diseño
│   └── README.md                 ← documentación completa del proyecto
├── openspec/                     ← especificaciones y cambios SDD actuales
└── .agents/skills/               ← integración OpenSpec para Codex
```

## Proyectos

| Proyecto | Descripción | Stack |
|---|---|---|
| [`estimador-cag/`](./estimador-cag/README.md) | API FastAPI que genera estimaciones iniciales de proyectos de software a partir de transcripciones de reuniones con clientes, usando CAG (Context-Augmented Generation): los ejemplos históricos se inyectan directamente en el prompt del LLM, sin embeddings ni vector store. Soporta OpenAI y Anthropic como proveedores. | Python 3.11, FastAPI, Pydantic, uv, OpenAI SDK, Anthropic SDK |

A medida que se agreguen nuevos proyectos del máster (RAG, agentes,
evaluación, etc.), se listarán aquí con un enlace a su propio README.

## Metodología de trabajo (SDD)

Los proyectos de este repositorio se construyen siguiendo un flujo de
**Spec-Driven Development**: primero se redacta una especificación de
requisitos, luego un plan técnico, después se descompone en tareas
pequeñas y trazables, se implementan una a una con revisión, y finalmente
se verifica el resultado contra la especificación original.

El flujo actual usa **OpenSpec 1.13.2**: propuesta → especificaciones y diseño →
tareas → implementación y verificación. Consulta [la guía de OpenSpec](./openspec/README.md)
para instalar el CLI, invocar los skills de Codex y validar cambios. El historial
anterior se conserva como referencia; no forma parte del flujo actual.

## Requisitos generales

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) como gestor de dependencias y entornos
- Claves de API de los proveedores de LLM que use cada proyecto (OpenAI y/o
  Anthropic); cada uno documenta las suyas en su propio `.env.example`

## Cómo trabajar con un proyecto

```bash
cd <nombre-del-proyecto>       # p. ej. estimador-cag
uv sync --group dev            # instala dependencias
cp .env.example .env           # configura variables/API keys
uv run uvicorn app.main:app --reload   # o el comando de arranque del proyecto
```

Consulta el `README.md` de cada carpeta para los detalles específicos
(endpoints, variables de entorno, ejemplos de uso y tests).

## Autor

Duberney Cardona — [github.com/Duberney02](https://github.com/Duberney02)
