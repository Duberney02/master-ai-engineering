# estimator-web

Aplicación web Rails para el [estimador](../estimador-cag/README.md). No tiene claves de proveedores: habla solo HTTP
con la API (cliente [Faraday](https://lostisland.github.io/faraday/)). Su única persistencia es el historial del
Chunking Lab (PostgreSQL). La organización del código y sus reglas están en [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Funcionalidad

- **Inicio** (`/`): un panel con una tarjeta por contexto. La barra de navegación marca la sección activa y muestra el
  **modelo primario** vigente del servicio (si el servicio no responde, el indicador simplemente no aparece).
- **Chunking Lab** (`/rag/chunking_comparisons`): compara las ocho estrategias de chunking sobre los presupuestos
  históricos (`POST /embeddings/compare`). Formulario con las estrategias (las gratuitas vienen marcadas; las de pago
  llevan aviso de coste y de la clave que necesitan y son opt-in), consultas predefinidas o propias y `top-k`. El
  resultado trae la **tabla de estadísticas** (chunks, min/p50/p95/máx de tokens, huérfanos y obesos), **barras de coste**
  y un **playground de recuperación** con la similitud de cada chunk y la indicación padre/hijo de la estrategia
  jerárquica. Cada ejecución se **guarda** (PostgreSQL) para revisarla sin repagar; la llamada usa un tiempo de espera
  ampliado (600 s) solo para ella.
- **Ajustes** (`/ai_settings`): ve y cambia los modelos del LLM en tiempo de ejecución (primario, respaldo, crítico,
  metadatos, resumen y los dos chunkers con LLM). Un selector vacío restablece el valor por defecto. El modelo de
  embeddings se muestra de solo lectura.
- **Estimaciones** (`/estimations/new`): formulario con descripción (20–80 000 caracteres), tipo de proyecto, nivel de detalle, formato de salida y
  versión de prompt. Admite **cargar un archivo `.txt`** (UTF-8, máx. 400 KB) que sustituye a la descripción.
  Al enviar muestra un **indicador de carga y un temporizador** de segundos transcurridos.
- **Conversación con memoria**: al abrir el formulario crea una sesión en la API (`POST /api/v1/sessions`) y guarda su
  `session_id` en la sesión de Rails; cada estimación se envía como multipart a `/api/v1/sessions/{id}/estimate`. Admite
  **varios adjuntos PDF o Word** (hasta 5 de 10 MB; la API extrae su texto) y, con adjuntos, un mensaje corto. Si la API
  pierde la sesión (reinicio o caducidad) abre otra y avisa; el formulario conserva lo escrito.
- **Barra lateral izquierda** (como en Streamlit): **metadatos del proyecto** de la conversación (nombre, equipo,
  tecnologías, alcance) con el botón **«Nueva conversación»**, prompt de sistema renderizado, ejemplos few-shot y métricas de la última llamada (modelo, tokens, latencia, coste, caché); se puede ocultar con «».
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
| `ESTIMATOR_COMPARE_TIMEOUT` | `600` | segundos de espera de la comparación del Chunking Lab (solo esa llamada) |
| `ESTIMATOR_BADGE_TIMEOUT` | `2` | segundos de espera del indicador del modelo primario de la barra |
| `DATABASE_URL` | — | PostgreSQL del historial del Lab (`postgres://usuario:clave@host:5432/base`); el entrypoint la prepara al arrancar |
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

Minitest + WebMock: nunca llaman a la API real. Todo se ejecuta en Docker, con una base de datos PostgreSQL efímera, desde
la raíz del repositorio:

```bash
docker compose -f docker-compose.verify.yml run --rm web-test          # bin/rails test
docker compose -f docker-compose.verify.yml run --rm web-test test test/models/rag   # un subconjunto
docker compose -f docker-compose.verify.yml run --rm web-lint          # RuboCop (omakase)
```

Cubren: los **clientes por contexto** y la taxonomía de errores (`test/services/estimator_ai`), los **contratos**
(`test/models/rag`, `test/models/ai`), los **controllers** con su mapeo de errores (`test/controllers`: estimaciones,
conversación, inicio, Ajustes y Chunking Lab) y los **helpers** (`test/helpers`: navegación e indicador del modelo
primario). `test_helper` simula siempre `GET /api/v1/config/models`, de modo que cualquier página —la barra incluida—
se renderiza sin el servicio levantado.
