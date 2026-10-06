# Aplicación web React del estimador: SPA estática servida por nginx sin privilegios, que hace de
# proxy inverso de la API (el navegador solo habla con este origen; no hay claves de proveedores).
#
#   docker build -t estimator-web-react .
#   docker run --rm -p 3001:8080 -e API_UPSTREAM=http://host.docker.internal:8000 estimator-web-react

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

# Dirección interna de la API; el entrypoint la sustituye en la plantilla al arrancar.
ENV API_UPSTREAM=http://estimador-cag:8000

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080

# Sonda local: falla si /healthz no responde 200 en 3 s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "--timeout=3", "http://127.0.0.1:8080/healthz"]
