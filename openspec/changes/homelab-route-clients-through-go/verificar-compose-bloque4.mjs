// Comprobador estático de la topología del Compose raíz (tareas 12.1, 13.1 y 13.2).
// Entrada: salida de `docker compose config --format json` con valores ficticios y, opcionalmente, el YAML de origen.
//   docker compose --env-file /dev/null -p hl-s1 config --format json > cfg.json
//   node verificar-compose-bloque4.mjs cfg.json ../../../docker-compose.yml
// Sin dependencias: se ejecuta en la imagen de Node de los servicios de verificación.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const SERVICIOS = ["estimador-cag", "estimator-web", "estimator-web-db", "estimator-web-react", "redis", "postgres"];

export const REDES = {
  "client-net": { internal: false, miembros: ["estimator-web", "estimator-web-react"] },
  "service-net": { internal: true, miembros: ["estimador-cag", "estimator-web"] },
  "go-data-net": { internal: true, miembros: ["estimator-web", "estimator-web-db"] },
  "ai-data-net": { internal: true, miembros: ["estimador-cag", "postgres", "redis"] },
  "ai-egress-net": { internal: false, miembros: ["estimador-cag"] },
};

const DEPENDENCIAS = {
  "estimador-cag": ["redis", "postgres"],
  "estimator-web": ["estimador-cag", "estimator-web-db"],
  "estimator-web-react": ["estimator-web"],
};

const SONDAS = {
  postgres: /pg_isready/,
  "estimator-web-db": /pg_isready/,
  redis: /redis-cli.*ping|ping/,
  "estimator-web": /estimator-web.*healthcheck/,
  "estimator-web-react": /127\.0\.0\.1:8080\/healthz/,
  "estimador-cag": /127\.0\.0\.1:8000\/health/,
};

const CLAVE_PROVEEDOR = /(OPENAI|ANTHROPIC|COHERE|GOOGLE|AZURE|MISTRAL|OLLAMA).*(KEY|TOKEN|SECRET)|^[A-Z_]*API_KEY$/;

function envDe(servicio) {
  const e = servicio.environment ?? {};
  return Array.isArray(e) ? Object.fromEntries(e.map((l) => l.split(/=(.*)/s).slice(0, 2))) : e;
}

function redesDe(servicio) {
  const n = servicio.networks ?? {};
  return Array.isArray(n) ? n : Object.keys(n);
}

export function validar(config, fuente = null) {
  const fallos = [];
  const f = (m) => fallos.push(m);
  const servicios = config.services ?? {};
  const nombres = Object.keys(servicios).sort();

  if (JSON.stringify(nombres) !== JSON.stringify([...SERVICIOS].sort())) {
    f(`servicios: se esperaban ${SERVICIOS.join(", ")} y hay ${nombres.join(", ")}`);
  }
  for (const [n, s] of Object.entries(servicios)) {
    const texto = JSON.stringify([n, s.image, s.command, s.entrypoint]).toLowerCase();
    if (/streamlit|rails|puma/.test(texto)) f(`${n}: referencia a Streamlit o Rails`);
    if (s.container_name) f(`${n}: container_name explícito (${s.container_name}) rompe el aislamiento por proyecto`);
    if (s.network_mode) f(`${n}: network_mode ${s.network_mode} no permitido`);
    if (s.privileged) f(`${n}: privileged no permitido`);
    if ((s.extra_hosts ?? []).length) f(`${n}: extra_hosts abre una ruta al host`);
    if (JSON.stringify(s).includes("host.docker.internal") || JSON.stringify(s).includes("host-gateway")) {
      f(`${n}: referencia a host.docker.internal o host-gateway`);
    }
    if (!s.healthcheck?.test) f(`${n}: sin healthcheck`);
    else if (SONDAS[n] && !SONDAS[n].test(JSON.stringify(s.healthcheck.test))) f(`${n}: sonda inesperada ${JSON.stringify(s.healthcheck.test)}`);
  }

  // Redes
  const redes = config.networks ?? {};
  for (const [red, esperado] of Object.entries(REDES)) {
    if (!redes[red]) { f(`red ${red} no definida`); continue; }
    if (Boolean(redes[red].internal) !== esperado.internal) f(`red ${red}: internal debe ser ${esperado.internal}`);
    if (redes[red].external) f(`red ${red}: no puede ser externa`);
    if (redes[red].enable_ipv6) f(`red ${red}: IPv6 habilitado`);
    const reales = nombres.filter((n) => redesDe(servicios[n]).includes(red)).sort();
    if (JSON.stringify(reales) !== JSON.stringify([...esperado.miembros].sort())) {
      f(`red ${red}: miembros ${reales.join(", ") || "(ninguno)"}; se esperaban ${esperado.miembros.join(", ")}`);
    }
  }
  for (const r of Object.keys(redes)) if (!REDES[r]) f(`red inesperada ${r}`);
  for (const n of nombres) {
    for (const r of redesDe(servicios[n])) if (!REDES[r]) f(`${n}: red inesperada ${r} (¿default?)`);
  }

  // Publicaciones
  for (const n of nombres) {
    const puertos = servicios[n].ports ?? [];
    if (n === "estimator-web-react") {
      const ok = puertos.length === 1 && puertos[0].host_ip === "127.0.0.1" && String(puertos[0].published) === "3001" && Number(puertos[0].target) === 8080 && (puertos[0].protocol ?? "tcp") === "tcp";
      if (!ok) f(`estimator-web-react debe publicar solo 127.0.0.1:3001->8080/tcp (hay ${JSON.stringify(puertos)})`);
    } else if (puertos.length) {
      f(`${n}: no debe publicar puertos (hay ${JSON.stringify(puertos)})`);
    }
    for (const p of puertos) if (!p.host_ip || /^(0\.0\.0\.0|::|\[::\])$/.test(p.host_ip)) f(`${n}: publicación sin enlace a loopback`);
    if (servicios[n].expose?.length && n !== "estimador-cag") { /* expose es solo documental */ }
  }

  // Orden de arranque
  for (const [n, deps] of Object.entries(DEPENDENCIAS)) {
    const d = servicios[n]?.depends_on ?? {};
    const mapa = Array.isArray(d) ? Object.fromEntries(d.map((x) => [x, {}])) : d;
    for (const dep of deps) if (mapa[dep]?.condition !== "service_healthy") f(`${n}: debe esperar a ${dep} con service_healthy`);
  }

  // Volúmenes con nombre de los almacenes
  const volumenes = {
    postgres: "postgres_data",
    redis: "redis_data",
    "estimator-web-db": "estimator_web_db_data",
  };
  for (const [n, v] of Object.entries(volumenes)) {
    const montajes = servicios[n]?.volumes ?? [];
    if (!montajes.some((m) => m.type === "volume" && m.source === v)) f(`${n}: falta el volumen con nombre ${v}`);
    if (config.volumes && !config.volumes[v]) f(`volumen ${v} no declarado`);
    if (config.volumes?.[v]?.external) f(`volumen ${v}: no puede ser externo (infraestructura preexistente)`);
  }

  // Credenciales: solo estimador-cag
  for (const n of nombres) {
    const claves = Object.keys(envDe(servicios[n])).filter((k) => CLAVE_PROVEEDOR.test(k));
    if (n !== "estimador-cag" && claves.length) f(`${n}: variables de proveedor de IA (${claves.join(", ")})`);
    if (n !== "estimador-cag" && servicios[n].env_file?.length) f(`${n}: env_file solo se admite en estimador-cag`);
  }

  // Cableado interno y bases separadas
  const cag = envDe(servicios["estimador-cag"] ?? {});
  const web = envDe(servicios["estimator-web"] ?? {});
  const react = envDe(servicios["estimator-web-react"] ?? {});
  if (!/^redis:\/\/redis:6379/.test(cag.REDIS_URL ?? "")) f("estimador-cag: REDIS_URL debe apuntar a redis interno");
  if (!/@postgres:5432\/estimator$/.test(cag.DATABASE_URL ?? "")) f("estimador-cag: DATABASE_URL debe apuntar a postgres/estimator");
  if (web.ESTIMATOR_API_URL !== "http://estimador-cag:8000") f("estimator-web: ESTIMATOR_API_URL debe ser http://estimador-cag:8000");
  if (!/@estimator-web-db:5432\/estimator_web$/.test(web.DATABASE_URL ?? "")) f("estimator-web: DATABASE_URL debe apuntar a estimator-web-db/estimator_web");
  if (react.API_UPSTREAM !== "http://estimator-web:3000") f("estimator-web-react: API_UPSTREAM debe apuntar a Go");

  // Contraseñas parametrizadas en el YAML de origen
  if (fuente !== null) {
    for (const linea of fuente.split("\n")) {
      if (/POSTGRES_PASSWORD:|DATABASE_URL:/.test(linea) && !/\$\{[A-Z_]+:-[^}]*\}/.test(linea)) f(`origen: contraseña sin parametrizar -> ${linea.trim()}`);
    }
    if (/sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9]/.test(fuente)) f("origen: aspecto de clave real versionada");
  }
  return fallos;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [cfg, origen] = process.argv.slice(2);
  if (!cfg) { console.error("uso: node verificar-compose-bloque4.mjs <config.json> [docker-compose.yml]"); process.exit(2); }
  const fallos = validar(JSON.parse(readFileSync(cfg, "utf8")), origen ? readFileSync(origen, "utf8") : null);
  console.log(JSON.stringify({ ok: fallos.length === 0, fallos }, null, 2));
  process.exit(fallos.length === 0 ? 0 : 1);
}
