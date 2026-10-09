# Spec Delta

## Purpose

Convertir documentos PDF y Word adjuntos en texto plano de forma local, determinista y acotada, para incorporarlos a la transcripción antes de llamar al modelo.

## ADDED Requirements

### Requirement: Extracción local de PDF y Word
El sistema SHALL extraer el texto de adjuntos PDF y Word (`.docx`) en el propio servicio, sin enviar los archivos al proveedor del LLM. Cada adjunto SHALL incorporarse al texto de la transcripción precedido de un separador `--- attachment: <nombre> ---` con el nombre de archivo saneado (sin rutas, saltos de línea ni caracteres de control). El tipo SHALL determinarse por la extensión y comprobarse con el contenido del archivo.

#### Scenario: PDF con texto
- **WHEN** se adjunta un PDF con texto extraíble
- **THEN** el texto resultante incluye `--- attachment: <nombre>.pdf ---` seguido del texto del documento.

#### Scenario: Documento Word
- **WHEN** se adjunta un `.docx` con párrafos y tablas
- **THEN** el texto de ambos aparece tras el separador de ese archivo.

#### Scenario: Varios adjuntos
- **WHEN** se adjuntan varios archivos
- **THEN** cada uno aparece con su propio separador, en el orden recibido, después del texto de la transcripción.

#### Scenario: Nombre malicioso
- **WHEN** el nombre del archivo contiene saltos de línea, rutas o un falso separador
- **THEN** el separador emitido usa solo el nombre base saneado en una única línea.

### Requirement: Límites y errores de adjuntos
El sistema SHALL rechazar con errores saneados y sin exponer el contenido: tipos no admitidos (415), archivos que superan el tamaño máximo, más archivos del máximo o texto total superior al máximo de la descripción (413), archivos corruptos, cifrados o sin texto extraíble (422). La extracción SHALL acotar el número de páginas y el tamaño descomprimido de los `.docx` y SHALL no bloquear el bucle de eventos.

#### Scenario: Tipo no admitido
- **WHEN** se adjunta un archivo que no es PDF ni `.docx`, o cuyo contenido no corresponde a su extensión
- **THEN** la respuesta es 415 con un mensaje saneado.

#### Scenario: Archivo demasiado grande
- **WHEN** un adjunto supera el tamaño máximo
- **THEN** la respuesta es 413.

#### Scenario: PDF sin texto
- **WHEN** el PDF no contiene texto extraíble (por ejemplo, escaneado)
- **THEN** la respuesta es 422 indicando que no se pudo extraer texto.
