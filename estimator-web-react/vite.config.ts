/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, Vite hace de proxy de la API para que el navegador hable solo con su origen
// (igual que nginx en producción): sin CORS y sin exponer la URL de la API.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.ESTIMATOR_API_URL || "http://localhost:8000";
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": { target, changeOrigin: true, timeout: 300_000, proxyTimeout: 300_000 },
        "/health": { target, changeOrigin: true },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
    },
  };
});
