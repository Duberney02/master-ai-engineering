#!/usr/bin/env bash
# Recorridos de extremo a extremo de 14.1 (cliente → Nginx → Go → Python) en un proyecto Compose propio (hl-s1/2/3).
#   verificar-e2e-bloque6.sh pila         # reconstruye solo la imagen de IA y levanta la pila con el proveedor simulado
#   verificar-e2e-bloque6.sh flujos       # REST, SSE, sesiones, adjuntos, historial, errores, límites y autorización
#   verificar-e2e-bloque6.sh caido        # Python detenido: errores saneados desde React→Go
#   verificar-e2e-bloque6.sh cancelacion  # barreras deterministas: REST y SSE hasta Python, filas y reintentos
#   verificar-e2e-bloque6.sh limpiar      # down -v SOLO del proyecto
# Resultados en .block4/evidencias/e2e-*.txt. Se detiene si cambia /sys/fs/ext4/sda2/errors_count.
set -euo pipefail
PROYECTO="${PROYECTO:-hl-s1}"
[[ "$PROYECTO" =~ ^hl-s[123]$ ]] || { echo "PROYECTO debe ser hl-s1, hl-s2 o hl-s3" >&2; exit 2; }
RAIZ="$(git rev-parse --show-toplevel)"; cd "$RAIZ"
CAMBIO=openspec/changes/homelab-route-clients-through-go
BLOQUE=.block4; [[ "$PROYECTO" != hl-s1 ]] && BLOQUE=".block4-${PROYECTO#hl-}"
EVID="$BLOQUE/evidencias"; mkdir -p "$EVID" "$BLOQUE/docker-config"; [[ -f "$BLOQUE/docker-config/config.json" ]] || echo '{}' > "$BLOQUE/docker-config/config.json"
export DOCKER_CONFIG="$RAIZ/$BLOQUE/docker-config"
HEAVY="${HEAVY:-/home/dccadmin/workspace/.homelab-parallel/heavy}"
EXT4=/sys/fs/ext4/sda2/errors_count; E0="$(cat "$EXT4")"
C=(docker compose --env-file /dev/null -p "$PROYECTO" -f docker-compose.yml -f "$CAMBIO/compose.bloque4.yml" -f "$CAMBIO/compose.bloque6.yml" --profile e2e)
guardia() { [[ "$(cat "$EXT4")" == "$E0" ]] || { echo "ERROR: cambió el contador EXT4; se detiene todo" >&2; exit 3; }; }
espera_sana() { for _ in $(seq 1 60); do [[ "$("${C[@]}" ps --format '{{.Health}}' "$1" 2>/dev/null)" == healthy ]] && return 0; sleep 2; done; echo "ERROR: $1 no llegó a healthy" >&2; return 1; }
driver() { "${C[@]}" run --rm --no-deps -T e2e "$1" 2>&1 | tee "$EVID/e2e-$1.txt"; }

case "${1:-}" in
  pila)
    printf 'LLM_PROVIDER=openai\nOPENAI_API_KEY=sk-test-dummy\nMODERATION_ENABLED=false\n' > "$BLOQUE/estimador-cag.env"
    "$HEAVY" "$PROYECTO-build-ia" "${C[@]}" build estimador-cag; guardia
    "${C[@]}" up -d --wait --wait-timeout 300 estimador-cag estimator-web estimator-web-react estimator-web-db redis postgres openai-simulado; guardia
    "${C[@]}" ps --format 'table {{.Service}}\t{{.Status}}' ;;
  flujos) driver flujos; guardia ;;
  caido)
    "${C[@]}" stop estimador-cag
    driver caido || { "${C[@]}" start estimador-cag; exit 1; }
    "${C[@]}" start estimador-cag; espera_sana estimador-cag; guardia ;;
  cancelacion)
    E2E_IA_URL=http://ia-fixture:8000 "${C[@]}" --profile e2e-fixture up -d --wait --no-deps --force-recreate ia-fixture
    E2E_IA_URL=http://ia-fixture:8000 "${C[@]}" up -d --wait --no-deps --force-recreate estimator-web
    "${C[@]}" restart estimator-web-react >/dev/null; espera_sana estimator-web-react
    E2E_IA_URL=http://ia-fixture:8000 driver cancelacion; guardia ;;
  limpiar) "${C[@]}" --profile e2e-fixture --profile sondas down -v --remove-orphans ;;
  *) echo "uso: $0 {pila|flujos|caido|cancelacion|limpiar}" >&2; exit 2 ;;
esac
