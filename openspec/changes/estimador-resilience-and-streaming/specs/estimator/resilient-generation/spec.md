# Spec Delta

## Purpose

Reducir llamadas repetidas y recuperar fallos de proveedores preservando resultados y métricas verificables del estimador.

## ADDED Requirements

### Requirement: Caché exacta y opcional
El sistema SHALL reutilizar respuestas completas con TTL configurable, sin mezclar prompts, entradas, proveedores, modelos, políticas de fallback ni parámetros diferentes. SHALL conservar tokens y finalización originales y distinguir coste original de coste de la solicitud. Un fallo o dato inválido de caché SHALL permitir generar normalmente.

#### Scenario: Repetición válida
- **WHEN** se repite una solicitud con caché vigente
- **THEN** no se invoca al proveedor, cache_hit es true y el coste de la solicitud es cero.

#### Scenario: Caché inválida o expirada
- **WHEN** Redis falla, el contenido es inválido o la entrada expiró
- **THEN** se genera sin caché y sin exponer datos de conexión.

#### Scenario: Respuesta truncada
- **WHEN** el proveedor termina por límite de tokens o falla a mitad de la respuesta
- **THEN** la respuesta no se almacena en caché.

### Requirement: Recuperación explícita
El sistema SHALL permitir timeout y reintentos configurables y un proveedor/modelo alternativo opcional. SHALL intentar el alternativo tras errores transitorios del principal, pero no ante errores de validación/autenticación ni cuando el usuario exige un modelo concreto. SHALL informar el proveedor efectivo sin bloquear otras solicitudes.

#### Scenario: Principal no disponible
- **WHEN** el principal agota sus reintentos por timeout o límite de solicitudes
- **THEN** se intenta el alternativo configurado y sus tokens y modelo aparecen en la respuesta.

#### Scenario: Modelo solicitado
- **WHEN** el usuario pide un modelo explícito y este falla
- **THEN** el sistema conserva ese error saneado y no sustituye el modelo.

### Requirement: Costes y registros honestos
El sistema SHALL calcular costes por fase con tarifas configuradas por millón de tokens y usar null para modelos sin tarifa. SHALL distinguir el coste original de generación del coste estimado de llamadas exitosas de la solicitud, sin presentarlo como facturación exacta de intentos fallidos. En producción SHALL emitir logs JSON sin claves ni transcripciones.

#### Scenario: Precio desconocido
- **WHEN** una fase utiliza un modelo sin tarifa configurada
- **THEN** el coste agregado es null en lugar de cero.

#### Scenario: Dos fases y caché parcial
- **WHEN** una fase se obtiene de caché y otra se genera
- **THEN** el coste de solicitud incluye solo la fase generada y los tokens originales se conservan por fase.
