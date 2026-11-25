# Proposal

## Why

React, la interfaz HTML de Go y el chat mantienen flujos web paralelos. La fase 6.6 concentra la experiencia web en React y sitúa en Go la frontera HTTP de aplicación para mantener el servicio de IA y sus datos fuera del alcance directo del navegador.

## What Changes

- Servir React con Nginx y dirigir sus solicitudes de mismo origen a Go, también mediante el proxy de Vite durante el desarrollo.
- Preservar los contratos REST y SSE enumerados en el diseño mediante rutas explícitas, con validación de transporte, cancelación de React a Python sin reintentos automáticos y errores saneados. Una escritura ya confirmada puede permanecer en PostgreSQL.
- **BREAKING** Retirar la interfaz HTML de Go tras verificar su paridad funcional, retirar Streamlit y la demo HTML servida por Python, y dejar de publicar el puerto de FastAPI en integración.
- Segmentar los servicios y mantener en Go el historial del Chunking Lab y en Python la IA, el renderizado de prompts y su persistencia. Publicar únicamente React/Nginx mediante loopback y túnel SSH durante la integración.
- DA-25 incorpora la paridad completa en React, incluidos Ajustes de IA, modelo primario y Chunking Lab. El corte requiere evidencia funcional en Docker y conservación de datos e identificadores.
- DA-26 reserva la autenticación propia de Go para `homelab-authentication-authorization`. Este cambio define la frontera de autorización en Go y mantiene cerradas las operaciones administrativas en integración. Hasta completar `homelab-authentication-authorization`, la aplicación es un entorno privado de desarrollo accesible exclusivamente por el operador autorizado mediante túnel SSH, sin exposición pública ni habilitación multiusuario. Go deniega por defecto las operaciones administrativas.
- DA-27 aprobada. Los IDs de comparación del Chunking Lab se serializan como cadenas decimales en HTTP y conservan tipo, precisión y valor en PostgreSQL.
- DA-28 aprobada. Solo el Chunking Lab usa `top_k=3` por defecto y mantiene el intervalo 1–10.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `estimator/deployment-stack` — topología, publicaciones, salud y credenciales.
- `estimator/web-backend-go` — API pública explícita, seguridad, plazos y retirada del HTML.
- `estimator/web-client-contexts` — navegación en React y saneamiento de errores en la frontera Go.
- `estimator/web-react-client` — cliente único que consume Go.
- `estimator/structured-estimation` — retirada del requisito exclusivo del cliente Streamlit.
- `estimator/prompt-preview` — vista previa servida a través de Go y renderizada en Python.
- `estimator/http-streaming` — intermediación SSE de las dos rutas públicas.
- `estimator/web-client` — sustituir los requisitos redundantes del cliente legado por la frontera del cliente único.
- `estimator/web-ai-settings` — conservar ajustes y el indicador en la consolidación.
- `estimator/web-chunking-lab` — conservar formulario, ejecución, resultados e historial sin HTML independiente.
- `estimator/layered-architecture` — retirar el montaje de la demo de navegador preservando los contratos de la API interna.

## Impact

Afecta al cliente React, a `internal/web` e `internal/estimatorai` en Go, al empaquetado y referencias al cliente retirado en Python, a Compose, CI y la documentación de integración. Las pruebas de aplicación se ejecutarán en Docker con datos simulados y claves ficticias. Las pruebas usan proyectos Compose propios y redes, bases de datos y volúmenes efímeros independientes del despliegue del proyecto y de la infraestructura preexistente. Queda prohibido detener, modificar o eliminar PostgreSQL, Ollama, Open WebUI o cualquiera de sus recursos preexistentes, ejecutar limpiezas globales o eliminar volúmenes de infraestructura. La preparación y la limpieza se limitan a los recursos de prueba identificados como propios. Está prohibido versionar credenciales reales. Solo estimador-cag recibe claves de proveedores de IA, mediante entorno local excluido o secretos de despliegue.

Quedan fuera la implementación de autenticación y autorización reales y los proveedores externos de identidad, Ollama, la separación de proveedores de generación y embeddings, la migración a PostgreSQL compartido, los cambios de dimensiones e índices, las estrategias RAG y el despliegue definitivo.
