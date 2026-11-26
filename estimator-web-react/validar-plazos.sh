#!/bin/sh
# Valida los plazos de nginx antes de arrancar (se ejecuta desde /docker-entrypoint.d/ antes de la plantilla).
# Relaciones: conexión <= habitual < largo. Un valor inválido o una relación rota impide el arranque.
set -eu
seconds() {
    case "$1" in
        *[!0-9s]*|""|s|*s?*) echo "plazo inválido: $1" >&2; exit 1 ;;
    esac
    value="${1%s}"
    [ -n "$value" ] || { echo "plazo inválido: $1" >&2; exit 1; }
    echo "$value"
}
connect=$(seconds "${NGINX_CONNECT_TIMEOUT:-5s}")
regular=$(seconds "${NGINX_REGULAR_TIMEOUT:-35s}")
long=$(seconds "${NGINX_LONG_TIMEOUT:-615s}")
if [ "$connect" -gt "$regular" ] || [ "$regular" -ge "$long" ]; then
    echo "plazos incoherentes: conexión=${connect}s habitual=${regular}s largo=${long}s (se exige conexión <= habitual < largo)" >&2
    exit 1
fi
