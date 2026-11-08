# estimator/web-ai-settings Specification

## Purpose
Ver y cambiar los modelos del servicio IA en tiempo de ejecución desde la web y mostrar el modelo primario vigente.

## Requirements

### Requirement: Pantalla de Ajustes
La pantalla `/ai_settings` de la web React SHALL mostrar, con los datos de `GET /api/ai-settings` del backend, los siete knobs de modelo con su descripción, su valor por defecto, su valor vigente (marcando los que tienen override) y un selector con los modelos del catálogo. Los chunkers SHALL ofrecer solo modelos de su proveedor. Un selector vacío SHALL significar «usar el valor por defecto». El modelo de embeddings SHALL mostrarse de solo lectura con su nota.

#### Scenario: Override visible
- **WHEN** el crítico tiene un override
- **THEN** su fila lo marca y el selector lo tiene preseleccionado.

#### Scenario: Chunkers por proveedor
- **WHEN** se muestra el selector del chunker proposicional
- **THEN** no ofrece modelos de Anthropic.

### Requirement: Guardar cambios
`PUT /api/ai-settings` del backend SHALL enviar a `PUT /api/v1/config/models` del servicio de IA todos los knobs recibidos, con los vacíos como `null`, ignorando los desconocidos, y no llamar al servicio si no hay ninguno. Con éxito SHALL responder 200 con el catálogo actualizado y la web SHALL mostrar un aviso de confirmación. Un rechazo (400 o 422) SHALL responder 422 con el detalle de la API y la web SHALL mantener el formulario; un almacén no disponible o un servicio inalcanzable, 503, sin exponer la URL interna.

#### Scenario: Restablecer
- **WHEN** se deja vacío el selector de un knob con override
- **THEN** se envía `null` para ese knob.

#### Scenario: Modelo sin clave
- **WHEN** el servicio rechaza un modelo por clave ausente
- **THEN** la pantalla muestra el detalle con la variable nombrada.

#### Scenario: Servicio caído al leer
- **WHEN** el servicio no responde al abrir los ajustes
- **THEN** el backend responde 503 y la web muestra un aviso sin formulario.

### Requirement: Indicador del modelo primario
La barra de navegación de la web React SHALL mostrar el modelo primario vigente obtenido de `GET /api/primary-model`, que el backend cachea unos segundos con un tiempo de espera corto. Si el servicio falla, el indicador SHALL omitirse sin afectar a la página, y el fallo SHALL cachearse brevemente en el backend. Guardar en Ajustes SHALL descartar la caché del backend y volver a consultar el indicador para que el cambio se vea de inmediato.

#### Scenario: Servicio caído
- **WHEN** el servicio no responde
- **THEN** la página se renderiza sin el indicador.

#### Scenario: Refresco al guardar
- **WHEN** se guarda un cambio del modelo primario
- **THEN** el indicador muestra el modelo nuevo sin recargar la página.
