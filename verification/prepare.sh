#!/usr/bin/env bash
# Prepara el estado local de los arneses (`.verification/`, ignorado por Git) desde un clon limpio.
#   verification/prepare.sh            # genera envs ficticios, certificado efímero, caché de tiktoken y fixtures
#   verification/prepare.sh --build    # además construye las imágenes de pruebas y de la pila (pesado)
# Requiere las imágenes de pruebas ya construidas (o --build). El único paso con red es la descarga de cl100k_base.tiktoken.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BUILD=0; [[ "${1:-}" == "--build" ]] && BUILD=1

if [[ "$BUILD" == 1 ]]; then
  log "construcción de las imágenes de pruebas (docker-compose.verify.yml)"
  heavy docker compose -p "$PROJECT" -f docker-compose.verify.yml build react-test api-test web-test; guard
  log "construcción de las imágenes de la pila (tags :verification)"
  heavy docker compose --env-file /dev/null -p "$PROJECT" -f docker-compose.yml -f verification/compose.network.yml build; guard
fi

log "credenciales ficticias de la IA"
printf 'LLM_PROVIDER=openai\nOPENAI_API_KEY=sk-test-dummy\nMODERATION_ENABLED=false\n' > "$LOCAL/estimador-cag.env"

log "certificado autofirmado efímero para el proveedor HTTPS simulado"
if [[ ! -f "$LOCAL/certs/cert.pem" ]]; then
  docker run --rm --network none --user "$(id -u):$(id -g)" --entrypoint sh -v "$LOCAL/certs:/c" pgvector/pgvector:pg17 -c \
    'openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=proveedor-simulado.test" -addext "subjectAltName=DNS:proveedor-simulado.test" -keyout /c/key.pem -out /c/cert.pem 2>/dev/null && chmod 644 /c/key.pem /c/cert.pem'
fi

log "caché de tiktoken (cl100k_base)"
# Procedencia: codificación oficial de OpenAI que descarga la biblioteca tiktoken. El SHA-256 esperado es el `expected_hash` de
# `tiktoken_ext/openai_public.py` para cl100k_base. El nombre de archivo que usa tiktoken es el SHA-1 de la URL (9b5ad71b…).
TIKTOKEN_URL="https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
TIKTOKEN_SHA256="223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
TIKTOKEN_FILE="$LOCAL/cache/cl100k_base.tiktoken"
if [[ -f "$TIKTOKEN_FILE" ]] && [[ "$(sha256sum "$TIKTOKEN_FILE" | cut -d' ' -f1)" == "$TIKTOKEN_SHA256" ]]; then
  echo "reutilizado (SHA-256 correcto)"
else
  rm -f "$TIKTOKEN_FILE"
  docker run --rm --user "$(id -u):$(id -g)" -v "$LOCAL/cache:/cache" -e URL="$TIKTOKEN_URL" -e SHA256="$TIKTOKEN_SHA256" \
    --entrypoint python "$VERIFY_API_IMAGE" -c '
import hashlib, os, sys, urllib.request
data = urllib.request.urlopen(os.environ["URL"], timeout=120).read()
digest = hashlib.sha256(data).hexdigest()
if digest != os.environ["SHA256"]:
    sys.exit(f"SHA-256 inesperado: {digest}")
open("/cache/cl100k_base.tiktoken", "wb").write(data)
print("descargado y verificado")' || { rm -f "$TIKTOKEN_FILE"; echo "ERROR: no se pudo descargar o verificar cl100k_base.tiktoken" >&2; exit 1; }
  [[ "$(sha256sum "$TIKTOKEN_FILE" | cut -d' ' -f1)" == "$TIKTOKEN_SHA256" ]] || { rm -f "$TIKTOKEN_FILE"; echo "ERROR: el SHA-256 del archivo no coincide" >&2; exit 1; }
fi

log "adjuntos sintéticos (PDF y DOCX) para los recorridos de extremo a extremo"
docker run --rm --network none --user "$(id -u):$(id -g)" -v "$ROOT/estimador-cag:/app:ro" -w /app --entrypoint python "$VERIFY_API_IMAGE" -c "
import base64, json
from tests._documents import make_pdf, make_docx
print(json.dumps({'pdf': base64.b64encode(make_pdf('Requisitos del proyecto: portal web de pedidos con facturación y panel de métricas para una pyme.')).decode(), 'docx': base64.b64encode(make_docx(['Requisitos del proyecto', 'Portal de pedidos, facturación electrónica y panel de métricas.'])).decode()}))" > "$LOCAL/fixtures/attachments.json"
guard; echo "preparación OK ($LOCAL)"
