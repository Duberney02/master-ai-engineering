# Spec Delta

## Purpose

Medir de forma determinista la calidad estructural y de contenido de una estimación respecto a las expectativas de un caso.

## ADDED Requirements

### Requirement: schema_adherence
La métrica `schema_adherence` SHALL comprobar la coherencia estructural de la estimación (la suma de costes de las fases coincide con el total, la duración total es coherente con las duraciones de las fases, los nombres de fase son únicos, la forma del resultado fuera de alcance es la esperada) y que el número de fases está en el rango del caso, y SHALL devolver una puntuación entre 0 y 1 con el detalle de cada comprobación.

#### Scenario: Estimación coherente
- **WHEN** la suma de costes coincide con el total, la duración es coherente y el número de fases está en el rango
- **THEN** la puntuación es 1 y la métrica aprueba.

#### Scenario: Incoherencias
- **WHEN** la suma de costes no coincide con el total o hay fases fuera del rango
- **THEN** la métrica no aprueba, la puntuación es menor que 1 y el detalle identifica la comprobación fallida.

### Requirement: cost_bounds
La métrica `cost_bounds` SHALL comprobar que el coste total y la duración total están dentro de los rangos del caso y que el carácter fuera de alcance del resultado coincide con el esperado. Un resultado fuera de alcance esperado SHALL tener coste cero y no se evalúa contra rangos.

#### Scenario: Dentro de rangos
- **WHEN** coste y duración están dentro de los rangos
- **THEN** la métrica aprueba con puntuación 1.

#### Scenario: Coste fuera de rango
- **WHEN** el coste es inferior al mínimo o superior al máximo
- **THEN** la métrica no aprueba y el detalle indica el valor y el rango.

#### Scenario: Fuera de alcance
- **WHEN** el caso espera un resultado fuera de alcance y el estimador lo devuelve con coste cero
- **THEN** la métrica aprueba; si el estimador devuelve cifras, no aprueba.

#### Scenario: Fuera de alcance inesperado
- **WHEN** el caso espera una estimación y el resultado es fuera de alcance
- **THEN** la métrica no aprueba.

### Requirement: content_recall
La métrica `content_recall` SHALL calcular la fracción de requisitos y tecnologías esperados (cualquiera de sus alternativas) presentes en el resumen y las fases de la estimación, sin distinguir mayúsculas ni acentos, SHALL aprobar con una fracción igual o superior al umbral del caso (0,6 por defecto) y SHALL listar los elementos ausentes. Sin expectativas SHALL aprobar con puntuación 1.

#### Scenario: Recall completo
- **WHEN** todos los elementos esperados aparecen
- **THEN** la puntuación es 1 y aprueba.

#### Scenario: Recall parcial
- **WHEN** aparecen 2 de 4 elementos y el umbral es 0,6
- **THEN** la puntuación es 0,5, no aprueba y el detalle lista los dos ausentes.

#### Scenario: Alternativas y acentos
- **WHEN** el esperado es `protección de datos|rgpd` y el texto dice «RGPD»
- **THEN** el elemento cuenta como presente.

### Requirement: Evaluaciones existentes intactas
Las evaluaciones de `app/services/evaluation.py` SHALL conservar su comportamiento y sus pruebas.

#### Scenario: Evaluación previa
- **WHEN** se ejecutan las pruebas de la evaluación existente
- **THEN** pasan sin modificaciones.
