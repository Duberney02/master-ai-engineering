# Spec Delta

## MODIFIED Requirements

### Requirement: Formulario del Chunking Lab
El formulario React del Chunking Lab para operadores autorizados SHALL obtener sus opciones de Go y SHALL mostrar las ocho estrategias con su etiqueta, descripción y nivel de coste. Solo structural, fixed_size y recursive SHALL venir marcadas; las de pago SHALL llevar aviso de coste y de la clave de proveedor que requieren, y SHALL mostrar un aviso al marcarlas. El formulario SHALL ofrecer las consultas predefinidas, un campo de consultas propias (una por línea) y `top_k` entre 1 y 10 con valor inicial de 3 (DA-28), y SHALL mostrar un indicador de carga al enviar.

#### Scenario: Selección por defecto
- **WHEN** se abre el formulario
- **THEN** solo las estrategias gratuitas por defecto están marcadas y las de pago no y `top_k` muestra 3 con límites 1–10.

#### Scenario: Aviso de clave
- **WHEN** se muestra la estrategia contextual
- **THEN** indica que requiere `ANTHROPIC_API_KEY`.

### Requirement: Ejecución de la comparación
La operación explícita de comparación en Go SHALL ignorar estrategias desconocidas y repetidas, normalizar consultas predefinidas y propias eliminando espacios exteriores, vacías y duplicadas, usar `top_k=3` si se omite (DA-28, exclusiva del Lab), acotar el entero a 1–10, rechazar sin llamar al servicio una selección vacía y llamar a `POST /embeddings/compare` con el corpus, las estrategias, las consultas y `top_k`. Con guardado exitoso SHALL devolver 201 y el identificador original como cadena decimal para que React navegue al resultado. Si solo falla el guardado SHALL devolver 200 con resultado, ID nulo y un aviso. La llamada SHALL usar un tiempo de espera de lectura ampliado (por defecto 600 s) sin cambiar el tiempo de espera global de las demás llamadas.

#### Scenario: Éxito
- **WHEN** el servicio responde 200
- **THEN** se guarda una ejecución y React navega a su resultado.

#### Scenario: Valor omitido y límites del Lab
- **WHEN** se envían comparaciones válidas omitiendo `top_k` o usando enteros dentro y fuera de 1–10
- **THEN** Go envía a Python 3 si se omitió, conserva valores válidos y acota los enteros fuera del intervalo sin cambiar los defaults ajenos al Lab

#### Scenario: Selección vacía
- **WHEN** no se marca ninguna estrategia
- **THEN** se responde 422 con un aviso y no se llama al servicio.

#### Scenario: Tiempo de espera propio
- **WHEN** se ejecuta una comparación
- **THEN** se respeta el plazo del laboratorio sin ampliar el plazo de las operaciones habituales.

#### Scenario: top_k que no es entero
- **WHEN** `top_k` llega como decimal (`3.5`, `1.0`), con exponente (`1e1`), cadena, booleano o `null`
- **THEN** Go responde 422 sin llamar al servicio ni guardar, y un entero JSON de cualquier magnitud (incluso fuera del rango de 64 bits) se acota a 1–10 sin error

#### Scenario: Consultas sin límites arbitrarios
- **WHEN** se envían muchas consultas o una consulta muy larga dentro del límite general de transporte del cuerpo JSON
- **THEN** Go las conserva íntegras y en orden, sin imponer un máximo propio de cantidad ni de longitud individual

#### Scenario: Cancelación
- **WHEN** el navegador cancela la comparación mientras IA calcula
- **THEN** Go cierra la solicitud a IA, no guarda ninguna fila, no responde ni reintenta, y una ejecución ya guardada es una única fila completa

### Requirement: Mapeo de errores del Lab
Los errores del servicio SHALL traducirse a avisos accionables: 400 a 422 con un aviso saneado, 503 por clave ausente a 503 con la variable nombrada, tiempo de espera agotado a 504 sugiriendo menos estrategias, servicio inalcanzable a 503 sin exponer la URL y errores del servidor a 502 sin exponer el cuerpo. En todos los casos SHALL mostrarse de nuevo el formulario.

#### Scenario: Clave ausente
- **WHEN** el servicio responde 503 indicando `ANTHROPIC_API_KEY`
- **THEN** el aviso menciona esa variable.

#### Scenario: Tiempo de espera
- **WHEN** la llamada excede el tiempo de espera
- **THEN** se responde 504 y el aviso sugiere probar con menos estrategias.

### Requirement: Resultados
La pantalla React de detalle SHALL obtener el resultado autorizado a través de Go y mostrar una tabla de estadísticas por estrategia (chunks, mínimo, p50, p95, máximo, huérfanos, obesos, llamadas extra y segundos), barras de coste proporcionales al mayor coste (o un mensaje si todas son gratuitas) y, si hubo consultas, un playground con el top-k de cada estrategia, su similitud y, en la jerárquica, la indicación de padre o hijo con su padre.

#### Scenario: Estrategia jerárquica
- **WHEN** el top-k incluye un chunk padre y un hijo
- **THEN** el padre lleva la marca «padre» y el hijo indica de qué padre es.

#### Scenario: Solo estadísticas
- **WHEN** la ejecución no tuvo consultas
- **THEN** se indica que no hubo consultas y no se muestra el playground.

### Requirement: Historial persistido
Cada ejecución SHALL guardarse en PostgreSQL con las estrategias, las consultas, `top_k`, el corpus, la duración y la respuesta completa. La consulta explícita de historial en Go SHALL listar las últimas 20, la más reciente primero, sin llamar al servicio. Si la base de datos no está disponible al guardar, el resultado calculado SHALL mostrarse igualmente con un aviso; si no lo está al listar, SHALL mostrarse el historial vacío con un aviso.

#### Scenario: Orden
- **WHEN** hay dos ejecuciones guardadas
- **THEN** la más reciente aparece primero.

#### Scenario: Base de datos caída al guardar
- **WHEN** el guardado falla tras calcular la comparación
- **THEN** se muestra el resultado con un aviso y no se pierde.

## ADDED Requirements

### Requirement: Detalle de comparaciones existentes
Go SHALL servir el historial y los detalles desde su repositorio, conservando identificadores y datos de ejecuciones anteriores. Conforme a DA-27, Go SHALL usar cadenas decimales para los IDs de comparación en el alta, el listado y el detalle, y el mismo segmento decimal en `Location` y la ruta de detalle. React SHALL conservar el ID como texto. PostgreSQL SHALL mantener el tipo, precisión y valor de los IDs originales. El resultado calculado que no pudo guardarse SHALL conservar ID nulo. El detalle SHALL devolver 404 si el ID es inválido o falta el registro y 500 saneado ante fallo de lectura.

#### Scenario: Datos previos y reinicio
- **WHEN** se consulta tras el reinicio un registro previo con ID 9007199254740993 (superior a 2⁵³ − 1) y se crea otro registro de prueba con ID superior al mismo umbral
- **THEN** el alta, `Location`, el listado, la navegación React y el detalle conservan los dígitos exactos, y el registro previo conserva su tipo y valor en PostgreSQL y devuelve corpus, fecha, duración, estrategias, consultas, top-k y resultados sin volver a calcular la comparación
