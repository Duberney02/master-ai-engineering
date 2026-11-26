# estimator/web-client Specification

## Purpose
Definir la frontera del cliente web: React, servido por Nginx, es el único cliente activo y habla solo con Go; el cliente Rails, el HTML de Go y Streamlit están retirados.

## Requirements

### Requirement: Retirada del cliente Streamlit
El producto SHALL retirar las referencias activas al cliente Streamlit y los recursos exclusivos de su ejecución, incluidas dependencias, lockfiles, servicios, puerto 8501, variables, código, scripts, pruebas y documentación vigente. SHALL conservar Git, el archivo histórico OpenSpec y los contratos REST y SSE aprobados.

#### Scenario: Auditoría de retirada
- **WHEN** se inspeccionan fuentes activas, dependencias resueltas, imágenes, configuración, documentación y especificaciones vigentes resultantes
- **THEN** no hay cliente, dependencia exclusiva, publicación ni instrucciones operativas activas de Streamlit y las pruebas de contrato REST y SSE siguen pasando

### Requirement: Frontera del cliente web
El producto SHALL ofrecer una sola interfaz de navegador, React. Sus contratos de estimación, historial, conversación y vista previa SHALL consumirse a través de Go. Las funciones administrativas existentes SHALL migrarse con paridad comprobada en pruebas y SHALL permanecer bloqueadas por Go en integración hasta disponer de autorización funcional. La retirada de clientes previos SHALL preservar datos y los contratos REST y SSE aprobados.

#### Scenario: Interfaz consolidada
- **WHEN** se navega por las capacidades aprobadas desde React
- **THEN** se accede mediante el mismo origen y ninguna pantalla requiere HTML de Go o de estimador-cag
