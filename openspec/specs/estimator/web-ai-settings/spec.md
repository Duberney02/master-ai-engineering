# estimator/web-ai-settings Specification

## Purpose
Ver y cambiar los modelos del servicio IA en tiempo de ejecución desde la web y mostrar el modelo primario vigente.

## Requirements

### Requirement: Pantalla de Ajustes
`GET /ai_settings` SHALL mostrar los siete knobs de modelo con su descripción, su valor por defecto, su valor vigente (marcando los que tienen override) y un selector con los modelos del catálogo. Los chunkers SHALL ofrecer solo modelos de su proveedor. Un selector vacío SHALL significar «usar el valor por defecto». El modelo de embeddings SHALL mostrarse de solo lectura con su nota.

#### Scenario: Override visible
- **WHEN** el crítico tiene un override
- **THEN** su fila lo marca y el selector lo tiene preseleccionado.

#### Scenario: Chunkers por proveedor
- **WHEN** se muestra el selector del chunker proposicional
- **THEN** no ofrece modelos de Anthropic.

### Requirement: Guardar cambios
`PATCH /ai_settings` SHALL enviar a `PUT /api/v1/config/models` todos los knobs del formulario, con los vacíos como `null`, ignorando los desconocidos, y no llamar al servicio si no hay ninguno. Con éxito SHALL redirigir con un aviso de confirmación. Un rechazo (400 o 422) SHALL responder 422 mostrando el detalle de la API y manteniendo el formulario; un almacén no disponible o un servicio inalcanzable, 503, sin exponer la URL interna.

#### Scenario: Restablecer
- **WHEN** se deja vacío el selector de un knob con override
- **THEN** se envía `null` para ese knob.

#### Scenario: Modelo sin clave
- **WHEN** el servicio rechaza un modelo por clave ausente
- **THEN** la pantalla muestra el detalle con la variable nombrada.

#### Scenario: Servicio caído al leer
- **WHEN** el servicio no responde al abrir los ajustes
- **THEN** se responde 503 con un aviso y sin formulario.

### Requirement: Indicador del modelo primario
La barra de navegación SHALL mostrar el modelo primario vigente, obtenido con un tiempo de espera corto y cacheado unos segundos. Si el servicio falla, el indicador SHALL omitirse sin afectar a la página, y el fallo SHALL cachearse brevemente. Guardar en Ajustes SHALL descartar la caché para que el cambio se vea de inmediato.

#### Scenario: Servicio caído
- **WHEN** el servicio no responde
- **THEN** la página se renderiza sin el indicador.

#### Scenario: Refresco al guardar
- **WHEN** se guarda un cambio del modelo primario
- **THEN** la siguiente página muestra el modelo nuevo.
