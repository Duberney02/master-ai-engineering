# estimator/conversation-sessions Specification

## Purpose
Mantener en memoria del proceso el contexto de una conversación de estimación (turnos recientes y hechos del proyecto) para que cada petición pueda apoyarse en las anteriores sin base de datos ni caché externa.

## Requirements

### Requirement: Historial con ventana deslizante
El sistema SHALL conservar el historial de cada sesión como pares completos usuario+asistente (un turno) con un máximo configurable de turnos, 6 por defecto. Al superarlo SHALL descartar los pares más antiguos completos, nunca un mensaje suelto, y SHALL conservar siempre el system prompt. Los mensajes enviados al LLM SHALL empezar por el system prompt regenerado con los metadatos vigentes, seguir con los turnos recientes en orden cronológico y terminar con el mensaje de usuario en curso, de modo que el número de turnos enviados, contando el actual, no supere el máximo.

#### Scenario: Descarte de turnos antiguos
- **WHEN** una sesión acumula más turnos que el máximo
- **THEN** solo se conservan los más recientes, en pares completos, y el system prompt sigue presente.

#### Scenario: Ventana al enviar
- **WHEN** se preparan los mensajes del turno número 8 de una sesión con máximo 6
- **THEN** la lista contiene el system prompt, como mucho 5 turnos previos y el mensaje de usuario actual, y ningún turno anterior al tercero.

#### Scenario: Máximo configurable
- **WHEN** se crea un historial con un máximo distinto del valor por defecto
- **THEN** la ventana respeta ese máximo.

### Requirement: Almacén de sesiones volátil
El sistema SHALL guardar las sesiones por identificador en un diccionario del proceso, sin base de datos ni Redis. SHALL acotar su crecimiento con un número máximo de sesiones y un tiempo de inactividad, eliminando primero las caducadas y después las menos recientes. Las sesiones SHALL perderse al reiniciar el servicio y no compartirse entre procesos; este comportamiento SHALL documentarse.

#### Scenario: Sesión existente
- **WHEN** se solicita un identificador creado y no caducado
- **THEN** se devuelve la misma sesión con su historial y metadatos.

#### Scenario: Sesión desconocida o caducada
- **WHEN** se solicita un identificador inexistente, mal formado o caducado
- **THEN** el sistema responde como no encontrada sin revelar detalles internos.

#### Scenario: Límite de sesiones
- **WHEN** se supera el máximo de sesiones
- **THEN** se elimina la sesión menos reciente y la nueva se crea con normalidad.
