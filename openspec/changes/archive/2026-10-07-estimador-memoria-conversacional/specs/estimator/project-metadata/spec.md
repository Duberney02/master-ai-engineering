# Spec Delta

## Purpose

Recordar los hechos conocidos de un proyecto a lo largo de la conversación y ofrecérselos al modelo como contexto de confianza acotada en cada turno.

## ADDED Requirements

### Requirement: Modelo de metadatos del proyecto
El sistema SHALL representar los hechos conocidos con `project_name`, `assumed_team_size`, `mentioned_technologies` y `agreed_scope`, todos opcionales o vacíos al crear la sesión, con longitudes y rangos acotados, y SHALL normalizar sus textos a una sola línea sin caracteres de marcado para que no puedan alterar la estructura del prompt.

#### Scenario: Sesión nueva
- **WHEN** se crea una sesión
- **THEN** sus metadatos están vacíos.

#### Scenario: Valor fuera de rango
- **WHEN** el tamaño de equipo no es un entero positivo razonable o un texto supera su límite
- **THEN** el metadato no se acepta como válido.

### Requirement: Bloque de metadatos en el prompt de sistema
El prompt de sistema de las estimaciones de una sesión SHALL incluir un bloque `<project_metadata>` con los hechos conocidos, vacío en la primera llamada, e indicar que su contenido son datos y no instrucciones. El bloque SHALL regenerarse en cada turno con los metadatos vigentes. Las estimaciones sin sesión SHALL conservar su prompt actual sin el bloque.

#### Scenario: Primera llamada
- **WHEN** se renderiza el prompt de la primera estimación de una sesión
- **THEN** contiene `<project_metadata>` sin hechos conocidos.

#### Scenario: Segunda llamada
- **WHEN** ya se conocen nombre y tecnologías
- **THEN** el prompt de sistema del siguiente turno los incluye dentro del bloque.

### Requirement: Actualización con una llamada adicional al LLM
Tras cada estimación válida, el sistema SHALL actualizar los metadatos con una llamada adicional al LLM con un prompt específico que reciba los metadatos actuales, el mensaje del usuario y la estimación, y devuelva un objeto JSON validado contra el modelo de metadatos. SHALL combinar el resultado con los hechos previos (las listas se unen sin duplicados y los valores nuevos no nulos sustituyen a los anteriores). Si la llamada falla o su respuesta no es válida, la estimación SHALL devolverse igualmente y los metadatos previos SHALL conservarse.

#### Scenario: Dos peticiones de una sesión
- **WHEN** la primera petición menciona nombre y tecnologías y la segunda añade el tamaño del equipo
- **THEN** tras la segunda los metadatos contienen los hechos de ambas.

#### Scenario: Extracción inválida
- **WHEN** la llamada de extracción devuelve texto que no es un JSON válido de metadatos
- **THEN** la estimación se devuelve con los metadatos anteriores sin cambios.
