# estimator/web-chunking-lab Specification

## Purpose
Permitir comparar estrategias de chunking desde la web, con aviso de coste, resultados visuales e historial persistido.

## Requirements

### Requirement: Formulario del Chunking Lab
`GET /rag/chunking_comparisons/new` SHALL mostrar las ocho estrategias con su etiqueta, descripción y nivel de coste. Solo las gratuitas SHALL venir marcadas; las de pago SHALL llevar aviso de coste y de la clave de proveedor que requieren, y SHALL mostrar un aviso al marcarlas. El formulario SHALL ofrecer las consultas predefinidas, un campo de consultas propias (una por línea) y `top_k` entre 1 y 10, y SHALL mostrar un indicador de carga al enviar.

#### Scenario: Selección por defecto
- **WHEN** se abre el formulario
- **THEN** solo las estrategias gratuitas por defecto están marcadas y las de pago no.

#### Scenario: Aviso de clave
- **WHEN** se muestra la estrategia contextual
- **THEN** indica que requiere `ANTHROPIC_API_KEY`.

### Requirement: Ejecución de la comparación
`POST /rag/chunking_comparisons` SHALL ignorar estrategias desconocidas, acotar `top_k` a 1–10, rechazar sin llamar al servicio una selección vacía y llamar a `POST /embeddings/compare` con el corpus, las estrategias, las consultas y `top_k`. Con éxito SHALL guardar la ejecución y redirigir a su resultado. La llamada SHALL usar un tiempo de espera de lectura ampliado (por defecto 600 s) sin cambiar el tiempo de espera global de las demás llamadas.

#### Scenario: Éxito
- **WHEN** el servicio responde 200
- **THEN** se guarda una ejecución y se redirige a su resultado.

#### Scenario: Selección vacía
- **WHEN** no se marca ninguna estrategia
- **THEN** se responde 422 con un aviso y no se llama al servicio.

#### Scenario: Tiempo de espera propio
- **WHEN** se ejecuta una comparación
- **THEN** el cliente de embeddings se crea con el `read_timeout` del laboratorio.

### Requirement: Mapeo de errores del Lab
Los errores del servicio SHALL traducirse a avisos accionables: 400 a 422 con el detalle, 503 por clave ausente a 503 con la variable nombrada, tiempo de espera agotado a 504 sugiriendo menos estrategias, servicio inalcanzable a 503 sin exponer la URL y errores del servidor a 502 sin exponer el cuerpo. En todos los casos SHALL mostrarse de nuevo el formulario.

#### Scenario: Clave ausente
- **WHEN** el servicio responde 503 indicando `ANTHROPIC_API_KEY`
- **THEN** el aviso menciona esa variable.

#### Scenario: Tiempo de espera
- **WHEN** la llamada excede el tiempo de espera
- **THEN** se responde 504 y el aviso sugiere probar con menos estrategias.

### Requirement: Resultados
`GET /rag/chunking_comparisons/:id` SHALL mostrar una tabla de estadísticas por estrategia (chunks, mínimo, p50, p95, máximo, huérfanos, obesos, llamadas extra y segundos), barras de coste proporcionales al mayor coste (o un mensaje si todas son gratuitas) y, si hubo consultas, un playground con el top-k de cada estrategia, su similitud y, en la jerárquica, la indicación de padre o hijo con su padre.

#### Scenario: Estrategia jerárquica
- **WHEN** el top-k incluye un chunk padre y un hijo
- **THEN** el padre lleva la marca «padre» y el hijo indica de qué padre es.

#### Scenario: Solo estadísticas
- **WHEN** la ejecución no tuvo consultas
- **THEN** se indica que no hubo consultas y no se muestra el playground.

### Requirement: Historial persistido
Cada ejecución SHALL guardarse en PostgreSQL con las estrategias, las consultas, `top_k`, el corpus, la duración y la respuesta completa. `GET /rag/chunking_comparisons` SHALL listar las últimas 20, la más reciente primero, sin llamar al servicio. Si la base de datos no está disponible al guardar, el resultado calculado SHALL mostrarse igualmente con un aviso; si no lo está al listar, SHALL mostrarse el historial vacío con un aviso.

#### Scenario: Orden
- **WHEN** hay dos ejecuciones guardadas
- **THEN** la más reciente aparece primero.

#### Scenario: Base de datos caída al guardar
- **WHEN** el guardado falla tras calcular la comparación
- **THEN** se muestra el resultado con un aviso y no se pierde.
