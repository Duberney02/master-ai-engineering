# Proposal

## Why

La interfaz web actual (`estimator-web`) está construida con Rails y vistas ERB con JavaScript en línea. Se quiere una versión con el stack de React para disponer de una interfaz basada en componentes reutilizables, tipada y con pruebas de componente, sin perder ninguna de las funciones que ya ofrece la web Rails. La API del estimador ya expone todo lo necesario, así que el cambio es solo de cliente.

## What Changes

- Nueva aplicación `estimator-web-react/` (React + TypeScript + Vite) que reproduce, componente a componente, las vistas y comportamientos de la web Rails: formulario con carga de `.txt`, indicador de carga con temporizador, resultado con tabla de fases, barra lateral de contexto del prompt, historial y pantalla de error.
- Cliente HTTP TypeScript equivalente a `EstimatorApi` (Faraday): mismos endpoints, tiempos de espera y traducción de fallos a mensajes saneados en español.
- Validación del formulario en el cliente con las mismas reglas y mensajes que `EstimationForm`, para no llamar a la API con entradas inválidas.
- Imagen Docker multietapa (build con Node, runtime con nginx sin privilegios) que sirve la SPA y hace de proxy inverso de `/api/` y `/health` hacia la API, de modo que el navegador solo habla con su propio origen (sin CORS ni cambios en la API).
- Nuevo servicio `estimator-web-react` en el `docker-compose.yml` raíz, en el puerto 3001.
- La web Rails **se conserva** sin cambios: ambas interfaces conviven. No hay cambios **BREAKING**.

## Capabilities

### New Capabilities
- `estimator/web-react-client`: aplicación web React que consume la API del estimador por HTTP y ofrece formulario, resultado, barra lateral de contexto del prompt, historial y manejo saneado de errores, con paridad funcional con la web Rails.

### Modified Capabilities
- `estimator/deployment-stack`: el compose raíz añade el servicio `estimator-web-react` (puerto 3001, healthcheck y dependencia de la API saludable) y la lista de servicios con puertos publicados pasa a incluirlo.

## Impact

- Código nuevo: `estimator-web-react/` (fuentes, pruebas Vitest, Dockerfile, configuración nginx, README).
- `docker-compose.yml`: un servicio nuevo; el resto no cambia.
- `README.md` raíz: mención de la nueva web y su puerto.
- `estimador-cag/` (API) y `estimator-web/` (Rails): sin cambios.
- Dependencias nuevas solo en el nuevo directorio (React, React Router, Vite, Vitest, Testing Library); Node 20.19 o posterior para desarrollo.
- Supuestos: TypeScript y Vite como herramientas; React Router para las rutas `/`, `/estimations` y `/estimations/:id` (mismas URL que Rails); la web Rails no se retira en este cambio.
