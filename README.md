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
├── estimator-web-go/             ← backend HTTP de aplicación en Go: API REST/SSE, autorización y Chunking Lab (sin HTML)
├── estimator-web-react/          ← cliente web único: React + TypeScript servido por Nginx
├── docker-compose.yml            ← pila de integración: React/Nginx, Go, IA, Redis Stack y dos PostgreSQL
├── docker-compose.verify.yml     ← pruebas, lint, evaluación y OpenSpec en contenedores
├── openspec/                     ← especificaciones y cambios SDD actuales
└── .agents/skills/               ← integración OpenSpec para Codex
```

## Proyectos

| Proyecto | Descripción | Stack |
|---|---|---|
| [`estimador-cag/`](./estimador-cag/README.md) | API FastAPI que genera estimaciones iniciales de proyectos de software a partir de transcripciones de reuniones con clientes, usando CAG (Context-Augmented Generation): los ejemplos históricos se inyectan directamente en el prompt del LLM, sin embeddings ni vector store. Soporta OpenAI y Anthropic como proveedores. | Python 3.11, FastAPI, Pydantic, uv, OpenAI SDK, Anthropic SDK |

| [`estimator-web-go/`](./estimator-web-go/README.md) | Backend de aplicación en Go. Única puerta de React hacia la IA: expone la API REST y SSE pública con rutas explícitas, validación de transporte, errores saneados y cancelación hasta Python; decide la autorización de las operaciones administrativas (denegadas por defecto) y guarda en su PostgreSQL el historial del **Chunking Lab**. No sirve HTML. | Go 1.25, net/http, pgx |
| [`estimator-web-react/`](./estimator-web-react/README.md) | Cliente web único del estimador: formulario con carga de `.txt`, PDF y Word, conversación con memoria, historial, resultado, barra lateral del prompt, **Ajustes de IA** y **Chunking Lab**. Se sirve con Nginx, que reenvía `/api/` a Go (mismo origen, sin CORS). | React 19, TypeScript, Vite, Vitest, nginx |

A medida que se agreguen nuevos proyectos del máster (RAG, agentes,
evaluación, etc.), se listarán aquí con un enlace a su propio README.

## Arquitectura de la pila de integración

```
Navegador ──► React/Nginx ──► Go ──► estimador-cag (IA) ──► Redis Stack · PostgreSQL (pgvector) · proveedores de IA
 (túnel SSH)   127.0.0.1:3001   │
                                └──► PostgreSQL de Go (historial del Chunking Lab)
```

- **React** es el único cliente. Habla solo con Go, por su propio origen.
- **Go** es la única puerta hacia `estimador-cag`; ningún cliente llama a la IA, a Redis ni a PostgreSQL.
- **`estimador-cag`** concentra la lógica de IA, RAG, embeddings y las credenciales de los proveedores.
- Redes de Docker: `client-net` (React y Go, sin NAT de salida), `service-net`, `go-data-net` y `ai-data-net` (internas) y
  `ai-egress-net` (solo la IA, para HTTPS hacia los proveedores).
- Solo React/Nginx publica un puerto: `127.0.0.1:3001`. Go, la API de IA (8000), Redis y PostgreSQL no publican nada. Las
  sondas son internas: `/healthz` (Nginx), `/up` (Go, `estimator-web healthcheck`), `/health` (IA), `pg_isready` y `redis-cli ping`.

**Estado y alcance.** Es un entorno **privado de desarrollo**, validado en una pila temporal de pruebas; no es un despliegue
de producción. Solo lo usa el operador autorizado mediante túnel SSH, sin exposición pública ni uso multiusuario hasta
completar `homelab-authentication-authorization`. Las operaciones administrativas (Ajustes de IA y Chunking Lab) devuelven
403 por defecto en la composición normal. PostgreSQL, Ollama y Open WebUI del homelab son servicios preexistentes y quedan
fuera de este Compose.

## Arranque con Docker

```bash
cp estimador-cag/.env.example estimador-cag/.env   # completa la API key del proveedor (solo la recibe estimador-cag)
cp .env.example .env                               # opcional: contraseñas propias
docker compose up --build
```

Los puertos 3000 y 5432 del host pueden estar ocupados por otros servicios del homelab; esta pila ya no publica ninguno
salvo `127.0.0.1:3001`. Para inspeccionar un servicio usa sondas internas, por ejemplo:

```bash
docker compose exec estimador-cag python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read())"
docker compose exec postgres psql -U estimator -d estimator
docker compose exec estimator-web /estimator-web healthcheck
```

Variables opcionales (`POSTGRES_PASSWORD`, `WEB_DB_PASSWORD`, `ESTIMATOR_PUBLIC_ORIGIN`) en [`.env.example`](./.env.example).
`ESTIMATOR_PUBLIC_ORIGIN` (por defecto `http://localhost:3001`) es el origen que Go acepta en las mutaciones del navegador.
Para desarrollar solo el backend de IA con recarga en caliente usa
[`estimador-cag/docker-compose.yml`](./estimador-cag/docker-compose.yml); su perfil `diagnostico` publica `127.0.0.1:8000`
y no forma parte de la pila de integración.

### Acceso desde Windows (VS Code Remote SSH y navegador)

Desde PowerShell, deja abierto un túnel con el mismo puerto local (el origen canónico es `http://localhost:3001`):

```powershell
ssh -N -L 3001:127.0.0.1:3001 <usuario>@<servidor>
```

y abre <http://localhost:3001>. Sin el túnel, `http://<servidor>:3001` no responde: el puerto solo escucha en el loopback del
servidor. El flujo no requiere Docker Desktop, Node.js, Python ni Go en Windows.

### Limitaciones conocidas

- Autenticación y roles reales: pendientes de `homelab-authentication-authorization` (hoy todo lo administrativo está cerrado).
- Los servicios del host que escuchan en todas las interfaces, como `sshd`, son alcanzables desde los contenedores por el
  gateway. El aislamiento de red de Docker (redes internas, `client-net` sin NAT) no sustituye a una política de firewall
  del host; su endurecimiento queda para la fase de seguridad del homelab.
- Reutilización de PostgreSQL/pgvector y Ollama del homelab, proveedores Ollama y separación de proveedores de generación y
  embeddings: objetivos de integración futuros (ver `AGENTS.md`).
- La vista previa del prompt es informativa: no incluye la memoria de la sesión.

## Conversación con memoria y adjuntos

La API admite **sesiones conversacionales** (`POST /api/v1/sessions` y `POST /api/v1/sessions/{id}/estimate`): recuerdan
los últimos 6 turnos y los metadatos del proyecto (nombre, equipo, tecnologías, alcance) y aceptan adjuntos PDF/Word cuyo
texto se extrae en local. React crea la sesión al cargar la página, permite transcripción más varios archivos, muestra los metadatos en la barra
lateral y ofrece «Nueva conversación»; Go intermedia las llamadas. Las sesiones viven en memoria de la API (se pierden al
reiniciar y una recarga completa del navegador inicia otra conversación). Detalle, decisiones y límites en el
[README de `estimador-cag`](./estimador-cag/README.md#conversación-con-memoria-sesiones).

La memoria conversacional conserva además un **resumen acumulativo** y **anclas** (compromisos relevantes) de los turnos
que salen de la ventana, adapta el enfoque del prompt a la **audiencia** (`tier`: executive, pm, developer, default), ofrece
`GET /api/v1/sessions/{id}` con el estado de la sesión y `POST /api/v1/sessions/{id}/estimate-acb`, que añade un crítico
independiente y un Boss en código con traza de auditoría. El dataset de referencia de 16 casos y su runner viven en
`estimador-cag/evals/`. Detalle en el README de `estimador-cag`.

Las validaciones se ejecutan en contenedores (`docker-compose.verify.yml`: nada se instala en el host):

```bash
docker compose -f docker-compose.verify.yml run --rm api-test                       # pytest (API de IA)
docker compose -f docker-compose.verify.yml run --rm api-lint check .               # Ruff
docker compose -f docker-compose.verify.yml run --rm web-test                       # go test (con PostgreSQL efímero)
docker compose -f docker-compose.verify.yml run --rm web-lint                       # gofmt y go vet
docker compose -f docker-compose.verify.yml run --rm react-test                     # Vitest
docker compose -f docker-compose.verify.yml run --rm react-build                    # tsc y vite build
docker compose -f docker-compose.verify.yml run --rm api-eval --list                # dataset de evaluación
docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
```

Usa siempre un nombre de proyecto propio (`-p <nombre>`) para no compartir redes ni volúmenes entre ejecuciones. Los recorridos
de extremo a extremo, la matriz de aislamiento de red y la evidencia del cambio activo están en
[`openspec/changes/archive/2026-11-26-homelab-route-clients-through-go/`](./openspec/changes/archive/2026-11-26-homelab-route-clients-through-go/verificacion-bloque4.md).
Ahí se describen también los arneses (`verificar-red-bloque4.sh`, `verificar-e2e-bloque6.sh`), que solo operan sobre proyectos
`hl-s1`, `hl-s2` o `hl-s3`.

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

- Docker y Docker Compose. El ciclo de las aplicaciones (dependencias, compilación, pruebas, lint, ejecución y despliegue)
  se ejecuta en contenedores. Git, Claude Code, Codex CLI, NVM, Node.js y OpenSpec pueden instalarse nativamente en Ubuntu.
- Claves de API de los proveedores de LLM que use el proyecto (OpenAI y/o Anthropic), solo en `estimador-cag/.env`
  (excluido de Git); cada proyecto documenta las suyas en su propio `.env.example`.

## Cómo trabajar con un proyecto

Cada proyecto se desarrolla y se prueba con Docker Compose desde la raíz (ver arriba y `docker-compose.verify.yml`).
Consulta el `README.md` de cada carpeta para los detalles específicos (endpoints, variables de entorno, ejemplos de uso y
pruebas).

## Autor

Duberney Cardona — [github.com/Duberney02](https://github.com/Duberney02)
