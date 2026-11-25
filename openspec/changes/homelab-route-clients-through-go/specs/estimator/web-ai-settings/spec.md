# Spec Delta

## MODIFIED Requirements

### Requirement: Pantalla de Ajustes
La pantalla React de Ajustes, accesible solo a operadores autorizados, SHALL mostrar los siete knobs de modelo con su descripción, su valor por defecto, su valor vigente (marcando los que tienen override) y un selector con los modelos del catálogo. Los campos editables SHALL ser exactamente primary_model, fallback_model, critic_model, metadata_model, summary_model, propositional_chunker_model y contextual_chunker_model. Los chunkers SHALL ofrecer solo modelos de su proveedor. Un selector vacío SHALL significar «usar el valor por defecto». El modelo de embeddings SHALL mostrarse de solo lectura con su nota.

#### Scenario: Override visible
- **WHEN** el crítico tiene un override
- **THEN** su fila lo marca y el selector lo tiene preseleccionado.

#### Scenario: Chunkers por proveedor
- **WHEN** se muestra el selector del chunker proposicional
- **THEN** no ofrece modelos de Anthropic.

### Requirement: Guardar cambios
La pantalla React SHALL enviar una modificación a la API de Go, que SHALL remitir a `PUT /api/v1/config/models` interno todos los knobs del formulario, con los vacíos como `null`, ignorando los desconocidos, y no llamar al servicio si no hay ninguno. Con éxito React SHALL mostrar un aviso de confirmación. La actualización SHALL ser parcial sobre los campos recibidos y atómica en IA. Si no queda un campo reconocido, Go SHALL devolver 422 con aviso. Un rechazo (400 o 422) SHALL responder 422 mostrando un aviso saneado y manteniendo el formulario; un almacén no disponible o un servicio inalcanzable, 503, sin exponer la URL interna.

#### Scenario: Restablecer
- **WHEN** se deja vacío el selector de un knob con override
- **THEN** se envía `null` para ese knob.

#### Scenario: Modelo sin clave
- **WHEN** el servicio rechaza un modelo por clave ausente
- **THEN** la pantalla muestra un aviso saneado que menciona el nombre de la variable conocida.

#### Scenario: Servicio caído al leer
- **WHEN** el servicio no responde al abrir los ajustes
- **THEN** se responde 503 con un aviso y sin formulario.

### Requirement: Indicador del modelo primario
La barra de navegación de React SHALL mostrar el modelo primario vigente, obtenido con un tiempo de espera corto y cacheado 15 segundos, usando la proyección de solo lectura del nombre efectivo. Si el servicio falla, el indicador SHALL omitirse sin afectar a la página, y el fallo SHALL cachearse brevemente. Guardar en Ajustes SHALL descartar la caché para que el cambio se vea de inmediato.

#### Scenario: Servicio caído
- **WHEN** el servicio no responde
- **THEN** la página se renderiza sin el indicador.

#### Scenario: Refresco al guardar
- **WHEN** se guarda un cambio del modelo primario
- **THEN** la siguiente página muestra el modelo nuevo.

## ADDED Requirements

### Requirement: Consulta y actualización del catálogo
Go SHALL exponer al administrador el catálogo filtrado por claves configuradas, los valores efectivos y por defecto y sus indicadores de sobreescritura. SHALL conservar la validación y persistencia de modelos en IA.

#### Scenario: Actualización atómica
- **WHEN** se envían juntos un modelo válido y otro fuera de catálogo o de proveedor incorrecto
- **THEN** se devuelve 422 saneado y no se modifica ningún modelo
