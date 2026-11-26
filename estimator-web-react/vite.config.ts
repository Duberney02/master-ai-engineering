/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/** Plazo en segundos desde el entorno; un valor inválido impide arrancar el servidor de desarrollo. */
function seconds(env: Record<string, string>, name: string, fallback: number): number {
  const raw = env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) throw new Error(`${name} debe ser un número positivo de segundos (recibido «${raw}»)`);
  return value;
}

// En desarrollo, Vite hace de proxy de Go (DA-03: React solo habla con Go) para que el navegador use únicamente su
// origen, igual que nginx: sin CORS y sin exponer la dirección del backend. Usa los mismos plazos que nginx, con margen
// sobre los de Go (30 s habituales, 600 s largas y SSE) para que llegue su error saneado.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.ESTIMATOR_WEB_URL || "http://localhost:3000";
  const connect = seconds(env, "VITE_CONNECT_TIMEOUT", 5);
  const regular = seconds(env, "VITE_REGULAR_TIMEOUT", 35);
  const long = seconds(env, "VITE_LONG_TIMEOUT", 615);
  if (connect > regular || regular >= long) {
    throw new Error(`Plazos incoherentes: conexión=${connect} s, habitual=${regular} s, largo=${long} s (se exige conexión ≤ habitual < largo)`);
  }
  const proxy = (timeout: number) => ({ target, changeOrigin: false, timeout: timeout * 1000, proxyTimeout: timeout * 1000 });
  return {
    plugins: [react()],
    server: {
      // Vite aplica la primera regla que coincide: las rutas largas y SSE van antes que el resto de /api.
      proxy: {
        "^/api/v1/(estimate|estimate/stream|sessions/[^/]+/estimate|transcription/estimate/stream|rag/chunking-comparisons)$": proxy(long),
        "/api": proxy(regular),
        "/health": proxy(regular),
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
    },
  };
});
