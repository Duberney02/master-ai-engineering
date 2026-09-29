# Spec Delta

## Purpose

Permitir que Streamlit y otros clientes consuman estimaciones progresivas a través de un contrato HTTP común.

## ADDED Requirements

### Requirement: Contrato SSE
El sistema SHALL exponer POST /api/v1/estimate/stream con la validación de entrada existente, eventos token con texto JSON, metadata con consumo/modelo/caché/costes y done únicamente tras éxito. Los fallos SHALL producir error saneado sin done. SHALL soportar las opciones de generación, incluida extracción en dos fases antes de emitir texto, y evaluar el resultado completo cuando se solicita.

#### Scenario: Generación correcta
- **WHEN** se transmite una estimación válida
- **THEN** el cliente recibe token, metadata y done en ese orden, conservando saltos de línea.

#### Scenario: Fallo después del primer token
- **WHEN** falla el proveedor tras emitir texto
- **THEN** se emite error sin reintentar ni cambiar de proveedor, sin caché de contenido parcial.

#### Scenario: Cancelación
- **WHEN** el cliente cancela la conexión
- **THEN** se cierra el generador y los recursos del proveedor sin almacenar una respuesta parcial.

### Requirement: Clientes HTTP independientes
Streamlit SHALL consumir la API por URL configurable, mostrar métricas y contexto CAG, permitir borrar historial y presentar errores sin tratarlos como estimaciones completas. SHALL existir una demo HTML servida por la API. El contenedor de chat SHALL funcionar sin claves de proveedores.

#### Scenario: Streamlit remoto
- **WHEN** Streamlit recibe tokens y métricas desde otra instancia de API
- **THEN** renderiza el Markdown y actualiza el panel sin invocar SDK de proveedores localmente.

#### Scenario: Mensaje multilínea
- **WHEN** el transporte fragmenta un evento o usa múltiples líneas data
- **THEN** el cliente reconstruye el evento antes de interpretarlo.
