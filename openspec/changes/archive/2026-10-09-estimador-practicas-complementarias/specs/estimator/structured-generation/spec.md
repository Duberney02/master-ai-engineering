# Spec Delta

## Purpose

Disponer de una primitiva de generación estructurada basada en modelos Pydantic y un criterio explícito para adoptar librerías externas.

## ADDED Requirements

### Requirement: Primitiva de generación estructurada
El sistema SHALL ofrecer una función que genere con el generador del proyecto una respuesta validada con un modelo Pydantic, reutilizando la caché, los reintentos, el fallback y las métricas de costes existentes, y que ante una respuesta inválida SHALL reintentar con un mensaje de corrección hasta un número configurable de intentos y, si se agotan, SHALL fallar con un error explícito. Devuelve el objeto validado y las completions consumidas.

#### Scenario: Respuesta válida
- **WHEN** el modelo devuelve un JSON que cumple el esquema
- **THEN** se devuelve el objeto validado y una completion.

#### Scenario: Corrección
- **WHEN** la primera respuesta incumple el esquema y la segunda lo cumple
- **THEN** se devuelve la segunda y la segunda llamada incluye la respuesta inválida y el motivo.

#### Scenario: Intentos agotados
- **WHEN** ninguna respuesta cumple el esquema
- **THEN** se lanza `StructuredOutputError` tras los intentos permitidos.

#### Scenario: Opciones del generador
- **WHEN** se pasan opciones como `model` o `max_tokens`
- **THEN** se transmiten tal cual al generador.

### Requirement: Evaluación documentada de librerías
El repositorio SHALL documentar la evaluación de Instructor (generación estructurada) y LiteLLM (unificación de proveedores) frente a la implementación existente, con el criterio aplicado y la decisión. Ninguna de ellas SHALL ser un requisito obligatorio del proyecto.

#### Scenario: Decisión registrada
- **WHEN** se consulta `docs/evaluacion-instructor-litellm.md`
- **THEN** recoge, para cada librería, el criterio, los hallazgos y la decisión, y las dependencias de producción no incluyen ninguna de las dos.
