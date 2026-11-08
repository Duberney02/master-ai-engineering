/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, Vite hace de proxy del backend Go para que el navegador hable solo con su origen
// (igual que nginx en producción): sin CORS y sin exponer la URL de la API.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.ESTIMATOR_WEB_URL || "http://localhost:3000";
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": { target, changeOrigin: true, timeout: 600_000, proxyTimeout: 600_000 },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
    },
  };
});
