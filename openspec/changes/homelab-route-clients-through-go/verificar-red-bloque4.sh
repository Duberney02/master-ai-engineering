#!/usr/bin/env bash
# Arnés de 13.1 y 13.2 (y de la parte de red de 12.1). Solo opera sobre un proyecto Compose propio (hl-s1, hl-s2, hl-s3).
#
#   openspec/changes/homelab-route-clients-through-go/verificar-red-bloque4.sh estatico        # sin contenedores
#   openspec/changes/homelab-route-clients-through-go/verificar-red-bloque4.sh pila            # construye y levanta (pesado)
#   openspec/changes/homelab-route-clients-through-go/verificar-red-bloque4.sh persistencia    # reinicio sin borrar volúmenes
#   openspec/changes/homelab-route-clients-through-go/verificar-red-bloque4.sh red             # 13.2: publicaciones y sondas
#   openspec/changes/homelab-route-clients-through-go/verificar-red-bloque4.sh limpiar         # down -v SOLO del proyecto
#
# Variables: PROYECTO (hl-s1 por defecto), HEAVY (envoltorio flock), TUNEL=1 para probar el túnel SSH a localhost.
# Los resultados se guardan en .block4/evidencias/. Se detiene si cambia /sys/fs/ext4/sda2/errors_count.
set -euo pipefail

PROYECTO="${PROYECTO:-hl-s1}"
[[ "$PROYECTO" =~ ^hl-s[123]$ ]] || { echo "PROYECTO debe ser hl-s1, hl-s2 o hl-s3 (recibido '$PROYECTO')" >&2; exit 2; }
RAIZ="$(git rev-parse --show-toplevel)"; cd "$RAIZ"
CAMBIO=openspec/changes/homelab-route-clients-through-go
BLOQUE=.block4; [[ "$PROYECTO" != hl-s1 ]] && BLOQUE=".block4-${PROYECTO#hl-}"
EVID="$BLOQUE/evidencias"; mkdir -p "$EVID" "$BLOQUE/certs" "$BLOQUE/docker-config"
[[ -f "$BLOQUE/docker-config/config.json" ]] || echo '{}' > "$BLOQUE/docker-config/config.json"
export DOCKER_CONFIG="$RAIZ/$BLOQUE/docker-config"
HEAVY="${HEAVY:-/home/dccadmin/workspace/.homelab-parallel/heavy}"
NODE_IMG=homelab-block1-307a8b9-react:test
EXT4=/sys/fs/ext4/sda2/errors_count
E0="$(cat "$EXT4")"
C=(docker compose --env-file /dev/null -p "$PROYECTO" -f docker-compose.yml -f "$CAMBIO/compose.bloque4.yml")

guardia() { [[ "$(cat "$EXT4")" == "$E0" ]] || { echo "ERROR: cambió el contador EXT4; se detiene todo" >&2; exit 3; }; }
nodo() { docker run --rm --network none -v "$RAIZ:/r:ro" -w /r "$NODE_IMG" node "$@"; }
registrar() { echo "== $*"; }
preparar() {
  printf 'LLM_PROVIDER=openai\nOPENAI_API_KEY=sk-test-dummy\nMODERATION_ENABLED=false\n' > "$BLOQUE/estimador-cag.env"
  if [[ ! -f "$BLOQUE/certs/cert.pem" ]]; then   # certificado autofirmado efímero, sin tocar el host
    docker run --rm --network none --user "$(id -u):$(id -g)" --entrypoint sh -v "$RAIZ/$BLOQUE/certs:/c" pgvector/pgvector:pg17 -c \
      'openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=proveedor-simulado.test" -addext "subjectAltName=DNS:proveedor-simulado.test" -keyout /c/key.pem -out /c/cert.pem 2>/dev/null && chmod 644 /c/key.pem /c/cert.pem'
  fi
}
sonda_dentro() { # sonda_dentro <servicio> <json de objetivos>  -> ejecuta la sonda en la red del servicio
  "${C[@]}" run --rm --no-deps -T -e SONDA_OBJETIVOS="$2" ${3:+-e SONDA_GATEWAY_PUERTOS="$3"} sonda-cliente
}

estatico() {
  registrar "configuración y topología"
  "${C[@]}" --profile sondas config -q
  "${C[@]}" config --format json > "$EVID/config-bloque4.json"
  nodo "$CAMBIO/verificar-compose-bloque4.mjs" "$EVID/config-bloque4.json" docker-compose.yml | tee "$EVID/topologia.json"
  nodo --test "$CAMBIO/verificar-compose-bloque4.test.mjs" | grep -E "^# (tests|pass|fail)"
  docker run --rm --network none -v "$RAIZ:/r:ro" -w /r "$NODE_IMG" node "$CAMBIO/sonda-red-bloque4.mjs" --autoprueba | grep '"ok"'
}

pila() {
  registrar "construcción y arranque ($PROYECTO)"
  "$HEAVY" "$PROYECTO-build" "${C[@]}" build
  guardia
  "${C[@]}" up -d --wait --wait-timeout 300
  "${C[@]}" ps --format 'table {{.Service}}\t{{.Status}}' | tee "$EVID/ps.txt"
  [[ "$("${C[@]}" ps --format '{{.Health}}' | grep -c '^healthy$')" == 6 ]] || { echo "ERROR: no hay seis servicios healthy" >&2; exit 1; }
  registrar "sondas internas"
  "${C[@]}" exec -T estimador-cag python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
  "${C[@]}" exec -T estimator-web /estimator-web healthcheck
  "${C[@]}" exec -T estimator-web-react wget -q -O /dev/null --timeout=3 http://127.0.0.1:8080/healthz
  "${C[@]}" exec -T redis redis-cli ping | grep -q PONG
  "${C[@]}" exec -T redis redis-cli MODULE LIST | grep -qi search || { echo "ERROR: RediSearch no disponible" >&2; exit 1; }
  "${C[@]}" exec -T postgres pg_isready -U estimator -d estimator
  "${C[@]}" exec -T estimator-web-db pg_isready -U estimator -d estimator_web
  guardia
}

persistencia() {
  registrar "persistencia entre reinicios (sin eliminar volúmenes)"
  marca="hl_marca_$(date +%s)"
  "${C[@]}" exec -T postgres psql -U estimator -d estimator -qc "create table if not exists hl_marca(v text); insert into hl_marca values ('$marca')"
  "${C[@]}" exec -T estimator-web-db psql -U estimator -d estimator_web -qc "create table if not exists hl_marca(v text); insert into hl_marca values ('$marca')"
  "${C[@]}" down --remove-orphans          # sin -v: conserva los volúmenes del proyecto
  "${C[@]}" up -d --wait --wait-timeout 300
  for db in "postgres estimator" "estimator-web-db estimator_web"; do set -- $db
    "${C[@]}" exec -T "$1" psql -U estimator -d "$2" -Atc "select v from hl_marca" | grep -q "$marca" || { echo "ERROR: se perdió la marca en $1" >&2; exit 1; }
  done
  echo "persistencia OK ($marca)"; guardia
}

red() {
  registrar "13.2 publicaciones"
  "${C[@]}" ps --format '{{.Service}} {{.Publishers}}' | tee "$EVID/publicaciones.txt"
  ss -ltnH | awk '{print $4}' | grep -E ':3001$' | tee "$EVID/ss-3001.txt"
  ! grep -qE '^(\*|0\.0\.0\.0|\[::\]|::):3001$' "$EVID/ss-3001.txt" || { echo "ERROR: 3001 publicado fuera de loopback/IPv6" >&2; exit 1; }
  grep -q '^127.0.0.1:3001$' "$EVID/ss-3001.txt"
  curl -fsS http://127.0.0.1:3001/healthz >/dev/null
  ip_host="$(hostname -I | awk '{print $1}')"
  ! curl -sS -m 3 -o /dev/null "http://$ip_host:3001/healthz" || { echo "ERROR: acceso directo por la IP del host sin túnel" >&2; exit 1; }
  if [[ "${TUNEL:-0}" == 1 ]]; then
    ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -f -N -L 3101:127.0.0.1:3001 "$USER@localhost"
    curl -fsS -m 5 http://127.0.0.1:3101/healthz >/dev/null; pkill -f 'ssh .*3101:127.0.0.1:3001' || true
  fi
  [[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/api/v1/ai/settings)" == 403 ]] || { echo "ERROR: la lectura administrativa no devolvió 403" >&2; exit 1; }
  registrar "13.2 sondas desde client-net"
  cag_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$("${C[@]}" ps -q estimador-cag)" | awk '{print $1}')"
  ip_host="$(hostname -I | awk '{print $1}')"
  objetivos="$(printf '[{"nombre":"go","host":"estimator-web","puerto":3000,"esperado":"alcanza"},
   {"nombre":"ia-dns","host":"estimador-cag","puerto":8000,"esperado":"falla"},
   {"nombre":"redis-dns","host":"redis","puerto":6379,"esperado":"falla"},
   {"nombre":"postgres-dns","host":"postgres","puerto":5432,"esperado":"falla"},
   {"nombre":"web-db-dns","host":"estimator-web-db","puerto":5432,"esperado":"falla"},
   {"nombre":"host.docker.internal","host":"host.docker.internal","puerto":5432,"esperado":"falla"},
   {"nombre":"ia-ip","host":"%s","puerto":8000,"esperado":"falla"},
   {"nombre":"host-ollama","host":"%s","puerto":11434,"esperado":"falla"},
   {"nombre":"host-postgres","host":"%s","puerto":5432,"esperado":"falla"},
   {"nombre":"host-open-webui","host":"%s","puerto":3000,"esperado":"falla"}]' "${cag_ip:-10.255.255.1}" "$ip_host" "$ip_host" "$ip_host")"
  sonda_dentro sonda-cliente "$objetivos" 5432,11434,3000,8000,6379 | tee "$EVID/sonda-cliente.json"
  registrar "13.2 salida HTTPS de IA hacia el proveedor simulado y credenciales"
  "${C[@]}" --profile sondas up -d --wait proveedor-simulado
  "${C[@]}" exec -T estimador-cag python -c "import ssl,urllib.request as u; print(u.urlopen('https://proveedor-simulado.test:8443/ping', context=ssl._create_unverified_context(), timeout=5).read())"
  "${C[@]}" exec -T estimator-web env | grep -Eic 'API_KEY|OPENAI|ANTHROPIC' | grep -qx 0 || { echo "ERROR: Go recibe claves de proveedor" >&2; exit 1; }
  "${C[@]}" exec -T estimator-web-react env | grep -Eic 'API_KEY|OPENAI|ANTHROPIC' | grep -qx 0 || { echo "ERROR: React recibe claves" >&2; exit 1; }
  "${C[@]}" exec -T estimador-cag env | grep -q '^OPENAI_API_KEY=sk-test-dummy$'
  guardia; echo "red OK"
}

limpiar() { "${C[@]}" --profile sondas down -v --remove-orphans; }

case "${1:-}" in
  estatico) preparar; estatico ;;
  pila) preparar; pila ;;
  persistencia) persistencia ;;
  red) red ;;
  limpiar) limpiar ;;
  *) echo "uso: $0 {estatico|pila|persistencia|red|limpiar}" >&2; exit 2 ;;
esac
