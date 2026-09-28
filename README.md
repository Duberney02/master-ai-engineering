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
│   ├── app/                      ← servidor FastAPI (routers, services, wrapper LLM, caché)
│   ├── estimator_client/         ← cliente HTTP/SSE usado por la interfaz Streamlit
│   ├── tests/                    ← suite de pytest
│   ├── docs/superpowers/         ← spec y plan de diseño del proyecto
│   └── README.md                 ← documentación completa del proyecto
└── .superpowers/sdd/              ← historial del flujo Spec-Driven Development
    └── <fecha>-<proyecto>/        ← briefs, paquetes de revisión y progreso por tarea
```

## Proyectos

| Proyecto | Descripción | Stack |
|---|---|---|
| [`estimador-cag/`](./estimador-cag/README.md) | API FastAPI que genera estimaciones iniciales de proyectos de software a partir de transcripciones de reuniones con clientes, usando CAG (Context-Augmented Generation): los ejemplos históricos se inyectan directamente en el prompt del LLM, sin embeddings ni vector store. Soporta OpenAI y Anthropic (con fallback), streaming SSE, caché Redis e interfaz Streamlit desacoplada que consume la API por HTTP. | Python 3.11, FastAPI, Pydantic, uv, OpenAI SDK, Anthropic SDK, Redis, Streamlit, Docker Compose |

A medida que se agreguen nuevos proyectos del máster (RAG, agentes,
evaluación, etc.), se listarán aquí con un enlace a su propio README.

## Metodología de trabajo (SDD)

Los proyectos de este repositorio se construyen siguiendo un flujo de
**Spec-Driven Development**: primero se redacta una especificación de
requisitos, luego un plan técnico, después se descompone en tareas
pequeñas y trazables, se implementan una a una con revisión, y finalmente
se verifica el resultado contra la especificación original.

El historial de ese proceso (specs, planes, briefs de tarea, paquetes de
revisión y bitácora de progreso) queda registrado en
[`.superpowers/sdd/`](./.superpowers/sdd/), organizado por fecha y nombre
de proyecto. Dentro de cada proyecto, la especificación y el plan de
diseño también se archivan en `docs/superpowers/` (por ejemplo,
[`estimador-cag/docs/superpowers/`](./estimador-cag/docs/superpowers/)).

## Requisitos generales

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) como gestor de dependencias y entornos
- Claves de API de los proveedores de LLM que use cada proyecto (OpenAI y/o
  Anthropic); cada uno documenta las suyas en su propio `.env.example`

## Cómo trabajar con un proyecto

```bash
cd <nombre-del-proyecto>       # p. ej. estimador-cag
uv sync --all-extras           # instala dependencias (servidor + cliente + dev)
cp .env.example .env           # configura variables/API keys
uv run uvicorn app.main:app --reload   # o el comando de arranque del proyecto
```

Consulta el `README.md` de cada carpeta para los detalles específicos
(endpoints, variables de entorno, ejemplos de uso y tests).

## Autor

Duberney Cardona — [github.com/Duberney02](https://github.com/Duberney02)
