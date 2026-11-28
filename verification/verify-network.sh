#!/usr/bin/env bash
# Valida la topología de la pila de integración, el aislamiento de red y la persistencia, con un proyecto Compose propio
# (PROJECT=verify-<nombre>, por defecto verify-local). Ver verification/README.md.
#
#   verification/verify-network.sh static        # render de Compose, topología y autopruebas (sin contenedores de la pila)
#   verification/verify-network.sh stack         # construye y levanta la pila (pesado) y comprueba sondas y salud
#   verification/verify-network.sh persistence   # reinicio sin borrar volúmenes: marcas, estimación y comparación sintéticas
#   verification/verify-network.sh network       # publicaciones, IPv6, matriz de comunicaciones, salida HTTPS y credenciales
#   verification/verify-network.sh clean         # down -v SOLO del proyecto
#
# Variables: PROJECT, HEAVY_LOCK (archivo de flock para las operaciones pesadas), TUNNEL=1 (reservada para pruebas de túnel).
# Requiere verification/prepare.sh. Las evidencias quedan en .verification/evidence/<PROJECT>/.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

C=(docker compose --env-file /dev/null -p "$PROJECT" -f docker-compose.yml -f verification/compose.network.yml)

static_checks() {
  log "configuración y topología"
  "${C[@]}" --profile probes config -q
  "${C[@]}" config --format json > "$EVIDENCE/config.json"
  node_tool verification/topology-check.mjs "${EVIDENCE#$ROOT/}/config.json" docker-compose.yml | tee "$EVIDENCE/topology.json"
  node_tool --test verification/topology-check.test.mjs | grep -E "^(# |ℹ )(tests|pass|fail)"
  node_tool verification/probe-network.mjs --self-test | grep '"ok"'
}

stack() {
  log "construcción y arranque ($PROJECT)"
  heavy "${C[@]}" build
  guard
  "${C[@]}" up -d --wait --wait-timeout 300
  "${C[@]}" ps --format 'table {{.Service}}\t{{.Status}}' | tee "$EVIDENCE/ps.txt"
  [[ "$("${C[@]}" ps --format '{{.Health}}' | grep -c '^healthy$')" == 6 ]] || { echo "ERROR: no hay seis servicios healthy" >&2; exit 1; }
  log "sondas internas"
  "${C[@]}" exec -T estimador-cag python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
  "${C[@]}" exec -T estimator-web /estimator-web healthcheck
  "${C[@]}" exec -T estimator-web-react wget -q -O /dev/null --timeout=3 http://127.0.0.1:8080/healthz
  "${C[@]}" exec -T redis redis-cli ping | grep -q PONG
  "${C[@]}" exec -T redis redis-cli MODULE LIST | grep -qi search || { echo "ERROR: RediSearch no disponible" >&2; exit 1; }
  "${C[@]}" exec -T postgres pg_isready -U estimator -d estimator
  "${C[@]}" exec -T estimator-web-db pg_isready -U estimator -d estimator_web
  guard; echo "pila OK"
}

persistence() {
  log "persistencia entre reinicios (sin eliminar volúmenes)"
  marca="verify_marker_$(date +%s)"
  "${C[@]}" exec -T postgres psql -U estimator -d estimator -qc "create table if not exists verify_marker(v text); insert into verify_marker values ('$marca')"
  "${C[@]}" exec -T estimator-web-db psql -U estimator -d estimator_web -qc "create table if not exists verify_marker(v text); insert into verify_marker values ('$marca')"
  # Registros sintéticos en las tablas reales: una estimación (API de IA) y una comparación del Chunking Lab (Go).
  curl -fsS http://127.0.0.1:3001/api/v1/estimations >/dev/null   # crea la tabla de historial si aún no existe
  "${C[@]}" exec -T postgres psql -U estimator -d estimator -qc "delete from estimations where description like '%estimacion sintetica'; insert into estimations(description,options,result,prompt_version,cached,cache_source,model,provider,requested_at,completed_at) values ('$marca estimacion sintetica','{\"project_type\":\"web_saas\",\"detail_level\":\"summary\",\"output_format\":\"phases_table\"}','{\"summary\":\"sintetica\",\"confidence_pct\":80,\"phases\":[{\"name\":\"F1\",\"description\":\"\",\"duration_weeks\":1,\"cost_eur\":100}],\"total_duration_weeks\":1,\"total_cost_eur\":100}','v1',false,'none','fake','fake',now(),now())"
  "${C[@]}" exec -T estimator-web-db psql -U estimator -d estimator_web -qc "insert into chunking_comparisons(strategies,queries,top_k,corpus_label,corpus_count,response_payload,created_at,updated_at) values ('[]','[]',3,'$marca',1,'{}',now(),now())"
  "${C[@]}" down --remove-orphans          # sin -v: conserva los volúmenes del proyecto
  "${C[@]}" up -d --wait --wait-timeout 300
  for db in "postgres estimator" "estimator-web-db estimator_web"; do set -- $db
    "${C[@]}" exec -T "$1" psql -U estimator -d "$2" -Atc "select v from verify_marker" | grep -q "$marca" || { echo "ERROR: se perdió la marca en $1" >&2; exit 1; }
  done
  curl -fsS "http://127.0.0.1:3001/api/v1/estimations?limit=50" | grep -q "$marca" || { echo "ERROR: la estimación sintética no se sirve tras el reinicio (React→Go→IA)" >&2; exit 1; }
  [[ "$("${C[@]}" exec -T estimator-web-db psql -U estimator -d estimator_web -Atc "select count(*) from chunking_comparisons where corpus_label='$marca'")" == 1 ]] || { echo "ERROR: se perdió la comparación sintética" >&2; exit 1; }
  echo "persistencia OK ($marca)"; guard
}

network() {
  log "13.2 publicaciones"
  "${C[@]}" ps --format '{{.Service}} {{.Publishers}}' | tee "$EVIDENCE/publicaciones.txt"
  ss -ltnH | awk '{print $4}' | grep -E ':3001$' | tee "$EVIDENCE/ss-3001.txt"
  ! grep -qE '^(\*|0\.0\.0\.0|\[::\]|::):3001$' "$EVIDENCE/ss-3001.txt" || { echo "ERROR: 3001 publicado fuera de loopback/IPv6" >&2; exit 1; }
  grep -q '^127.0.0.1:3001$' "$EVIDENCE/ss-3001.txt"
  curl -fsS http://127.0.0.1:3001/healthz >/dev/null
  ip_host="$(hostname -I | awk '{print $1}')"
  ! curl -sS -m 3 -o /dev/null "http://$ip_host:3001/healthz" || { echo "ERROR: acceso directo por la IP del host sin túnel" >&2; exit 1; }
  if [[ "${TUNNEL:-0}" == 1 ]]; then
    ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -f -N -L 3101:127.0.0.1:3001 "$USER@localhost"
    curl -fsS -m 5 http://127.0.0.1:3101/healthz >/dev/null; pkill -f 'ssh .*3101:127.0.0.1:3001' || true
  fi
  [[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/api/v1/ai/settings)" == 403 ]] || { echo "ERROR: la lectura administrativa no devolvió 403" >&2; exit 1; }
  log "13.2 IPv6 y redes"
  ! curl -6 -sS -m 3 -o /dev/null "http://[::1]:3001/healthz" || { echo "ERROR: 3001 responde por IPv6" >&2; exit 1; }
  for r in client-net service-net go-data-net ai-data-net ai-egress-net; do
    [[ "$(docker network inspect "${PROJECT}_$r" -f '{{.EnableIPv6}} {{.Internal}}')" == "false "* ]] || { echo "ERROR: $r con IPv6" >&2; exit 1; }
  done
  docker network inspect "${PROJECT}_client-net" -f '{{index .Options "com.docker.network.bridge.enable_ip_masquerade"}}' | grep -qx false
  log "13.2 matriz de comunicaciones"
  : > "$EVIDENCE/matriz.tsv"; fallos=0
  ips() { docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$("${C[@]}" ps -q "$1")"; }
  gw_cliente="$(docker network inspect "${PROJECT}_client-net" -f '{{(index .IPAM.Config 0).Gateway}}')"
  ip_host="$(hostname -I | awk '{print $1}')"
  chk() { # chk <origen> <destino> <esperado> <comando...>
    local o="$1" d="$2" e="$3"; shift 3
    local r=falla; if "$@" >/dev/null 2>&1; then r=alcanza; fi
    local v=OK; [[ "$r" == "$e" ]] || { v=FALLA; fallos=$((fallos+1)); }
    printf '%s\t%s\t%s\t%s\t%s\n' "$o" "$d" "$e" "$r" "$v" | tee -a "$EVIDENCE/matriz.tsv"
  }
  react() { "${C[@]}" exec -T estimator-web-react nc -z -w 3 "$1" "$2"; }
  cag() { "${C[@]}" exec -T estimador-cag python -c "import socket,sys; socket.create_connection((sys.argv[1],int(sys.argv[2])),3)" "$1" "$2"; }
  go() { "${C[@]}" run --rm --no-deps -T -e PROBE_TARGETS="[{\"nombre\":\"x\",\"host\":\"$1\",\"puerto\":$2,\"esperado\":\"alcanza\"}]" probe-go; }
  cag_ips="$(ips estimador-cag)"; redis_ips="$(ips redis)"; pg_ips="$(ips postgres)"; wdb_ips="$(ips estimator-web-db)"
  # React (contenedor real, solo client-net)
  chk react estimator-web:3000 alcanza react estimator-web 3000
  for d in estimador-cag:8000 redis:6379 postgres:5432 estimator-web-db:5432 host.docker.internal:5432; do chk react "$d(DNS)" falla react "${d%%:*}" "${d##*:}"; done
  for ip in $cag_ips; do chk react "$ip:8000(IP-IA)" falla react "$ip" 8000; done
  for ip in $redis_ips; do chk react "$ip:6379(IP-redis)" falla react "$ip" 6379; done
  for ip in $pg_ips; do chk react "$ip:5432(IP-pgIA)" falla react "$ip" 5432; done
  for ip in $wdb_ips; do chk react "$ip:5432(IP-pgGo)" falla react "$ip" 5432; done
  for h in "$gw_cliente" "$ip_host"; do for p in 5432 11434 3000 8000 6379; do chk react "$h:$p" falla react "$h" "$p"; done; done
  for t in 1.1.1.1:443 8.8.8.8:53; do chk react "$t(Internet)" falla react "${t%%:*}" "${t##*:}"; done
  # Go (posición equivalente: client-net, service-net y go-data-net; la imagen no tiene shell)
  chk go estimador-cag:8000 alcanza go estimador-cag 8000
  chk go estimator-web-db:5432 alcanza go estimator-web-db 5432
  for d in redis:6379 postgres:5432; do chk go "$d(DNS)" falla go "${d%%:*}" "${d##*:}"; done
  for ip in $redis_ips; do chk go "$ip:6379(IP-redis)" falla go "$ip" 6379; done
  for ip in $pg_ips; do chk go "$ip:5432(IP-pgIA)" falla go "$ip" 5432; done
  for p in 5432 11434 3000 6379; do chk go "$gw_cliente:$p" falla go "$gw_cliente" "$p"; done
  for t in 1.1.1.1:443 8.8.8.8:53; do chk go "$t(Internet)" falla go "${t%%:*}" "${t##*:}"; done
  # IA (contenedor real)
  chk ia redis:6379 alcanza cag redis 6379
  chk ia postgres:5432 alcanza cag postgres 5432
  chk ia estimator-web-db:5432 falla cag estimator-web-db 5432
  for ip in $wdb_ips; do chk ia "$ip:5432(IP-pgGo)" falla cag "$ip" 5432; done
  for p in 5432 11434 3000; do chk ia "$ip_host:$p" falla cag "$ip_host" "$p"; done
  # Limitación aceptada (sshd del host): se registra, no invalida la matriz.
  for o in react; do r=falla; react "$gw_cliente" 22 >/dev/null 2>&1 && r=alcanza; printf 'react\t%s:22(sshd, limitación aceptada)\t-\t%s\tINFO\n' "$gw_cliente" "$r" | tee -a "$EVIDENCE/matriz.tsv"; done
  [[ "$fallos" == 0 ]] || { echo "ERROR: $fallos comprobaciones de la matriz no coinciden" >&2; exit 1; }
  log "13.2 salida HTTPS de IA hacia el proveedor simulado y credenciales"
  "${C[@]}" --profile probes up -d --wait https-provider-fake
  "${C[@]}" exec -T estimador-cag python -c "import ssl,urllib.request as u; print(u.urlopen('https://https-provider-fake.test:8443/ping', context=ssl._create_unverified_context(), timeout=5).read())"
  for sv in estimator-web estimator-web-react estimator-web-db redis postgres; do   # las imágenes de Go y React no traen `env`: se inspecciona la configuración
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$("${C[@]}" ps -q "$sv")" | grep -Eiq '(OPENAI|ANTHROPIC|COHERE|MISTRAL)|API_KEY' && { echo "ERROR: $sv recibe claves de proveedor" >&2; exit 1; }
    true
  done
  "${C[@]}" exec -T estimador-cag env | grep -q '^OPENAI_API_KEY=sk-test-dummy$'
  guard; echo "red OK"
}

clean() { "${C[@]}" --profile probes down -v --remove-orphans; }

case "${1:-}" in
  static) static_checks ;;
  stack) stack ;;
  persistence) persistence ;;
  network) network ;;
  clean) clean ;;
  *) echo "uso: $0 {static|stack|persistence|network|clean}" >&2; exit 2 ;;
esac
