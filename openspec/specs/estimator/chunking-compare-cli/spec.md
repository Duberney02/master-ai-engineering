# estimator/chunking-compare-cli Specification

## Purpose
Comparar estrategias de chunking desde la línea de comandos y generar un informe Markdown.

## Requirements

### Requirement: CLI de comparación de chunkers
`scripts/compare_chunkers.py` SHALL aceptar `--strategies` (`free` por defecto, `all` o lista), `--queries` (`all`, índices base 1 o vacío) y `--query` repetible, `--show-stats`, `--show-top-k N`, `--show-cost`, `--output RUTA`, `--limit-budgets N`, `--resolve-parents` y `--dimensions` (lista de dimensiones de embedding). SHALL usar `budgets_sample.json` y `budgets_stress_cases.json` por defecto y funcionar dentro del contenedor. Sin claves SHALL poder mostrar las estadísticas de las estrategias gratuitas.

#### Scenario: Estadísticas sin claves
- **WHEN** se ejecuta con `--show-stats` y sin argumentos más
- **THEN** imprime la tabla de las cinco estrategias gratuitas y termina con código 0.

#### Scenario: Informe Markdown
- **WHEN** se pasa `--output informe.md`
- **THEN** el archivo contiene el mismo informe que se imprime.

#### Scenario: Dimensiones
- **WHEN** se pasa `--dimensions 8,16` con consultas y `--show-top-k`
- **THEN** el top-k se calcula una vez por dimensión reutilizando el chunking.

#### Scenario: Padres
- **WHEN** se pasa `--resolve-parents` con la estrategia jerárquica
- **THEN** cada hijo recuperado indica su padre.

#### Scenario: Errores de uso
- **WHEN** la estrategia es desconocida o falta la clave de una de pago
- **THEN** termina con código 2 y un mensaje que no contiene valores secretos.
