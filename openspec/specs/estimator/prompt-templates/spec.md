# estimator/prompt-templates Specification

## Purpose
Mantener los prompts de estimación como plantillas versionadas, fuera del código, que se renderizan de forma determinista y verificable sin llamar al modelo.

## Requirements

### Requirement: Renderizado versionado de prompts
El sistema SHALL renderizar, a partir de una solicitud estructurada y una versión, un prompt de sistema y un prompt de usuario independientes. Cada versión SHALL vivir en su propio directorio con plantillas de sistema, usuario y ejemplos, de modo que añadir una versión no requiera cambiar el código que las consume. Una variable ausente en la plantilla SHALL producir un error en lugar de texto vacío. Una versión inexistente o con formato inválido SHALL rechazarse sin leer archivos fuera del directorio de prompts.

#### Scenario: Descripción del usuario
- **WHEN** se renderiza una solicitud con una descripción
- **THEN** el prompt de usuario contiene la descripción literal dentro del bloque `<project_description>`.

#### Scenario: Versión desconocida
- **WHEN** se pide la versión `v99` o `../v1`
- **THEN** el render falla con un error de versión desconocida.

#### Scenario: Versiones con variación deliberada
- **WHEN** se renderiza la misma solicitud con `v1` y con `v2`
- **THEN** ambos prompts de sistema son distintos y cada uno respeta el formato y el nivel de detalle pedidos.

### Requirement: Instrucciones condicionales por formato y detalle
El prompt de sistema SHALL incluir las instrucciones de formato de salida que correspondan solo a `output_format` (`phases_table`, `line_items`, `narrative`) y las instrucciones de detalle que correspondan solo a `detail_level` (`summary`, `medium`, `detailed`). SHALL incluir ejemplos few-shot bien formados presentados en el formato solicitado.

#### Scenario: Tabla de fases
- **WHEN** `output_format=phases_table`
- **THEN** el prompt de sistema menciona la columna `confidence_pct`.

#### Scenario: Narrativa
- **WHEN** `output_format=narrative`
- **THEN** el prompt de sistema no menciona `confidence_pct`.

#### Scenario: Detalle con asunciones por fase
- **WHEN** `detail_level=detailed`
- **THEN** el prompt de sistema pide listar las asunciones de cada fase, y con `detail_level=summary` esa instrucción no aparece.

### Requirement: Proyectos de referencia
Cuando la solicitud incluye proyectos de referencia, el prompt de usuario SHALL listar cada uno con su nombre, descripción y horas reales. Sin proyectos de referencia no SHALL aparecer ese bloque.

#### Scenario: Con referencias
- **WHEN** la solicitud incluye dos proyectos de referencia
- **THEN** el prompt de usuario contiene ambos dentro del bloque `<reference_projects>`.

#### Scenario: Sin referencias
- **WHEN** `reference_projects` falta o es null
- **THEN** el prompt de usuario no contiene el bloque `<reference_projects>`.

### Requirement: Trazabilidad del render
Cada renderizado SHALL emitir un evento de log estructurado con la versión del prompt y un hash estable del contenido renderizado. El evento no SHALL incluir el texto del prompt ni la descripción del usuario.

#### Scenario: Evento emitido
- **WHEN** se renderiza dos veces la misma solicitud con la misma versión
- **THEN** se emiten dos eventos con la misma versión y el mismo hash y sin la descripción.

### Requirement: Bloque de metadatos del proyecto
Las plantillas de sistema SHALL admitir un bloque `<project_metadata>` opcional con los hechos conocidos del proyecto. Con metadatos presentes (aunque vacíos) el bloque SHALL renderizarse indicando que su contenido son datos y no instrucciones; sin metadatos SHALL omitirse y el prompt SHALL ser idéntico al anterior.

#### Scenario: Sin sesión
- **WHEN** se renderiza una solicitud sin metadatos
- **THEN** el prompt de sistema no contiene `<project_metadata>`.

#### Scenario: Con metadatos vacíos
- **WHEN** se renderiza con metadatos vacíos
- **THEN** contiene el bloque sin hechos conocidos.

#### Scenario: Con metadatos
- **WHEN** se renderiza con nombre, equipo y tecnologías
- **THEN** el bloque los contiene.
