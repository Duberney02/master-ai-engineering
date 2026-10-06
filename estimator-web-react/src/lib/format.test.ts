import {
  cacheSourceLabel, formatCost, formatDecimal, formatInteger, formatTime, formatUsd, formatWeeks,
  labelFor, optionsForLabels, outOfScopeReason, truncate,
} from "./format";

describe("format", () => {
  test("etiquetas", () => {
    expect(labelFor("web_saas")).toBe("SaaS web");
    expect(labelFor("desconocido")).toBe("desconocido");
    expect(labelFor(undefined)).toBe("");
    expect(optionsForLabels(["summary", "x"])).toEqual([
      { label: "Resumen", value: "summary" },
      { label: "x", value: "x" },
    ]);
  });

  test("procedencia", () => {
    expect(cacheSourceLabel("none")).toBe("Generada");
    expect(cacheSourceLabel("exact")).toBe("Caché exacta");
    expect(cacheSourceLabel("semantic")).toBe("Caché semántica");
    expect(cacheSourceLabel("otra")).toBe("Generada");
  });

  test("coste en EUR con miles y coma decimal", () => {
    expect(formatCost(20000)).toBe("20.000,00 EUR");
    expect(formatCost(1234567.5)).toBe("1.234.567,50 EUR");
    expect(formatCost(0)).toBe("0,00 EUR");
    expect(formatCost(999.999)).toBe("1.000,00 EUR");
  });

  test("semanas sin ceros no significativos", () => {
    expect(formatWeeks(1.5)).toBe("1,5 semanas");
    expect(formatWeeks(4)).toBe("4 semanas");
    expect(formatWeeks(12.0)).toBe("12 semanas");
  });

  test("coste en USD", () => {
    expect(formatUsd(0.001234)).toBe("0,001234 USD");
    expect(formatUsd(null)).toBe("Sin tarifa");
    expect(formatUsd(undefined)).toBe("Sin tarifa");
  });

  test("fecha UTC", () => {
    expect(formatTime("2026-05-20T10:05:00Z")).toBe("20/05/2026 10:05 UTC");
    expect(formatTime("2026-05-20T10:05:00+02:00")).toBe("20/05/2026 08:05 UTC");
    expect(formatTime("no es fecha")).toBe("no es fecha");
  });

  test("motivo fuera de alcance", () => {
    expect(outOfScopeReason("Out of scope: falta información")).toBe("falta información");
    expect(outOfScopeReason("Otro texto")).toBe("Otro texto");
  });

  test("enteros con miles y decimales", () => {
    expect(formatInteger(1234567)).toBe("1.234.567");
    expect(formatInteger("80000")).toBe("80.000");
    expect(formatInteger(undefined)).toBe("0");
    expect(formatDecimal(2.0)).toBe("2");
  });

  test("truncado como Rails", () => {
    expect(truncate("abc", 5)).toBe("abc");
    expect(truncate("abcdefghij", 6)).toBe("abc...");
    expect(Array.from(truncate("x".repeat(95), 90))).toHaveLength(90);
  });
});
