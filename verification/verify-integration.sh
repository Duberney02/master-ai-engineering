#!/usr/bin/env bash
# Cancelación REST, SSE y del Chunking Lab desde Go real hasta el upstream Python aislado (FastAPI real con barreras), con
# PostgreSQL efímero y una red interna sin salida. Ver verification/README.md.
#   verification/verify-integration.sh run     # levanta bases y fixture, ejecuta las pruebas Go de integración
#   verification/verify-integration.sh clean   # down -v SOLO del proyecto
# Variables: PROJECT, HEAVY_LOCK. Requiere verification/prepare.sh y las imágenes de pruebas.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

C=(docker compose --env-file /dev/null -p "$PROJECT" -f docker-compose.verify.yml -f verification/compose.integration.yml)

case "${1:-}" in
  run)
    [[ -f "$LOCAL/cache/cl100k_base.tiktoken" ]] || { echo "ERROR: falta la caché de tiktoken; ejecuta verification/prepare.sh" >&2; exit 1; }
    "${C[@]}" up -d --wait --wait-timeout 120 api-db web-db integration-fixture; guard
    "${C[@]}" run --rm -T go-integration-test 2>&1 | tee "$EVIDENCE/integration.txt"; guard
    grep -q "^ok" "$EVIDENCE/integration.txt" && ! grep -q -- "--- SKIP" "$EVIDENCE/integration.txt" || { echo "ERROR: hay pruebas fallidas u omitidas" >&2; exit 1; }
    echo "integración OK" ;;
  clean) "${C[@]}" down -v --remove-orphans ;;
  *) echo "uso: $0 {run|clean}" >&2; exit 2 ;;
esac
