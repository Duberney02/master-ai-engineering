# Spec Delta

## MODIFIED Requirements

### Requirement: Manejo de errores del cliente HTTP
El cliente SHALL llamar a la API solo por rutas relativas del propio origen, con plazos totales configurables por operación coordinados con Nginx/Vite y Go (inicialmente 40 s para operaciones habituales y 630 s para largas, incluidas las estimaciones), y SHALL traducir los fallos a mensajes saneados en español, idénticos a los de la web Rails: fallo de conexión o de tiempo, 400 con el `message` del guardrail (acotado a 300 caracteres), 422, 404, 503 del historial y otros 5xx. SHALL NOT mostrar cuerpos de respuesta crudos, trazas ni URLs internas. Un cuerpo no JSON o fuera de contrato SHALL tratarse como respuesta inválida.

#### Scenario: API caída
- **WHEN** la API no acepta la conexión o excede el tiempo
- **THEN** se muestra «No se pudo conectar con la API del estimador.» sin detalles internos.

#### Scenario: Rechazo de guardrails
- **WHEN** la API responde 400 con `{reason, message}`
- **THEN** se muestra ese `message` como error del formulario.

#### Scenario: Error del servidor
- **WHEN** la API responde 5xx
- **THEN** se muestra un mensaje genérico y no el cuerpo de la respuesta.

#### Scenario: Respuesta inválida
- **WHEN** la API responde 200 con un cuerpo que no es JSON o sin `result`
- **THEN** se muestra un mensaje de respuesta inválida.

#### Scenario: Pantalla de error
- **WHEN** falla la carga de una estimación (404 o error de la API)
- **THEN** se muestra «No se pudo completar la operación» con el mensaje saneado y enlaces al historial y a nueva estimación.

#### Scenario: Presupuesto coordinado
- **WHEN** una estimación supera el plazo habitual y termina dentro del presupuesto largo
- **THEN** React recibe el resultado sin abortar antes que los intermediarios

## ADDED Requirements

### Requirement: Paridad funcional de la interfaz React
React SHALL ofrecer la funcionalidad de inicio y navegación, estimación con TXT, PDF y DOCX, avisos de guardrails y caducidad, reinicio conversacional, resultado inline sin ID o detalle con ID, historial, métricas y barra plegable con prompt, ejemplos y metadatos. SHALL ofrecer Ajustes, indicador y Chunking Lab conforme a sus contratos. React SHALL limitarse a presentación e interacción y preservar su diseño visual vigente.

#### Scenario: Resultado, conversación y contexto
- **WHEN** se reproduce el recorrido HTML de referencia con las mismas respuestas simuladas, incluidas estimaciones sin historial y no estimables
- **THEN** React permite completar las mismas acciones, muestra los resultados y métricas aplicables y mantiene usable la barra si falla la vista previa

#### Scenario: Paridad administrativa
- **WHEN** se prueban Ajustes y Lab de extremo a extremo con autorización exclusiva de pruebas
- **THEN** React conserva acciones, avisos, visualizaciones y acceso a registros históricos con sus IDs


### Requirement: Cliente web único con API de mismo origen
React SHALL ser el único cliente web y SHALL usar rutas relativas de mismo origen que Nginx o Vite dirigen a Go. SHALL conservar JSON y multipart en sus flujos existentes. El cliente SHALL conservar el borrador ante 404 de sesión, crear una sesión nueva y avisar para que el usuario decida volver a enviar. Los flujos cancelables SHALL abortar la solicitud con `AbortSignal` para propagar el cierre a Python mediante Nginx o Vite y Go, sin reintentos automáticos.

#### Scenario: Estimación y navegación
- **WHEN** el usuario estima desde React con el devserver o la imagen de integración
- **THEN** el POST multipart llega a Go y el historial y la vista previa se consultan también a través de Go

#### Scenario: Sesión caducada
- **WHEN** Go devuelve 404 en el envío de un turno
- **THEN** React conserva el borrador, crea otra sesión, informa y no vuelve a enviar la estimación por sí mismo

#### Scenario: Cancelar
- **WHEN** el usuario cancela la operación en curso
- **THEN** React aborta la petición, habilita el formulario sin mostrar resultados incompletos ni reenviar, y permite consultar después una escritura ya confirmada en PostgreSQL
