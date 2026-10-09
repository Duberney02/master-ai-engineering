# Spec Delta

## Purpose

Orquestar la generación, la revisión y la decisión sobre una estimación con una traza auditable.

## ADDED Requirements

### Requirement: Decisión del Boss en código
El Boss SHALL decidir en código, sin llamadas al LLM: aceptar cuando el veredicto es `accept`; devolver el borrador con reservas cuando es `reject`; regenerar cuando es `needs_iteration` y quedan iteraciones, y devolver el borrador con reservas cuando es `needs_iteration` y se han agotado.

#### Scenario: Aceptación
- **WHEN** el crítico emite `accept`
- **THEN** la decisión es aceptar.

#### Scenario: Rechazo
- **WHEN** el crítico emite `reject`
- **THEN** la decisión es devolver con reservas, aunque queden iteraciones.

#### Scenario: Regeneración
- **WHEN** el crítico emite `needs_iteration` en la iteración 1 de 3
- **THEN** la decisión es regenerar.

#### Scenario: Iteraciones agotadas
- **WHEN** el crítico emite `needs_iteration` en la última iteración
- **THEN** la decisión es devolver con reservas.

### Requirement: Orquestación y límite de iteraciones
El orquestador SHALL generar una estimación, solicitar su revisión y aplicar la decisión del Boss hasta aceptar, ser rechazado o agotar `BOSS_MAX_ITERATIONS` generaciones (1 a 5, por defecto 3). Ante un fallo del crítico SHALL devolver el borrador con reservas sin fallar la estimación. Un fallo del actor SHALL propagarse sin modificar la sesión.

#### Scenario: Aceptada a la primera
- **WHEN** el primer borrador es aceptado
- **THEN** se realizan una generación y una revisión y la decisión final es `accepted`.

#### Scenario: Regenerada y aceptada
- **WHEN** el crítico pide una iteración y el segundo borrador es aceptado
- **THEN** el resultado devuelto es el segundo borrador y el total de iteraciones es 2.

#### Scenario: Límite alcanzado
- **WHEN** el crítico pide iterar en todas las iteraciones permitidas
- **THEN** se realizan exactamente el máximo de generaciones y se devuelve el último borrador con la decisión final `returned_with_reservations`.

#### Scenario: Crítico no disponible
- **WHEN** la llamada del crítico falla o su respuesta no es válida
- **THEN** se devuelve el borrador con reservas y la traza marca el error del crítico.

### Requirement: Feedback en la regeneración y único turno final
La regeneración SHALL incorporar al prompt los defectos, categorías, severidades y correcciones sugeridas del crítico. La sesión SHALL guardar únicamente el resultado final como un único turno, sin los borradores intermedios ni los mensajes de feedback.

#### Scenario: Feedback en el prompt
- **WHEN** se regenera tras un veredicto `needs_iteration`
- **THEN** los mensajes de la segunda generación incluyen la descripción y la corrección sugerida de cada defecto.

#### Scenario: Un solo turno
- **WHEN** el flujo realiza tres generaciones
- **THEN** la sesión contiene un único turno nuevo con el mensaje del usuario y la respuesta final.

### Requirement: Traza de auditoría
El resultado SHALL incluir una traza con, por iteración, el número, el veredicto del crítico, la confianza de la revisión, un resumen de los defectos (recuento por severidad y categorías) y la decisión del Boss, además del total de iteraciones, la decisión final y las reservas pendientes.

#### Scenario: Traza completa
- **WHEN** el flujo termina tras dos iteraciones
- **THEN** la traza contiene dos entradas con veredicto, confianza, defectos y decisión, `total_iterations` igual a 2 y la decisión final.

#### Scenario: Reservas
- **WHEN** la decisión final es devolver con reservas
- **THEN** la traza lista los defectos pendientes o la explicación del rechazo.
