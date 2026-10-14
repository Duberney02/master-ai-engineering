# Spec Delta

## Purpose

Ejecutar el dataset contra la API y producir un resultado y un reporte utilizables en pipelines.

## ADDED Requirements

### Requirement: Modos y destinos de ejecución
El runner SHALL ejecutar el dataset en modo `actor` (`POST /api/v1/sessions/{id}/estimate`) o `acb` (`POST /api/v1/sessions/{id}/estimate-acb`), en proceso mediante `TestClient` o contra una URL HTTP indicada con `--base-url`. SHALL usar una sesión nueva e independiente por caso.

#### Scenario: Modo actor
- **WHEN** se ejecuta en modo `actor`
- **THEN** cada caso crea una sesión y llama al endpoint conversacional una sola vez.

#### Scenario: Modo acb
- **WHEN** se ejecuta en modo `acb`
- **THEN** cada caso llama a `estimate-acb` y el reporte incluye la decisión final del Boss.

#### Scenario: Sesiones independientes
- **WHEN** se ejecutan varios casos
- **THEN** cada uno usa un `session_id` distinto y ninguno ve el historial de otro.

#### Scenario: URL HTTP
- **WHEN** se indica `--base-url`
- **THEN** las llamadas se envían a esa URL y no se arranca la aplicación en proceso.

### Requirement: Selección de casos y exportación
El runner SHALL permitir limitar los casos con `--limit`, seleccionarlos por identificador con `--case` o por categoría con `--category`, y exportar el reporte con `--output`.

#### Scenario: Límite
- **WHEN** se ejecuta con `--limit 3`
- **THEN** se evalúan los tres primeros casos del dataset.

#### Scenario: Sin casos seleccionados
- **WHEN** los filtros no seleccionan ningún caso
- **THEN** el proceso termina con código 2 sin llamar a la API.

### Requirement: Código de salida
El runner SHALL terminar con código 0 si todos los casos evaluados superan la evaluación y con un código distinto de cero si alguno falla o produce un error. Un error en un caso SHALL registrarse y no interrumpir los demás.

#### Scenario: Todos aprueban
- **WHEN** todos los casos aprueban
- **THEN** el código de salida es 0.

#### Scenario: Algún fallo
- **WHEN** un caso incumple una métrica o la API devuelve un error
- **THEN** el código de salida es 1 y los casos restantes se evalúan igualmente.

### Requirement: Reporte JSON
El reporte SHALL incluir, por caso, el identificador, la latencia, las métricas, si aprobó, el resumen de la estimación, la versión del prompt y la decisión final ACB (nula en modo actor), además de los errores y los totales de casos evaluados y aprobados.

#### Scenario: Contenido del reporte
- **WHEN** se exporta el reporte de una ejecución con un caso aprobado y uno fallido
- **THEN** los totales indican 2 evaluados y 1 aprobado y cada caso incluye su latencia y sus tres métricas.

#### Scenario: Error en un caso
- **WHEN** un caso falla por un error de la API
- **THEN** su entrada incluye el estado HTTP y el mensaje de error, sin métricas, y cuenta como fallido.

#### Scenario: Rechazo esperado
- **WHEN** un caso espera el rechazo por guardrails y la API responde 400 con esa razón
- **THEN** el caso aprueba.
