# estimator/attachment-extraction Specification

## Purpose
Convertir documentos PDF y Word adjuntos en texto plano de forma local, determinista y acotada, para incorporarlos a la transcripción antes de llamar al modelo.

## Requirements

### Requirement: Extracción local de PDF y Word
El sistema SHALL extraer el texto de adjuntos PDF y Word (`.docx`) en el propio servicio, sin enviar los archivos al proveedor del LLM. Cada adjunto SHALL incorporarse al texto de la transcripción entre un separador de apertura `--- attachment: <nombre> ---` con el nombre de archivo saneado (sin rutas, saltos de línea ni caracteres de control) y un delimitador de cierre `--- end attachment ---`. El tipo SHALL determinarse por la extensión y comprobarse con el contenido del archivo. El texto de cada adjunto SHALL recortarse a `MAX_ATTACHMENT_CHARS` caracteres (60 000 por defecto, configurable). (Referencia: `app/attachments/extractor.py`, `enrich_transcript`.)

#### Scenario: PDF con texto
- **WHEN** se adjunta un PDF con texto extraíble
- **THEN** el texto resultante incluye `--- attachment: <nombre>.pdf ---`, el texto del documento y `--- end attachment ---`.

#### Scenario: Documento Word
- **WHEN** se adjunta un `.docx` con párrafos y tablas
- **THEN** el texto de ambos aparece entre el separador de apertura y el de cierre de ese archivo.

#### Scenario: Varios adjuntos
- **WHEN** se adjuntan varios archivos
- **THEN** cada uno aparece con su propio bloque delimitado, en el orden recibido, después del texto de la transcripción.

#### Scenario: Nombre malicioso
- **WHEN** el nombre del archivo contiene saltos de línea, rutas o un falso separador
- **THEN** el separador emitido usa solo el nombre base saneado en una única línea.

#### Scenario: Texto que supera el límite
- **WHEN** el texto extraído de un adjunto supera `MAX_ATTACHMENT_CHARS`
- **THEN** se recorta a ese número de caracteres y el recorte se registra.

### Requirement: Límites y errores de adjuntos
El sistema SHALL rechazar con errores saneados y sin exponer el contenido: tipos no admitidos (415), archivos que superan el tamaño máximo, más archivos del máximo o texto total superior al máximo de la descripción (413), archivos corruptos o cifrados (422). La extracción SHALL acotar el número de páginas y el tamaño descomprimido de los `.docx` y SHALL no bloquear el bucle de eventos. Un fallo al leer una página de un PDF SHALL registrarse y conservar el texto de las páginas legibles. Un adjunto que se procesa correctamente pero no produce texto (por ejemplo, un PDF escaneado) SHALL omitirse con un registro, sin error, y la solicitud SHALL continuar si el texto restante cumple el mínimo exigido; un documento ilegible sigue siendo un error 422.

#### Scenario: Tipo no admitido
- **WHEN** se adjunta un archivo que no es PDF ni `.docx`, o cuyo contenido no corresponde a su extensión
- **THEN** la respuesta es 415 con un mensaje saneado.

#### Scenario: Archivo demasiado grande
- **WHEN** un adjunto supera el tamaño máximo
- **THEN** la respuesta es 413.

#### Scenario: Documento ilegible
- **WHEN** el PDF está corrupto o cifrado
- **THEN** la respuesta es 422.

#### Scenario: Página ilegible
- **WHEN** una página de un PDF falla al extraerse y las demás tienen texto
- **THEN** el adjunto se incorpora con el texto de las páginas legibles.

#### Scenario: PDF sin texto
- **WHEN** el PDF no contiene texto extraíble (por ejemplo, escaneado) y acompaña a una transcripción suficiente
- **THEN** el adjunto se omite con un registro y la estimación continúa con la transcripción, en lugar de responder 422.

#### Scenario: Todas las páginas ilegibles
- **WHEN** todas las páginas de un PDF fallan al extraerse
- **THEN** el documento se considera ilegible y la respuesta es 422.

#### Scenario: Adjunto sin texto y solicitud insuficiente
- **WHEN** el único contenido es un adjunto sin texto y no se alcanza el mínimo de caracteres
- **THEN** la respuesta es 422 por texto demasiado corto.
