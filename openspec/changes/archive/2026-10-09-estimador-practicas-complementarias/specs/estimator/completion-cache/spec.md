# Spec Delta

## Purpose

Garantizar con pruebas herméticas el comportamiento de la caché de completions sobre Redis.

## ADDED Requirements

### Requirement: Ida y vuelta de la caché
La caché SHALL devolver exactamente el diccionario guardado con `set` al consultarlo con `get`, incluidos caracteres no ASCII, y SHALL devolver `None` para una clave inexistente. Sin `REDIS_URL` SHALL comportarse como desactivada.

#### Scenario: Guardar y leer
- **WHEN** se guarda un diccionario con texto en español y se lee con la misma clave
- **THEN** se obtiene un diccionario igual al guardado.

#### Scenario: Clave inexistente o caché desactivada
- **WHEN** se lee una clave que no existe o no hay `REDIS_URL`
- **THEN** el resultado es `None` y no se abre ninguna conexión cuando está desactivada.

### Requirement: Serialización robusta
Un valor almacenado que no sea JSON válido o que no sea un objeto JSON SHALL tratarse como ausente y no lanzar excepciones. Un valor no serializable SHALL no escribirse y no lanzar excepciones.

#### Scenario: Valor corrupto
- **WHEN** la clave contiene texto que no es JSON o un JSON que no es un objeto
- **THEN** `get` devuelve `None`.

#### Scenario: Valor no serializable
- **WHEN** se intenta guardar un objeto no serializable
- **THEN** la operación termina sin excepción y la clave no existe.

### Requirement: TTL
Toda entrada escrita SHALL caducar tras `CACHE_TTL` segundos.

#### Scenario: TTL aplicado
- **WHEN** se guarda una entrada con `CACHE_TTL=120`
- **THEN** el servidor informa un TTL de 120 segundos o inferior y mayor que cero.

#### Scenario: Caducidad
- **WHEN** transcurre el TTL
- **THEN** la entrada deja de existir y `get` devuelve `None`.
