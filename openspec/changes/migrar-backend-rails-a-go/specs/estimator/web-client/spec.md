# Spec Delta

## MODIFIED Requirements

### Requirement: Manejo de errores del cliente HTTP
El cliente HTTP SHALL usar la URL `ESTIMATOR_API_URL`, tiempos de espera acotados y SHALL traducir los fallos a mensajes saneados en español: fallo de conexión o de tiempo, 400 con el `message` del guardrail, 422, 404 y 5xx. SHALL NOT mostrar cuerpos de respuesta crudos, trazas ni la URL interna. Un cuerpo no JSON o fuera de contrato SHALL tratarse como respuesta inválida.

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
