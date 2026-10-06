# Aplicación web Rails del estimador (cliente HTTP de la API; sin base de datos propia).
#
#   docker build -t estimator-web .
#   docker run --rm -p 3000:3000 -e SECRET_KEY_BASE=... -e ESTIMATOR_API_URL=http://api:8000 estimator-web
ARG RUBY_VERSION=3.4

# =============================================================================
# Etapa 1 — build: instala las gemas de producción
# =============================================================================
FROM ruby:${RUBY_VERSION}-slim AS build

RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends build-essential git libyaml-dev \
 && rm -rf /var/lib/apt/lists/*

ENV BUNDLE_DEPLOYMENT=1 \
    BUNDLE_WITHOUT="development:test" \
    BUNDLE_PATH=/usr/local/bundle

WORKDIR /rails
COPY Gemfile Gemfile.lock ./
RUN bundle install --jobs 4 \
 && rm -rf "${BUNDLE_PATH}"/ruby/*/cache "${BUNDLE_PATH}"/ruby/*/bundler/gems/*/.git

# =============================================================================
# Etapa 2 — runtime: imagen mínima, usuario sin privilegios
# =============================================================================
FROM ruby:${RUBY_VERSION}-slim AS runtime

ENV RAILS_ENV=production \
    RAILS_LOG_TO_STDOUT=1 \
    BUNDLE_DEPLOYMENT=1 \
    BUNDLE_WITHOUT="development:test" \
    BUNDLE_PATH=/usr/local/bundle

RUN groupadd --system --gid 10001 rails \
 && useradd --system --uid 10001 --gid rails --no-create-home --shell /usr/sbin/nologin rails

WORKDIR /rails
COPY --from=build /usr/local/bundle /usr/local/bundle
COPY --chown=rails:rails . .
RUN mkdir -p tmp log && chown -R rails:rails tmp log

USER rails

EXPOSE 3000

# Sonda sin curl (no existe en -slim): falla si /up no responde 200 en 3 s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["ruby", "-rnet/http", "-e", "exit(Net::HTTP.start('127.0.0.1', 3000, read_timeout: 3) { |h| h.get('/up').code == '200' } ? 0 : 1)"]

# SECRET_KEY_BASE y ESTIMATOR_API_URL se inyectan en tiempo de ejecución.
CMD ["bin/rails", "server", "-b", "0.0.0.0", "-p", "3000"]
