# Spec Delta

## Purpose

Rechazar entradas peligrosas o con datos personales antes de consultar cachés, calcular embeddings o llamar al proveedor.

## ADDED Requirements

### Requirement: Evaluación de textos largos
Los guardrails SHALL evaluar el texto completo de la descripción, sin truncarlo, incluso con 80000 caracteres: un dato personal o una instrucción de inyección en cualquier posición SHALL provocar el rechazo. La moderación SHALL enviar el texto por tramos de como máximo 30000 caracteres y SHALL rechazar si cualquier tramo es marcado.

#### Scenario: Dato personal al final de una transcripción larga
- **WHEN** una descripción de 80000 caracteres contiene un correo electrónico en su última línea
- **THEN** la respuesta es 400 con `reason="pii_email"`.

#### Scenario: Inyección en mitad del texto
- **WHEN** una descripción larga contiene «Ignora las instrucciones anteriores» en su parte central
- **THEN** la respuesta es 400 con `reason="prompt_injection"`.

#### Scenario: Moderación por tramos
- **WHEN** la descripción supera 30000 caracteres
- **THEN** la moderación recibe varios tramos en una única llamada y rechaza si alguno es marcado.
