# estimator/conversation-memory Specification

## Purpose
Conservar el hilo de una conversación larga más allá de la ventana de turnos recientes mediante un resumen acumulativo y anclas literales de compromisos relevantes.

## Requirements

### Requirement: Resumen acumulativo
El sistema SHALL combinar el resumen anterior con los turnos que salen de la ventana reciente y conservar el resultado como resumen de la sesión. Si el resumidor falla o devuelve un texto vacío, SHALL conservar el resumen anterior sin fallar la estimación. El resumen SHALL normalizarse (sin marcado ni caracteres de control) y acotarse en longitud antes de reinyectarse en el prompt.

#### Scenario: Primer desbordamiento
- **WHEN** un turno sale de la ventana y no hay resumen previo
- **THEN** el resumidor recibe el turno retirado y su resultado pasa a ser el resumen de la sesión.

#### Scenario: Resumen acumulado
- **WHEN** salen nuevos turnos de la ventana y ya existe un resumen
- **THEN** el resumidor recibe el resumen anterior y los turnos retirados y el resultado sustituye al anterior.

#### Scenario: Fallo del resumidor
- **WHEN** el resumidor lanza un error o devuelve texto vacío
- **THEN** el resumen anterior se conserva intacto y la estimación se completa.

### Requirement: Anclas de memoria
El sistema SHALL conservar fuera de la ventana reciente, como pares literales usuario/asistente, los turnos que contienen compromisos relevantes: contratos, alcance cerrado, presupuestos acordados, fechas límite y restricciones legales o regulatorias. Las anclas SHALL no ser resumidas, SHALL no repetirse y SHALL estar acotadas en número descartando las más antiguas.

#### Scenario: Turno con presupuesto acordado
- **WHEN** un turno que contiene un presupuesto acordado sale de la ventana
- **THEN** el par completo se conserva como ancla y no se incluye en el material a resumir.

#### Scenario: Turno sin compromisos
- **WHEN** un turno sin compromisos sale de la ventana
- **THEN** se incorpora al resumen y no se crea ningún ancla.

#### Scenario: Límite de anclas
- **WHEN** se supera el máximo de anclas
- **THEN** se descarta la más antigua y se conservan las más recientes en orden cronológico.

### Requirement: Separación de estructura, detección y política
La estructura del historial, el detector de anclas y la política de compresión SHALL ser componentes independientes. La política SHALL ejecutarse después de completar cada turno. El detector SHALL poder ser heurístico o basado en LLM según `ANCHOR_DETECTION_MODE`; ante un fallo del detector LLM SHALL recurrir al heurístico. SHALL registrarse el nombre de las reglas que identificaron cada ancla, sin el texto del turno.

#### Scenario: Política tras cada turno
- **WHEN** se confirma un turno de una sesión
- **THEN** la política de compresión se ejecuta una vez y sin turnos retirados no realiza llamadas al LLM.

#### Scenario: Reglas registradas
- **WHEN** el detector identifica un ancla
- **THEN** el resultado incluye los nombres de las reglas coincidentes y se registra un evento con ellas.

#### Scenario: Detector LLM no disponible
- **WHEN** el modo es `llm` y la llamada falla o su respuesta no es válida
- **THEN** se usa el detector heurístico para ese turno.

### Requirement: Composición del contexto
Los mensajes enviados al estimador SHALL construirse, en este orden, con el prompt de sistema actualizado (incluido el resumen acumulativo en un bloque de datos), los pares ancla, los turnos recientes dentro de la ventana y el mensaje de usuario actual. Sin resumen ni anclas la lista SHALL ser la misma que antes de este cambio.

#### Scenario: Orden de los mensajes
- **WHEN** la sesión tiene resumen, anclas y turnos recientes
- **THEN** la lista empieza por el mensaje de sistema con el resumen, sigue con las anclas, después los turnos recientes y termina con el mensaje actual, alternando roles.

#### Scenario: Sesión sin memoria extendida
- **WHEN** la sesión no tiene resumen ni anclas
- **THEN** los mensajes son idénticos a los del comportamiento anterior.

#### Scenario: Ventana reciente
- **WHEN** hay anclas
- **THEN** los turnos recientes siguen sin superar `max_turns` contando el actual.
