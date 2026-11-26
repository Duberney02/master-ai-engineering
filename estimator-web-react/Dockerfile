# Aplicación web React del estimador: SPA estática servida por nginx sin privilegios, que hace de
# proxy inverso del servicio Go (el navegador solo habla con este origen; no hay claves de proveedores).
#
#   docker build -t estimator-web-react .
#   docker run --rm -p 3001:8080 -e API_UPSTREAM=http://host.docker.internal:3000 estimator-web-react

# =============================================================================
# Etapa 1 — build: instala dependencias y compila la SPA (tsc + vite)
# =============================================================================
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# =============================================================================
# Etapa 2 — runtime: nginx sin privilegios (usuario 101, puerto 8080)
# =============================================================================
FROM nginxinc/nginx-unprivileged:stable-alpine AS runtime

# Dirección interna del servicio Go (única frontera hacia la IA) y plazos por tipo de operación; el entrypoint los
# sustituye en la plantilla al arrancar. 35 s / 615 s dan margen sobre los 30 s / 600 s de Go.
ENV API_UPSTREAM=http://estimator-web:3000 \
    NGINX_CONNECT_TIMEOUT=5s \
    NGINX_REGULAR_TIMEOUT=35s \
    NGINX_LONG_TIMEOUT=615s

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# Los scripts de /docker-entrypoint.d/ se ejecutan en orden: el 15 valida los plazos antes de generar la configuración.
COPY --chmod=755 validar-plazos.sh /docker-entrypoint.d/15-validar-plazos.sh

EXPOSE 8080

# Sonda local: falla si /healthz no responde 200 en 3 s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "--timeout=3", "http://127.0.0.1:8080/healthz"]
