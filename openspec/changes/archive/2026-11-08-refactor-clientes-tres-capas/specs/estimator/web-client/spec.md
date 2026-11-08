## REMOVED Requirements

### Requirement: Formulario de estimación con carga de `.txt`
**Reason**: describía el cliente Rails (`estimator-web`), retirado cuando el servicio pasó a Go; el cliente web vigente es React.
**Migration**: ver `web-react-client` (formulario) y `streamlit-client`; ambos consumen el backend Go.

### Requirement: Visualización del resultado
**Reason**: cliente Rails retirado.
**Migration**: ver `web-react-client`, «Visualización del resultado».

### Requirement: Barra lateral de contexto del prompt
**Reason**: cliente Rails retirado.
**Migration**: ver `web-react-client`, «Barra lateral de contexto del prompt».

### Requirement: Historial de estimaciones
**Reason**: cliente Rails retirado.
**Migration**: ver `web-react-client`, «Historial de estimaciones».

### Requirement: Manejo de errores del cliente HTTP
**Reason**: cliente Rails retirado.
**Migration**: ver `web-react-client`, «Manejo de errores del cliente HTTP».
