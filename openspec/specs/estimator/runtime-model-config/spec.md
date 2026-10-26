# estimator/runtime-model-config Specification

## Purpose
Cambiar los modelos del LLM en tiempo de ejecución sin tocar `.env` ni reiniciar, con overrides persistentes y una API de lectura y escritura.

## Requirements

### Requirement: Overrides persistentes por knob
El sistema SHALL permitir sustituir en tiempo de ejecución los modelos `primary_model`, `fallback_model`, `critic_model`, `metadata_model`, `summary_model`, `propositional_chunker_model` y `contextual_chunker_model`. Los overrides SHALL guardarse en Redis, sobrevivir a reinicios y compartirse entre procesos. `Settings` SHALL seguir siendo el valor por defecto. El modelo de embeddings SHALL no ser configurable en runtime.

#### Scenario: Persistencia entre procesos
- **WHEN** un proceso guarda un override y otro proceso lo consulta
- **THEN** el segundo ve el mismo valor.

#### Scenario: Redis caído al leer
- **WHEN** Redis no responde al leer los overrides
- **THEN** el servicio usa los valores de `Settings` sin error.

#### Scenario: Redis caído al escribir
- **WHEN** Redis no responde al guardar un override
- **THEN** la escritura falla de forma visible y no se aplica ningún cambio.

### Requirement: Resolución sin reiniciar
Cada solicitud SHALL resolver los modelos efectivos una vez al empezar y usarlos en el wrapper del LLM, en las tareas (crítico, resumen, anclas, metadatos) y en la clave de las cachés, sin reconstruir clientes. Un cambio SHALL aplicar a partir de la siguiente solicitud. Un override del primario SHALL cambiar también el proveedor según el nombre del modelo y SHALL suplantar a `estimator_model`; un override cuyo proveedor no tenga clave configurada SHALL ignorarse con un aviso.

#### Scenario: Cambio entre solicitudes
- **WHEN** se llama al generador, se cambia el primario y se vuelve a llamar
- **THEN** la segunda llamada usa el nuevo modelo y, tras restablecer, la tercera vuelve al anterior.

#### Scenario: Otro proveedor
- **WHEN** el primario se cambia a un modelo de Anthropic y hay clave de Anthropic
- **THEN** la llamada se hace con el SDK de Anthropic.

#### Scenario: Tarea con modelo de otro proveedor
- **WHEN** el modelo de una tarea es de Anthropic y el primario es de OpenAI
- **THEN** la llamada de esa tarea usa el SDK de Anthropic.

#### Scenario: Claves de caché
- **WHEN** se cambia el primario entre dos solicitudes idénticas
- **THEN** la caché exacta usa claves distintas y la semántica filtra por cada modelo.

### Requirement: Fallback bajo un override
El fallback SHALL ser independiente del primario: ante un fallo reintentable del primario efectivo se SHALL intentar el fallback efectivo (el de `Settings` o su override), y sin fallback configurado no SHALL haber segundo intento.

#### Scenario: Primario sobrescrito con fallback
- **WHEN** el primario sobrescrito falla de forma reintentable y hay fallback configurado
- **THEN** se atiende la solicitud con el modelo de fallback.

### Requirement: Catálogo de modelos
El sistema SHALL ofrecer un catálogo configurable (`available_models`) y la API SHALL devolver solo los modelos cuyo proveedor tenga clave configurada.

#### Scenario: Sin clave de Anthropic
- **WHEN** no hay `ANTHROPIC_API_KEY`
- **THEN** el catálogo devuelto no incluye modelos de Anthropic.

### Requirement: GET /api/v1/config/models
El servicio SHALL exponer `GET /api/v1/config/models` con, por knob, `effective`, `default` y `overridden`, la lista `available_models`, el `embedding_model` y una nota que indique que es de solo lectura.

#### Scenario: Sin overrides
- **WHEN** no hay overrides
- **THEN** todos los knobs tienen `overridden` falso y `effective` igual a `default`.

### Requirement: PUT /api/v1/config/models
El servicio SHALL exponer `PUT /api/v1/config/models` con `{models: {knob: modelo|null}}`: actualización parcial y todo-o-nada, donde `null` restablece el valor por defecto. SHALL responder `422` ante un knob desconocido, un modelo fuera del catálogo o un chunker con un modelo de otro proveedor; `400` si falta la clave del proveedor del modelo (nombrando la variable, nunca su valor); `503` si el almacén no está disponible. Devuelve la instantánea actualizada. Cada knob modificado SHALL dejar un log de auditoría con el knob, el valor efectivo anterior, el nuevo y si fue un restablecimiento.

#### Scenario: Actualización parcial
- **WHEN** se cambia solo `primary_model`
- **THEN** los demás knobs conservan su estado.

#### Scenario: Todo o nada
- **WHEN** una de las entradas del cuerpo es inválida
- **THEN** ninguna se aplica.

#### Scenario: Restablecer
- **WHEN** se envía `null` para un knob con override
- **THEN** vuelve a `overridden` falso y a su valor por defecto.

#### Scenario: Auditoría
- **WHEN** un cambio se aplica
- **THEN** se registra `runtime_config_changed` con `key`, `old_effective`, `new_value` y `reset`.

#### Scenario: Almacén caído
- **WHEN** Redis no responde
- **THEN** la respuesta es 503 sin detalles internos.
