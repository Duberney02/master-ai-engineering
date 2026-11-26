import config from "../../vite.config";

// El proxy de desarrollo hace de nginx: destino Go y plazos coordinados (35 s / 615 s sobre los 30 s / 600 s de Go).
type Rule = { target: string; timeout: number; proxyTimeout: number; changeOrigin: boolean };
type Resolved = { server: { proxy: Record<string, Rule> } };

function resolve(env: Record<string, string> = {}): Resolved {
  const previous = { ...process.env };
  Object.assign(process.env, env);
  try {
    return (config as unknown as (env: { mode: string; command: string }) => Resolved)({ mode: "test", command: "serve" });
  } finally {
    for (const key of Object.keys(env)) {
      if (previous[key] === undefined) delete process.env[key];
      else process.env[key] = previous[key];
    }
  }
}

describe("proxy de desarrollo de Vite", () => {
  test("apunta a Go por defecto, no a la API de IA, con las rutas largas antes que el resto", () => {
    const rules = resolve().server.proxy;
    const keys = Object.keys(rules);
    expect(keys[keys.length - 2]).toBe("/api");
    expect(keys[0]).toContain("estimate/stream");
    expect(keys[0]).toContain("transcription/estimate/stream");
    expect(keys[0]).toContain("rag/chunking-comparisons");
    for (const rule of Object.values(rules)) {
      expect(rule.target).toBe("http://localhost:3000");
      expect(rule.target).not.toContain("8000");
      expect(rule.changeOrigin).toBe(false); // conserva el Host del navegador para la validación de origen de Go
    }
    expect(rules[keys[0]].timeout).toBe(615_000);
    expect(rules[keys[0]].proxyTimeout).toBe(615_000);
    expect(rules["/api"].timeout).toBe(35_000);
    expect(rules["/health"].timeout).toBe(35_000);
  });

  test("las rutas largas coinciden exactamente con las operaciones largas y SSE", () => {
    const [pattern] = Object.keys(resolve().server.proxy);
    const regex = new RegExp(pattern);
    for (const path of [
      "/api/v1/estimate", "/api/v1/estimate/stream", "/api/v1/transcription/estimate/stream",
      "/api/v1/sessions/6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10/estimate", "/api/v1/rag/chunking-comparisons",
    ]) expect(regex.test(path), path).toBe(true);
    for (const path of ["/api/v1/estimations", "/api/v1/estimations/7", "/api/v1/prompts/estimation", "/api/v1/sessions",
      "/api/v1/ai/settings", "/api/v1/ai/primary-model", "/api/v1/rag/chunking-comparisons/7", "/api/v1/rag/chunking-comparisons/options",
    ]) expect(regex.test(path), path).toBe(false);
  });

  test("el destino y los plazos son configurables", () => {
    const rules = resolve({ ESTIMATOR_WEB_URL: "http://estimator-web:3000", VITE_REGULAR_TIMEOUT: "10", VITE_LONG_TIMEOUT: "20", VITE_CONNECT_TIMEOUT: "2" }).server.proxy;
    expect(rules["/api"].target).toBe("http://estimator-web:3000");
    expect(rules["/api"].timeout).toBe(10_000);
    expect(rules[Object.keys(rules)[0]].timeout).toBe(20_000);
  });

  test.each([
    [{ VITE_REGULAR_TIMEOUT: "abc" }, "número positivo"],
    [{ VITE_LONG_TIMEOUT: "0" }, "número positivo"],
    [{ VITE_REGULAR_TIMEOUT: "50", VITE_LONG_TIMEOUT: "40" }, "incoherentes"],
    [{ VITE_CONNECT_TIMEOUT: "60" }, "incoherentes"],
  ])("rechaza plazos inválidos o incoherentes %j", (env, message) => {
    expect(() => resolve(env)).toThrow(message);
  });
});
