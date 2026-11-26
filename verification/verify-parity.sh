#!/usr/bin/env bash
# Paridad funcional: genera `go test -json` y la salida JSON de Vitest con el Compose de verificación y comprueba que cada
# prueba nombrada en verification/parity.json existe y pasó (las referencias a HTML retirado figuran como retiradas).
#   verification/verify-parity.sh
# Variables: PROJECT, HEAVY_LOCK. Requiere las imágenes de pruebas (verification/prepare.sh --build).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

V=(docker compose --env-file /dev/null -p "$PROJECT" -f docker-compose.verify.yml)
log "go test -json (PostgreSQL efímero)"
heavy "${V[@]}" run --rm -T web-test -count=1 -json ./... > "$EVIDENCE/go-test.json"; guard
log "Vitest (JSON)"
heavy "${V[@]}" run --rm -T react-test sh -c 'npx vitest run --reporter=json --outputFile=/tmp/v.json --maxWorkers=1 >/dev/null 2>&1; s=$?; cat /tmp/v.json; exit $s' > "$EVIDENCE/vitest.json"; guard
log "matriz de paridad"
PARITY_EVIDENCE_DIR="$EVIDENCE" docker compose --env-file /dev/null -p "$PROJECT" -f docker-compose.verify.yml -f verification/compose.integration.yml \
  run --rm --no-deps -T parity-check 2>&1 | tee "$EVIDENCE/parity.txt"
