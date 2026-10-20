# estimator/budget-cleaning Specification

## Purpose
Limpiar y validar registros de presupuestos como utilidades independientes, repartiendo cada fila en válida, en cuarentena o descartada.

## Requirements

### Requirement: Limpieza de registros de presupuesto
`clean_budget_records(records)` SHALL devolver un `DataFrame` de pandas que normalice los marcadores de nulos (`TBD`, `N/A`, cadenas vacías y los demás de la referencia) a `NA` en `client_name`, `contact`, `contact_email` y `notes`; convierta la moneda a mayúsculas; convierta `signed_at` a fecha y `total_amount` a número, dejando `NaT`/`NaN` ante valores no interpretables; calcule `content_hash`; y deduplique por `budget_id` conservando el registro con la fecha de firma más reciente. (Referencia: `app/ingestion/cleaning/budget_records.py`.)

#### Scenario: Nulos disfrazados
- **WHEN** `client_name` es `TBD`, `N/A` o una cadena vacía
- **THEN** el valor limpio es nulo.

#### Scenario: Moneda y números
- **WHEN** la moneda es `eur` y el importe llega como texto
- **THEN** la moneda es `EUR` y el importe es numérico.

#### Scenario: Duplicados
- **WHEN** dos registros comparten `budget_id` con distinta fecha de firma
- **THEN** se conserva el de la fecha más reciente.

### Requirement: Validación con política de partición
`validate_with_policy(df)` SHALL validar con el esquema Pandera `BudgetRecord` (identificador `BUDGET-YYYY-NNNN`, código de cliente `CLI-NNNN`, moneda en `EUR`/`USD`/`GBP`, importe entre 0 y 10 000 000 y fecha de firma válida; `client_name` admite nulo) con `lazy=True` y devolver `ValidationResult` con los registros válidos, en cuarentena y descartados y un informe con las cantidades y los fallos agrupados por comprobación. Un registro con fallos de ambas categorías SHALL descartarse. El módulo no valida la suma de importes de fases. (Referencia: `app/ingestion/cleaning/schemas.py`, `policy.py`.)

#### Scenario: Importe negativo
- **WHEN** un registro tiene `total_amount` negativo
- **THEN** se descarta y el informe cuenta el fallo por comprobación.

#### Scenario: Todo válido
- **WHEN** todos los registros cumplen el esquema
- **THEN** `quarantined` y `discarded` están vacíos y el informe indica cero fallos.

#### Scenario: Cliente sin nombre
- **WHEN** `client_name` es nulo tras la limpieza
- **THEN** el registro sigue siendo válido porque el esquema admite el nulo.

### Requirement: Independencia del orquestador
Las utilidades de limpieza y validación SHALL ser independientes: el orquestador de ingesta no las ejecuta automáticamente.

#### Scenario: Ingesta sin limpieza
- **WHEN** se ejecuta una ingesta
- **THEN** no se invoca `clean_budget_records` ni `validate_with_policy`.
