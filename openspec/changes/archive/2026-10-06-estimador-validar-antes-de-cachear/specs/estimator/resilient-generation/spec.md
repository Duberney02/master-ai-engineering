# Spec Delta

## MODIFIED Requirements

### Requirement: Caché exacta y opcional
El sistema SHALL reutilizar respuestas completas con TTL configurable, sin mezclar prompts, entradas, proveedores, modelos, políticas de fallback ni parámetros diferentes. SHALL conservar tokens y finalización originales y distinguir coste original de coste de la solicitud. Un fallo o dato inválido de caché SHALL permitir generar normalmente. Cuando el llamador define un criterio de aceptación de la respuesta, el sistema SHALL almacenar solo las respuestas que lo cumplen y SHALL tratar como fallo de caché cualquier entrada guardada que ya no lo cumpla.

#### Scenario: Repetición válida
- **WHEN** se repite una solicitud con caché vigente
- **THEN** no se invoca al proveedor, cache_hit es true y el coste de la solicitud es cero.

#### Scenario: Caché inválida o expirada
- **WHEN** Redis falla, el contenido es inválido o la entrada expiró
- **THEN** se genera sin caché y sin exponer datos de conexión.

#### Scenario: Respuesta truncada
- **WHEN** el proveedor termina por límite de tokens o falla a mitad de la respuesta
- **THEN** la respuesta no se almacena en caché.

#### Scenario: Respuesta no aceptada
- **WHEN** el proveedor devuelve una respuesta que no cumple el criterio de aceptación del llamador
- **THEN** la respuesta se devuelve al llamador pero no se almacena en caché, de modo que un reintento con el mismo prompt vuelve a invocar al proveedor.

#### Scenario: Entrada cacheada que ya no es aceptable
- **WHEN** la caché contiene una respuesta que no cumple el criterio de aceptación del llamador
- **THEN** se ignora, se invoca al proveedor y la respuesta nueva, si es aceptable, sustituye a la anterior.
