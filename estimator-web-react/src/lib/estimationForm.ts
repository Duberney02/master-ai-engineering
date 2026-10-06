// Equivalente de EstimationForm (Rails): constantes, validación y lectura del .txt.

export const MIN_DESCRIPTION = 20;
export const MAX_DESCRIPTION = 80_000;
// 80 000 caracteres ocupan como mucho ~320 KB en UTF-8.
export const MAX_UPLOAD_BYTES = 400_000;

export const PROJECT_TYPES = ["mobile_app", "web_saas", "internal_tool", "data_pipeline"] as const;
export const DETAIL_LEVELS = ["summary", "medium", "detailed"] as const;
export const OUTPUT_FORMATS = ["phases_table", "line_items", "narrative"] as const;
export const PROMPT_VERSIONS = ["v3", "v1", "v2"] as const;

export interface FormValues {
  description: string;
  project_type: string;
  detail_level: string;
  output_format: string;
  prompt_version: string;
}

export const DESCRIPTION_MESSAGE = `La descripción debe tener entre ${MIN_DESCRIPTION} y ${MAX_DESCRIPTION} caracteres.`;
export const NOT_TXT_MESSAGE = "El archivo debe ser de texto plano (.txt).";
export const TOO_BIG_MESSAGE = `El archivo supera el máximo de ${MAX_UPLOAD_BYTES / 1000} KB.`;
export const NOT_UTF8_MESSAGE = "El archivo debe estar codificado en UTF-8.";

export function defaultForm(): FormValues {
  return {
    description: "",
    project_type: PROJECT_TYPES[0],
    detail_level: "medium",
    output_format: OUTPUT_FORMATS[0],
    prompt_version: PROMPT_VERSIONS[0],
  };
}

/** Opciones que se envían a la API (sin la versión del prompt, que va como parámetro de consulta). */
export function apiAttributes(form: FormValues) {
  return {
    description: form.description.trim(),
    project_type: form.project_type,
    detail_level: form.detail_level,
    output_format: form.output_format,
  };
}

/** Devuelve la lista de mensajes de error (vacía si el formulario es válido). */
export function validateForm(form: FormValues): string[] {
  const errors: string[] = [];
  if (!(PROJECT_TYPES as readonly string[]).includes(form.project_type)) errors.push("El tipo de proyecto no es válido.");
  if (!(DETAIL_LEVELS as readonly string[]).includes(form.detail_level)) errors.push("El nivel de detalle no es válido.");
  if (!(OUTPUT_FORMATS as readonly string[]).includes(form.output_format)) errors.push("El formato de salida no es válido.");
  if (!(PROMPT_VERSIONS as readonly string[]).includes(form.prompt_version)) errors.push("La versión del prompt no es válida.");
  const length = Array.from(form.description.trim()).length;
  if (length < MIN_DESCRIPTION || length > MAX_DESCRIPTION) errors.push(DESCRIPTION_MESSAGE);
  return errors;
}

export type TxtResult = { ok: true; text: string } | { ok: false; error: string };

/** Valida extensión, tamaño y UTF-8 estricto (quita el BOM) antes de usar el contenido como descripción. */
export async function readTxtFile(file: File): Promise<TxtResult> {
  if (!/\.txt$/i.test(file.name)) return { ok: false, error: NOT_TXT_MESSAGE };
  if (file.size > MAX_UPLOAD_BYTES) return { ok: false, error: TOO_BIG_MESSAGE };
  try {
    const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer());
    return { ok: true, text: text.replace(/^﻿/, "") };
  } catch {
    return { ok: false, error: NOT_UTF8_MESSAGE };
  }
}
