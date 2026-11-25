# Spec Delta

## ADDED Requirements

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

#### Scenario: Cancelación
- **WHEN** React aborta después del primer evento de cualquiera de las dos rutas SSE a través de Nginx o Vite
- **THEN** el proxy propaga el cierre a Go, Go cancela y cierra el cuerpo upstream, Python cierra el generador, el fake del proveedor observa la liberación de recursos y no hay resultado parcial persistido, caché parcial ni segundo POST

## REMOVED Requirements

### Requirement: Clientes HTTP independientes
**Reason**: Se retira el contrato ligado a la interfaz o topología anterior.
**Migration**: La cobertura aplicable se traslada a «Intermediación pública de SSE» en este delta.
