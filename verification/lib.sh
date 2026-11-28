# Funciones comunes de los arneses de verificación. Se carga con `source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"`.
# Resuelve todas las rutas respecto a la raíz del repositorio, de modo que los scripts funcionan desde cualquier directorio.
# No contiene rutas propias de una máquina: lo específico del entorno se pasa por variables (ver README.md).

VERIF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$VERIF_DIR/.." && pwd)"
cd "$ROOT"

# Estado local no versionado (caché, evidencias, certificados, fixtures): ignorado por Git.
LOCAL="$ROOT/.verification"
mkdir -p "$LOCAL/cache" "$LOCAL/fixtures" "$LOCAL/certs" "$LOCAL/docker-config"
[[ -f "$LOCAL/docker-config/config.json" ]] || echo '{}' > "$LOCAL/docker-config/config.json"
export DOCKER_CONFIG="$LOCAL/docker-config"   # sin credenciales ni helpers del usuario

# Proyecto Compose propio: siempre con prefijo `verify-` para no tocar la pila real ni otros recursos.
PROJECT="${PROJECT:-verify-local}"
[[ "$PROJECT" =~ ^verify-[a-z0-9][a-z0-9-]*$ ]] || { echo "PROJECT debe ser 'verify-<nombre>' (recibido '$PROJECT')" >&2; exit 2; }
EVIDENCE="$LOCAL/evidence/$PROJECT"; mkdir -p "$EVIDENCE"

# Imágenes base de las herramientas (se construyen con docker-compose.verify.yml; ver README.md). Se pueden sustituir por
# variables para reutilizar imágenes ya existentes.
export VERIFY_NODE_IMAGE="${VERIFY_NODE_IMAGE:-estimator-web-react:test}"
export VERIFY_API_IMAGE="${VERIFY_API_IMAGE:-estimador-cag:test}"
export VERIFY_GO_IMAGE="${VERIFY_GO_IMAGE:-estimator-web-go:test}"

# Operaciones pesadas (construcciones y regresiones): si HEAVY_LOCK apunta a un archivo, se serializan con flock.
heavy() { if [[ -n "${HEAVY_LOCK:-}" ]]; then flock "$HEAVY_LOCK" "$@"; else "$@"; fi; }

# Guardia de almacenamiento: detiene todo si aumenta el contador de errores de EXT4 del disco donde vive el repositorio.
EXT4_COUNTER=""
_dev="$(findmnt -no SOURCE -T "$ROOT" 2>/dev/null | sed 's#.*/##')"
[[ -n "$_dev" && -r "/sys/fs/ext4/$_dev/errors_count" ]] && EXT4_COUNTER="/sys/fs/ext4/$_dev/errors_count"
EXT4_BASE="$([[ -n "$EXT4_COUNTER" ]] && cat "$EXT4_COUNTER" || echo 0)"
guard() {
  [[ -z "$EXT4_COUNTER" ]] && return 0
  [[ "$(cat "$EXT4_COUNTER")" == "$EXT4_BASE" ]] || { echo "ERROR: cambió el contador de errores de EXT4; se detiene todo" >&2; exit 3; }
}

log() { echo "== $*"; }
# Ejecuta el verificador de topología (Node) dentro de la imagen de herramientas, sin red.
node_tool() { docker run --rm --network none -v "$ROOT:/r:ro" -w /r "$VERIFY_NODE_IMAGE" node "$@"; }
