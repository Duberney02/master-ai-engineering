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
│   ├── app/                      ← código FastAPI (foundation, domain, generation, ingestion, api; ver ARCHITECTURE.md)
│   ├── tests/                    ← suite de pytest
│   ├── docs/                    ← documentación e historial de diseño
│   └── README.md                 ← documentación completa del proyecto
├── estimator-web-go/             ← backend de negocio en Go: API JSON y único cliente del servicio de IA
├── estimator-web-react/          ← cliente web en React + TypeScript (SPA con proxy nginx hacia el backend Go)
├── estimator-streamlit/          ← chat Streamlit (cliente independiente del backend Go)
├── docker-compose.yml            ← stack completo en tres capas: frontends + backend Go + API de IA + Redis Stack + PostgreSQL
├── docker-compose.verify.yml     ← pruebas, lint, evaluación y OpenSpec en contenedores
├── openspec/                     ← especificaciones y cambios SDD actuales
└── .agents/skills/               ← integración OpenSpec para Codex
```

## Proyectos

| Proyecto | Descripción | Stack |
|---|---|---|
| [`estimador-cag/`](./estimador-cag/README.md) | API FastAPI que genera estimaciones iniciales de proyectos de software a partir de transcripciones de reuniones con clientes, usando CAG (Context-Augmented Generation): los ejemplos históricos se inyectan directamente en el prompt del LLM, sin embeddings ni vector store. Soporta OpenAI y Anthropic como proveedores. | Python 3.11, FastAPI, Pydantic, uv, OpenAI SDK, Anthropic SDK |

| [`estimator-web-go/`](./estimator-web-go/README.md) | Backend de negocio en Go (capa 2): API JSON bajo `/api/` (estimaciones, conversación, historial, **Chunking Lab** con historial en PostgreSQL y **Ajustes** de modelos en tiempo de ejecución) y único cliente del servicio de IA. Sin HTML ni sesión de navegador; organizado por contextos. | Go 1.25, net/http, pgx |
| [`estimator-web-react/`](./estimator-web-react/README.md) | Cliente web en React (capa 1): formulario con carga de `.txt` y adjuntos, conversación con memoria, historial, resultado, barra lateral del prompt, Chunking Lab y Ajustes. Se sirve con nginx, que reenvía `/api/` al backend Go (sin CORS). | React 19, TypeScript, Vite, Vitest, nginx |
| [`estimator-streamlit/`](./estimator-streamlit/README.md) | Chat Streamlit (capa 1): cliente independiente que solo habla HTTP con el backend Go; sin claves de proveedores ni imports del servicio de IA. | Python 3.11, Streamlit, httpx, uv |

Arquitectura en tres capas estrictas: **frontends** (React y Streamlit) → **backend de negocio** (`estimator-web-go`) →
**servicio de IA** (`estimador-cag`). Solo el backend llama al servicio de IA.

A medida que se agreguen nuevos proyectos del máster (RAG, agentes,
evaluación, etc.), se listarán aquí con un enlace a su propio README.

## Arranque completo con Docker

Desde la raíz, un único Compose levanta API, aplicaciones web, Redis Stack y PostgreSQL en la red
`estimator-net`, con volúmenes y healthchecks:

```bash
cp estimador-cag/.env.example estimador-cag/.env   # completa la API key del proveedor
docker compose up --build
```

Backend Go (API JSON) en <http://localhost:3000>, web React en <http://localhost:3001>, chat Streamlit en <http://localhost:8501> y API de IA en <http://localhost:8000/docs>. Solo esos cuatro puertos se publican. Variable
opcional (`POSTGRES_PASSWORD`) en [`.env.example`](./.env.example).

## Conversación con memoria y adjuntos

La API admite **sesiones conversacionales** (`POST /api/v1/sessions` y `POST /api/v1/sessions/{id}/estimate`): recuerdan
los últimos 6 turnos y los metadatos del proyecto (nombre, equipo, tecnologías, alcance) y aceptan adjuntos PDF/Word cuyo
texto se extrae en local. Los dos clientes (chat Streamlit y web React) abren la conversación al cargar la página a través del backend Go (`POST /api/conversations`),
permiten transcripción más varios archivos, muestran los metadatos en la barra lateral y ofrecen «Nueva conversación». Las
sesiones viven en memoria de la API (se pierden al reiniciar). Detalle, decisiones y límites en el
[README de `estimador-cag`](./estimador-cag/README.md#conversación-con-memoria-sesiones).

La memoria conversacional conserva además un **resumen acumulativo** y **anclas** (compromisos relevantes) de los turnos
que salen de la ventana, adapta el enfoque del prompt a la **audiencia** (`tier`: executive, pm, developer, default), ofrece
`GET /api/v1/sessions/{id}` con el estado de la sesión y `POST /api/v1/sessions/{id}/estimate-acb`, que añade un crítico
independiente y un Boss en código con traza de auditoría. El dataset de referencia de 16 casos y su runner viven en
`estimador-cag/evals/`. Detalle en el README de `estimador-cag`.

Las validaciones se ejecutan en contenedores (`docker-compose.verify.yml`: nada se instala en el host):

```bash
docker compose -f docker-compose.verify.yml run --rm api-test                       # pytest (servicio de IA)
docker compose -f docker-compose.verify.yml run --rm api-lint check .               # Ruff
docker compose -f docker-compose.verify.yml run --rm api-eval --list                # dataset de evaluación
docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
```

Cada cliente tiene sus servicios de prueba y lint (`web-test`/`web-lint` para el backend Go, `web-react-test`/`web-react-lint`,
`streamlit-test`/`streamlit-lint`); el comando está en el README de cada proyecto.

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
