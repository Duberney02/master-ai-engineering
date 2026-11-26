#!/usr/bin/env bash
# Nginx del cliente React delante de un upstream simulado de Go: SSE sin buffering, cancelación hasta el upstream, plazos
# por ruta, límite de cuerpo, cabeceras reenviadas y negativa a arrancar con plazos incoherentes.
#   verification/verify-nginx.sh run     # ejecuta la comprobación y la prueba de plazos incoherentes
#   verification/verify-nginx.sh clean   # down -v SOLO del proyecto
# Variables: PROJECT, HEAVY_LOCK. Usa la imagen pública de Nginx sin privilegios (se descarga si falta) y la de herramientas Node.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

C=(docker compose --env-file /dev/null -p "$PROJECT" -f verification/compose.nginx.yml)

case "${1:-}" in
  run)
    "${C[@]}" up -d --wait --wait-timeout 90 nginx-upstream nginx; guard
    "${C[@]}" run --rm -T nginx-check 2>&1 | tee "$EVIDENCE/nginx.txt"; guard
    log "plazos incoherentes: el contenedor debe negarse a arrancar"
    if "${C[@]}" run --rm -T nginx-bad > "$EVIDENCE/nginx-bad.txt" 2>&1; then echo "ERROR: nginx arrancó con plazos incoherentes" >&2; exit 1; fi
    echo "nginx OK" ;;
  clean) "${C[@]}" down -v --remove-orphans ;;
  *) echo "uso: $0 {run|clean}" >&2; exit 2 ;;
esac
