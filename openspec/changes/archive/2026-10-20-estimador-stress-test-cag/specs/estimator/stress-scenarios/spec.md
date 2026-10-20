# Spec Delta

## Purpose

Definir escenarios multi-turno y adjuntos sintéticos reproducibles para medir la degradación del CAG.

## ADDED Requirements

### Requirement: Escenarios multi-turno
`evals/stress/scenarios.py` SHALL ofrecer los perfiles `growing`, `pivot` y `contradiction`, cada uno como turnos `(turn_index, transcript, fact_to_remember)` de 20 turnos con checkpoints N ∈ {1, 3, 6, 10, 20}. `growing` SHALL añadir requisitos coherentes con un nombre de proyecto original en el turno 1; `pivot` SHALL cambiar el stack en el turno 5; `contradiction` SHALL fijar un presupuesto de 30.000 EUR en el turno 3 y de 80.000 EUR en el turno 8. Todo transcript SHALL cumplir la longitud mínima de la API y ser determinista.

#### Scenario: Perfil y checkpoint válidos
- **WHEN** se solicita el perfil `pivot` con N = 10
- **THEN** se obtienen los 10 primeros turnos, con el cambio de stack en el turno 5.

#### Scenario: N no admitido
- **WHEN** se solicita N = 7
- **THEN** se rechaza con un error de uso.

### Requirement: Fact-tracker
El sistema SHALL registrar los hechos introducidos por cada turno y SHALL permitir evaluarlos contra un snapshot posterior, distinguiendo los hechos vigentes de los sustituidos (cambio de stack, presupuesto reemplazado).

#### Scenario: Hecho sustituido
- **WHEN** el turno 8 reemplaza el presupuesto fijado en el turno 3
- **THEN** el tracker lista ambos hechos y marca el primero como sustituido desde el turno 8.

### Requirement: Adjuntos PDF sintéticos
`evals/stress/fixtures/build_pdfs.py` SHALL generar PDFs deterministas de aproximadamente 5, 20, 50 y 100 KB (0 = sin adjunto) con hechos identificables, y SHALL registrar para cada uno el tamaño real y los caracteres extraídos por el extractor de la aplicación. Los PDFs SHALL regenerarse en cada ejecución y SHALL NOT versionarse.

#### Scenario: Determinismo
- **WHEN** se generan dos veces los PDFs
- **THEN** el contenido de cada archivo es idéntico.

#### Scenario: Tamaño cero
- **WHEN** se pide el tamaño 0
- **THEN** no se genera ningún archivo y el turno se envía sin adjunto.
