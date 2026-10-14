# CLI de OpenSpec para validar y archivar cambios sin instalar Node en el host.
#   docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict
# La versión coincide con openspec/README.md y con el CI.
FROM node:24-slim

ARG OPENSPEC_VERSION=1.13.2
RUN npm install -g @fission-ai/openspec@${OPENSPEC_VERSION} && npm cache clean --force

ENV OPENSPEC_TELEMETRY=0
WORKDIR /repo
ENTRYPOINT ["openspec"]
