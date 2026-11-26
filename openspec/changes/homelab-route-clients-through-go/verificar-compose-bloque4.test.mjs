// Autopruebas del comprobador: una configuración válida y mutaciones que deben detectarse.
//   node --test openspec/changes/homelab-route-clients-through-go/verificar-compose-bloque4.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { validar, REDES } from "./verificar-compose-bloque4.mjs";

const sonda = (t) => ({ test: t });
const depende = (...n) => Object.fromEntries(n.map((x) => [x, { condition: "service_healthy" }]));
function base() {
  const redesDe = (s) => Object.fromEntries(Object.entries(REDES).filter(([, v]) => v.miembros.includes(s)).map(([k]) => [k, null]));
  return {
    services: {
      "estimador-cag": {
        networks: redesDe("estimador-cag"), env_file: [{ path: "x" }], depends_on: depende("redis", "postgres"),
        environment: { REDIS_URL: "redis://redis:6379/0", DATABASE_URL: "postgresql+asyncpg://u:p@postgres:5432/estimator" },
        healthcheck: sonda(["CMD", "python", "-c", "urlopen('http://127.0.0.1:8000/health')"]),
      },
      "estimator-web": {
        networks: redesDe("estimator-web"), depends_on: depende("estimador-cag", "estimator-web-db"),
        environment: { ESTIMATOR_API_URL: "http://estimador-cag:8000", DATABASE_URL: "postgres://u:p@estimator-web-db:5432/estimator_web" },
        healthcheck: sonda(["CMD", "/estimator-web", "healthcheck"]),
      },
      "estimator-web-db": { networks: redesDe("estimator-web-db"), volumes: [{ type: "volume", source: "estimator_web_db_data" }], healthcheck: sonda(["CMD-SHELL", "pg_isready"]) },
      "estimator-web-react": {
        networks: redesDe("estimator-web-react"), depends_on: depende("estimator-web"), environment: { API_UPSTREAM: "http://estimator-web:3000" },
        ports: [{ host_ip: "127.0.0.1", published: "3001", target: 8080, protocol: "tcp" }],
        healthcheck: sonda(["CMD", "wget", "http://127.0.0.1:8080/healthz"]),
      },
      redis: { networks: redesDe("redis"), volumes: [{ type: "volume", source: "redis_data" }], healthcheck: sonda(["CMD", "redis-cli", "ping"]) },
      postgres: { networks: redesDe("postgres"), volumes: [{ type: "volume", source: "postgres_data" }], healthcheck: sonda(["CMD-SHELL", "pg_isready"]) },
    },
    networks: Object.fromEntries(Object.entries(REDES).map(([k, v]) => [k, v.internal ? { internal: true } : {}])),
    volumes: { postgres_data: {}, redis_data: {}, estimator_web_db_data: {} },
  };
}
const mutar = (fn) => { const c = base(); fn(c); return validar(c); };
const detecta = (nombre, fn, patron) => test(`detecta: ${nombre}`, () => assert.match(mutar(fn).join("\n"), patron));

test("configuración válida", () => assert.deepEqual(validar(base()), []));
detecta("publicación en todas las interfaces", (c) => { c.services["estimator-web-react"].ports[0].host_ip = "0.0.0.0"; }, /loopback|127\.0\.0\.1:3001/);
detecta("publicación sin enlace (IPv6/todas)", (c) => { delete c.services["estimator-web-react"].ports[0].host_ip; }, /127\.0\.0\.1:3001/);
detecta("puerto publicado en IA", (c) => { c.services["estimador-cag"].ports = [{ host_ip: "127.0.0.1", published: "8000", target: 8000 }]; }, /estimador-cag: no debe publicar/);
detecta("puerto publicado en PostgreSQL", (c) => { c.services.postgres.ports = [{ host_ip: "127.0.0.1", published: "5432", target: 5432 }]; }, /postgres: no debe publicar/);
detecta("servicio Streamlit", (c) => { c.services["estimador-cag-chat"] = { command: ["streamlit", "run"], healthcheck: sonda(["CMD", "x"]) }; }, /servicios:|Streamlit/);
detecta("React en red de IA", (c) => { c.services["estimator-web-react"].networks["ai-data-net"] = null; }, /ai-data-net: miembros/);
detecta("red de datos no interna", (c) => { c.networks["ai-data-net"] = {}; }, /ai-data-net: internal/);
detecta("salida de IA compartida", (c) => { c.services["estimator-web"].networks["ai-egress-net"] = null; }, /ai-egress-net: miembros/);
detecta("clave de proveedor en Go", (c) => { c.services["estimator-web"].environment.OPENAI_API_KEY = "sk-x"; }, /estimator-web: variables de proveedor/);
detecta("env_file en React", (c) => { c.services["estimator-web-react"].env_file = [{ path: "x" }]; }, /env_file/);
detecta("container_name explícito", (c) => { c.services.redis.container_name = "redis"; }, /container_name/);
detecta("ruta al host", (c) => { c.services["estimator-web-react"].extra_hosts = ["host.docker.internal:host-gateway"]; }, /extra_hosts|host\.docker\.internal/);
detecta("sin healthcheck", (c) => { delete c.services.redis.healthcheck; }, /redis: sin healthcheck/);
detecta("dependencia sin espera de salud", (c) => { c.services["estimator-web"].depends_on["estimador-cag"].condition = "service_started"; }, /debe esperar a estimador-cag/);
detecta("volumen externo", (c) => { c.volumes.postgres_data = { external: true }; }, /no puede ser externo/);
detecta("Go apunta a la base de IA", (c) => { c.services["estimator-web"].environment.DATABASE_URL = "postgres://u:p@postgres:5432/estimator"; }, /estimator-web-db\/estimator_web/);
test("detecta contraseña sin parametrizar en el origen", () => {
  assert.match(validar(base(), "      POSTGRES_PASSWORD: secreto\n").join("\n"), /sin parametrizar/);
  assert.deepEqual(validar(base(), "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-dev}\n"), []);
});
