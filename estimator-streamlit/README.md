# estimator-streamlit

Chat del estimador en **Streamlit** (capa 1). Es un cliente independiente: **solo habla HTTP con el backend
[`estimator-web-go`](../estimator-web-go/README.md)** (capa 2), que es el único que llama al servicio de IA
([`estimador-cag`](../estimador-cag/README.md)). No tiene claves de proveedores ni importa nada de `estimador-cag`; el
contrato del backend Go es su única dependencia compartida.

```
Navegador ──▶ estimator-streamlit (:8501) ──HTTP /api──▶ estimator-web (Go, :3000) ──▶ estimador-cag (:8000)
```

## Funcionalidad

- **Conversación con memoria**: al cargar la página abre una conversación (`POST /api/conversations`) y conserva su
  `conversation_id` en `st.session_state`. Cada estimación va como multipart a
  `POST /api/conversations/{id}/estimations`. «Nueva conversación» abre otra y reinicia historial, metadatos y métricas;
  si el backend responde 404 (conversación caducada) abre otra y avisa.
- **Formulario**: descripción (20–80 000 caracteres; con adjuntos puede ser corta), carga de `.txt` UTF-8 (máx. 400 KB, sustituye
  a la descripción), adjuntos PDF/Word (varios), tipo de proyecto, nivel de detalle, formato de salida y versión del
  prompt. Valida en local y el backend repite la validación.
- **Resultado**: resumen, confianza, duración, coste y tabla de fases; «No estimable» sin cifras con baja confianza.
- **Barra lateral**: metadatos del proyecto, prompt de sistema y ejemplos few-shot (`GET /api/prompt-preview`, para las
  opciones de la última solicitud) y métricas de la última llamada.
- **Errores saneados**: muestra el `detail` que redacta el backend o un mensaje genérico; nunca trazas, claves ni URLs.

## Estructura

| Archivo | Contenido |
|---|---|
| `streamlit_app.py` | la aplicación |
| `estimator_chat/client.py` | único módulo con red: cliente `httpx` del backend y errores saneados |
| `estimator_chat/models.py` | contrato JSON del backend (modelos locales: tipos, resultado, metadatos, límites) |
| `estimator_chat/support.py` | lectura del `.txt` subido |
| `tests/` | pruebas con el backend simulado en la frontera HTTP (`AppTest` de Streamlit); `test_architecture.py` impide imports del servicio de IA y referencias de red a él |

## Configuración

| Variable | Por defecto | Uso |
|---|---|---|
| `ESTIMATOR_WEB_URL` | `http://localhost:3000` | URL del backend `estimator-web` (en Compose, `http://estimator-web:3000`) |

## Todo se ejecuta en Docker

Desde la raíz del repositorio:

```sh
docker compose -f docker-compose.verify.yml run --rm streamlit-test    # pytest -q
docker compose -f docker-compose.verify.yml run --rm streamlit-lint    # ruff check
docker compose -f docker-compose.verify.yml run --rm streamlit-uv lock # regenerar uv.lock tras cambiar pyproject.toml
docker compose up --build                                              # stack completo (chat en :8501)
```

Si cambian las dependencias (`pyproject.toml`), reconstruye la imagen de pruebas:
`docker compose -f docker-compose.verify.yml build streamlit-test`. Las pruebas nunca usan claves reales ni llaman a un
servicio real.

Imagen aislada:

```sh
docker build -t estimator-streamlit estimator-streamlit
docker run --rm -p 8501:8501 -e ESTIMATOR_WEB_URL=http://host.docker.internal:3000 estimator-streamlit
```
