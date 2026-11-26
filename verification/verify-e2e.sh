#!/usr/bin/env bash
# Recorridos de extremo a extremo (cliente → Nginx → Go → Python) con un proyecto Compose propio y proveedores simulados.
#   verification/verify-e2e.sh stack          # reconstruye la imagen de IA y levanta la pila con el proveedor simulado
#   verification/verify-e2e.sh flows          # REST, SSE, sesiones, adjuntos, historial, errores, límites y autorización
#   verification/verify-e2e.sh backend-down   # Python detenido: errores saneados desde React → Go
#   verification/verify-e2e.sh cancellation   # barreras deterministas: REST y SSE hasta Python, filas y reintentos
#   verification/verify-e2e.sh clean          # down -v SOLO del proyecto
# Variables: PROJECT (verify-<nombre>), HEAVY_LOCK. Requiere verification/prepare.sh. Evidencias en .verification/evidence/<PROJECT>/.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

C=(docker compose --env-file /dev/null -p "$PROJECT" -f docker-compose.yml -f verification/compose.network.yml -f verification/compose.e2e.yml --profile e2e)
wait_healthy() { for _ in $(seq 1 60); do [[ "$("${C[@]}" ps --format '{{.Health}}' "$1" 2>/dev/null)" == healthy ]] && return 0; sleep 2; done; echo "ERROR: $1 no llegó a healthy" >&2; return 1; }
driver() { "${C[@]}" run --rm --no-deps -T e2e "$1" 2>&1 | tee "$EVIDENCE/e2e-$1.txt"; }

case "${1:-}" in
  stack)
    heavy "${C[@]}" build estimador-cag; guard
    "${C[@]}" up -d --wait --wait-timeout 300 estimador-cag estimator-web estimator-web-react estimator-web-db redis postgres openai-fake; guard
    "${C[@]}" ps --format 'table {{.Service}}\t{{.Status}}' ;;
  flows) driver flows; guard ;;
  backend-down)
    "${C[@]}" stop estimador-cag
    driver backend-down || { "${C[@]}" start estimador-cag; exit 1; }
    "${C[@]}" start estimador-cag; wait_healthy estimador-cag; guard ;;
  cancellation)
    E2E_IA_URL=http://ia-fixture:8000 "${C[@]}" --profile e2e-fixture up -d --wait --no-deps --force-recreate ia-fixture
    E2E_IA_URL=http://ia-fixture:8000 "${C[@]}" up -d --wait --no-deps --force-recreate estimator-web
    "${C[@]}" restart estimator-web-react >/dev/null; wait_healthy estimator-web-react
    E2E_IA_URL=http://ia-fixture:8000 driver cancellation; guard ;;
  clean) "${C[@]}" --profile e2e-fixture --profile probes down -v --remove-orphans ;;
  *) echo "uso: $0 {stack|flows|backend-down|cancellation|clean}" >&2; exit 2 ;;
esac
