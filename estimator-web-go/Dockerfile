# Servicio web del estimador en Go (cliente de la API de IA; PostgreSQL solo para el historial del Chunking Lab).
#
#   docker build -t estimator-web .
#   docker run --rm -p 3000:3000 -e SECRET_KEY_BASE=... -e ESTIMATOR_API_URL=http://api:8000 \
#     -e DATABASE_URL=postgres://usuario:clave@host:5432/base estimator-web
ARG GO_VERSION=1.25

# =============================================================================
# Etapa de pruebas — toolchain completo; el código se monta en ejecución (docker-compose.verify.yml)
#   docker build --target test -t estimator-web:test .
# Se declara antes de runtime para que `docker build .` siga generando la imagen de producción.
# =============================================================================
FROM golang:${GO_VERSION}-alpine AS test

ENV CGO_ENABLED=0 \
    GOFLAGS=-buildvcs=false
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download
CMD ["go", "test", "./..."]

# =============================================================================
# Etapa de compilación — binario estático, sin símbolos de depuración
# =============================================================================
FROM test AS build

COPY . .
RUN go build -trimpath -ldflags="-s -w" -o /out/estimator-web ./cmd/server

# =============================================================================
# Etapa runtime — imagen mínima sin shell, usuario sin privilegios
# =============================================================================
FROM gcr.io/distroless/static-debian12:nonroot AS runtime

COPY --from=build /out/estimator-web /estimator-web

USER nonroot:nonroot
EXPOSE 3000

# Sonda sin curl ni shell: el propio binario hace `GET /up`.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/estimator-web", "healthcheck"]

# SECRET_KEY_BASE, ESTIMATOR_API_URL y DATABASE_URL se inyectan en tiempo de ejecución. Sin DATABASE_URL el servicio
# funciona igual, solo que el Chunking Lab no podrá guardar sus ejecuciones.
ENTRYPOINT ["/estimator-web"]
