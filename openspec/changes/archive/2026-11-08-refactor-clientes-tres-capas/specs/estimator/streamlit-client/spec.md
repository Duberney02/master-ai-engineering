## ADDED Requirements

### Requirement: Proyecto Streamlit independiente
El cliente Streamlit SHALL vivir en `estimator-streamlit/` con su propio `Dockerfile`, `pyproject.toml`, `uv.lock`, `README.md`, `.dockerignore` y pruebas. Su código SHALL NOT importar nada de `estimador-cag/app`: los tipos del contrato (tipos de proyecto, niveles de detalle, formatos, resultado, metadatos, límites de descripción) SHALL definirse localmente a partir del contrato JSON del backend Go. La imagen SHALL NOT incluir claves de proveedores.

#### Scenario: Sin imports del servicio de IA
- **WHEN** se buscan imports de `app.` o rutas a `estimador-cag` en `estimator-streamlit/`
- **THEN** no hay ninguno y las pruebas del proyecto pasan con `streamlit-test`.

#### Scenario: Imagen propia
- **WHEN** se construye `estimator-streamlit/Dockerfile`
- **THEN** la imagen arranca `streamlit run streamlit_app.py` en el puerto 8501 con healthcheck sobre `/_stcore/health`.

### Requirement: Solo HTTP con el backend Go
El cliente SHALL hablar únicamente con `estimator-web` por HTTP, hacia la URL de la variable `ESTIMATOR_WEB_URL` (por defecto `http://localhost:3000`), usando las rutas `/api/...` del backend. SHALL NOT usar `ESTIMATOR_API_BASE_URL` ni rutas `/api/v1/` del servicio de IA. Crear la conversación al cargar la página, mantener su `conversation_id` en `st.session_state`, enviar cada estimación (multipart con transcripción o `.txt`, adjuntos PDF/Word y opciones) a `POST /api/conversations/{id}/estimations` y ofrecer «Nueva conversación» SHALL comportarse como el chat anterior. El prompt de sistema, los ejemplos few-shot y las métricas SHALL obtenerse de `GET /api/prompt-preview` y de la respuesta de la estimación.

#### Scenario: Conversación al cargar
- **WHEN** se abre la página
- **THEN** el cliente hace `POST /api/conversations`, guarda el `conversation_id` y lo reutiliza en los envíos hasta pulsar «Nueva conversación».

#### Scenario: Sesión caducada
- **WHEN** el backend responde 404 a una estimación
- **THEN** el cliente abre otra conversación y muestra «La conversación anterior expiró en el servidor; se inició una nueva. Vuelve a enviar tu mensaje.».

#### Scenario: Errores saneados
- **WHEN** el backend responde con un error o no se puede conectar
- **THEN** el cliente muestra el `detail` saneado o «No se pudo conectar con el backend del estimador.» sin trazas, claves ni URLs internas.

### Requirement: Formulario y validaciones del chat
El cliente SHALL presentar el formulario con descripción (20–80 000 caracteres), carga de `.txt` UTF-8 de hasta 400 000 bytes que sustituye a la descripción, adjuntos PDF/Word, tipo de proyecto, nivel de detalle, formato de salida y versión de prompt, y SHALL rechazar sin llamar al backend las entradas inválidas con los mismos mensajes en español que la web React. SHALL mostrar el resultado (resumen, confianza, duración, coste y tabla de fases; «No estimable» si `out_of_scope`), los metadatos del proyecto y las métricas de la última llamada.

#### Scenario: Descripción fuera de rango
- **WHEN** la descripción tiene menos de 20 o más de 80 000 caracteres y no hay adjuntos
- **THEN** se muestra «La descripción debe tener entre 20 y 80000 caracteres.» y no se llama al backend.

#### Scenario: Resultado fuera de alcance
- **WHEN** el resultado tiene `out_of_scope=true`
- **THEN** se muestra «No estimable» con el motivo y ninguna cifra de coste o duración.
