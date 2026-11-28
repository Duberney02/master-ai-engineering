# http-streaming Specification

## Purpose
Permitir que Go, único cliente de la API de IA, reciba estimaciones progresivas mediante un contrato HTTP común y las intermedie hacia React sin sintetizar eventos ni reintentar.

## Requirements

### Requirement: Contrato SSE
El sistema SHALL exponer POST /api/v1/transcription/estimate/stream con la validación de entrada del flujo de transcripción, eventos token con texto JSON, metadata con consumo/modelo/caché/costes y done únicamente tras éxito. Los fallos SHALL producir error saneado sin done. SHALL soportar las opciones de generación, incluida extracción en dos fases antes de emitir texto, y evaluar el resultado completo cuando se solicita.

#### Scenario: Generación correcta
- **WHEN** se transmite una estimación válida
- **THEN** el cliente recibe token, metadata y done en ese orden, conservando saltos de línea.

#### Scenario: Fallo después del primer token
- **WHEN** falla el proveedor tras emitir texto
- **THEN** se emite error sin reintentar ni cambiar de proveedor, sin caché de contenido parcial.

#### Scenario: Cancelación
- **WHEN** el cliente cancela la conexión
- **THEN** se cierra el generador y los recursos del proveedor sin almacenar una respuesta parcial.

### Requirement: Intermediación pública de SSE
Go SHALL intermediar las dos rutas POST de streaming explícitamente, con las secuencias `result → metadata → done` y `token* → metadata → done` respectivamente. SHALL conservar el orden, saltos de línea y datos compatibles, transferir y hacer flush de cada evento sin esperar al fin del flujo y acotar la memoria por evento. SHALL distinguir errores HTTP anteriores a la apertura de eventos `error` terminales posteriores. Al recibir EOF prematuro, secuencia incompleta o agotar inactividad, SHALL señalar fallo si la conexión es escribible y SHALL NOT sintetizar `done`. Ante cancelación SHALL cerrar el cuerpo upstream y cancelar su contexto conforme al requisito «Frontera con la API de IA». El generador Python SHALL liberar los recursos del proveedor sin almacenar una respuesta parcial ni reintentar la operación.

#### Scenario: Entrega incremental
- **WHEN** el upstream simulado fragmenta un evento con varias líneas data y retiene el siguiente
- **THEN** un cliente tras Nginx recibe el evento completo con sus saltos de línea antes de que se libere el siguiente

#### Scenario: Error previo
- **WHEN** IA devuelve 400 o 422 JSON durante validación inicial
- **THEN** la frontera devuelve ese código con un JSON saneado y sin confirmar streaming

#### Scenario: Fallo posterior
- **WHEN** IA devuelve error saneado, corta la conexión sin terminal o deja vencer la inactividad
- **THEN** el flujo termina con error cuando se puede escribir, sin done y sin reintento

#### Scenario: Cancelación estructurada durante la generación
- **WHEN** el cliente cancela mientras el proveedor simulado genera y el stream aún no ha emitido `result`
- **THEN** Go cancela y cierra el upstream, Python libera el recurso del proveedor y no queda persistencia ni caché parcial

#### Scenario: Cancelación estructurada después del resultado
- **WHEN** el cliente cancela tras recibir `result`
- **THEN** Go cancela y cierra el upstream, y toda escritura confirmada se conserva intacta

#### Scenario: Cancelación de transcripción tras el primer token
- **WHEN** el cliente cancela después del primer `token` mientras la generación sigue activa
- **THEN** Go cancela y cierra el upstream y Python interrumpe el generador y libera el recurso del proveedor simulado, sin caché parcial ni segundo POST

#### Scenario: Cancelación alrededor de la escritura
- **WHEN** se cancela antes, durante o después de la escritura
- **THEN** se preserva la atomicidad y las escrituras confirmadas, con independencia de si se entregó `result`
