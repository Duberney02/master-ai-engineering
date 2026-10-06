# estimator-web

Aplicación web Rails para el [estimador](../estimador-cag/README.md). No tiene base de datos ni claves de
proveedores: habla solo HTTP con la API (cliente [Faraday](https://lostisland.github.io/faraday/)).

## Funcionalidad

- **Formulario** con descripción (20–80 000 caracteres), tipo de proyecto, nivel de detalle, formato de salida y
  versión de prompt. Admite **cargar un archivo `.txt`** (UTF-8, máx. 400 KB) que sustituye a la descripción.
  Al enviar muestra un **indicador de carga y un temporizador** de segundos transcurridos.
- **Barra lateral izquierda** (como en Streamlit): prompt de sistema renderizado, ejemplos few-shot y métricas de la última llamada (modelo, tokens, latencia, coste, caché); se puede ocultar con «».
- **Historial** (`/estimations`): las últimas 10 estimaciones (fecha, tipo, confianza, coste, procedencia y extracto).
- **Resultado** (`/estimations/:id`): resumen, **confianza, duración y coste totales** y **tabla de fases**. Con baja
  confianza (< 30 %) muestra «No estimable» sin cifras. Indica si fue generada o servida de la caché exacta/semántica.
- **Errores saneados**: conexión o tiempo agotado, 400 de guardrails (se muestra el `message` de la API), 422, 404 y 5xx se
  traducen a mensajes en español; nunca se muestran cuerpos crudos, trazas ni la URL interna.

## Configuración

| Variable | Por defecto | Uso |
|---|---|---|
| `ESTIMATOR_API_URL` | `http://localhost:8000` | URL de la API del estimador |
| `ESTIMATOR_OPEN_TIMEOUT` | `5` | segundos para abrir la conexión |
| `ESTIMATOR_READ_TIMEOUT` | `300` | segundos de espera de la respuesta (las transcripciones largas tardan) |
| `SECRET_KEY_BASE` | — | obligatoria en producción (`openssl rand -hex 64`) |

## Ejecución

Con todo el stack (recomendado), desde la raíz del repositorio: `docker compose up --build` → <http://localhost:3000>.

Aislada, con una API ya en marcha:

```bash
docker build -t estimator-web .
docker run --rm -p 3000:3000 -e SECRET_KEY_BASE=$(openssl rand -hex 64) \
  -e ESTIMATOR_API_URL=http://host.docker.internal:8000 estimator-web
```

## Pruebas

Minitest + WebMock: nunca llaman a la API real. Sin Ruby local, en Docker:

```bash
docker run --rm -v "$PWD:/rails" -w /rails ruby:3.4-slim sh -c \
  "apt-get update -qq && apt-get install -y -qq build-essential git libyaml-dev && bundle install && bin/rails test"
```

Cubren el cliente (`test/services`), el formulario y la carga de `.txt` (`test/models`) y los flujos completos —envío,
rechazos antes de llamar a la API, baja confianza, historial vacío o desactivado y API caída— (`test/controllers`).
