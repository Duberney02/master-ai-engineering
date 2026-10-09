# estimator/critic-contract Specification

## Purpose
Definir el contrato estructurado de la revisión independiente de una estimación y el servicio que la produce.

## Requirements

### Requirement: Contrato de defectos y feedback
El sistema SHALL definir `CriticIssue` con categoría (`math_error`, `hallucination`, `scope_mismatch`, `phase_imbalance`, `missing_assumption`, `unrealistic_estimate` o `tier_mismatch`), severidad (`critical`, `major` o `minor`), campo afectado, descripción y corrección sugerida, y `CriticFeedback` con veredicto (`accept`, `needs_iteration` o `reject`), lista de defectos, confianza de la revisión entre 0 y 1 y explicación opcional. SHALL rechazar categorías, severidades o veredictos desconocidos.

#### Scenario: Feedback válido
- **WHEN** se valida un feedback `accept` sin defectos y confianza 0.9
- **THEN** el modelo se crea correctamente.

#### Scenario: Valores fuera del contrato
- **WHEN** la categoría, la severidad o el veredicto no pertenecen a los valores definidos, o la confianza está fuera de 0 a 1
- **THEN** la validación falla.

### Requirement: Coherencia del veredicto
`CriticFeedback` con veredicto `needs_iteration` SHALL contener al menos un defecto `critical` o `major`, y con veredicto `reject` SHALL incluir una explicación no vacía.

#### Scenario: Iteración sin defectos graves
- **WHEN** el veredicto es `needs_iteration` y los defectos son todos `minor` o no hay ninguno
- **THEN** la validación falla.

#### Scenario: Iteración con defecto mayor
- **WHEN** el veredicto es `needs_iteration` y hay un defecto `major`
- **THEN** la validación es correcta.

#### Scenario: Rechazo sin explicación
- **WHEN** el veredicto es `reject` y la explicación falta o está en blanco
- **THEN** la validación falla.

### Requirement: Servicio de revisión independiente
El sistema SHALL ofrecer un servicio crítico que reciba la transcripción, los metadatos del proyecto, la audiencia y la estimación generada y devuelva un `CriticFeedback` validado, usando el modelo `CRITIC_MODEL` y una plantilla versionada. El servicio SHALL NOT recibir ni modificar la sesión. Si la respuesta del modelo no es válida SHALL reintentar con un mensaje de corrección y, si sigue siéndolo, fallar con un error explícito.

#### Scenario: Revisión estructurada
- **WHEN** se solicita la revisión de una estimación
- **THEN** el prompt enviado contiene la transcripción, los metadatos, la audiencia y la estimación, y el resultado es un `CriticFeedback`.

#### Scenario: Modelo del crítico
- **WHEN** `CRITIC_MODEL` está definido
- **THEN** la llamada del crítico usa ese modelo.

#### Scenario: Respuesta inválida corregida
- **WHEN** la primera respuesta del modelo no cumple el contrato y la segunda sí
- **THEN** se devuelve el feedback de la segunda.

#### Scenario: Respuesta inválida persistente
- **WHEN** ninguna respuesta cumple el contrato
- **THEN** el servicio lanza un error de salida estructurada.
