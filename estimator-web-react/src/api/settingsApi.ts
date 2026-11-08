// Ajustes de IA: modelos del LLM en tiempo de ejecución y modelo primario vigente.

import { EstimatorApiError, INVALID_RESPONSE_MESSAGE, isObject, request } from "./estimatorApi";
import type { AiSettings } from "./types";

function expectSettings(body: unknown): AiSettings {
  if (!isObject(body) || !Array.isArray(body.models) || !Array.isArray(body.available_models)) {
    throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  }
  return body as unknown as AiSettings;
}

export async function getSettings(): Promise<AiSettings> {
  return expectSettings(await request("/api/ai-settings", { detail: true }));
}

/** Guarda todos los knobs del formulario: un valor vacío restablece el modelo por defecto (viaja como `null`). */
export async function saveSettings(models: Record<string, string>): Promise<AiSettings> {
  const payload = Object.fromEntries(Object.entries(models).map(([key, value]) => [key, value === "" ? null : value]));
  return expectSettings(await request("/api/ai-settings", { method: "PUT", body: { models: payload }, detail: true }));
}

/** Modelo primario vigente; vacío si el backend o el servicio no responden (el indicador se omite). */
export async function getPrimaryModel(): Promise<string> {
  try {
    const body = await request("/api/primary-model");
    return isObject(body) && typeof body.primary_model === "string" ? body.primary_model : "";
  } catch {
    return "";
  }
}
