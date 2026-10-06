import {
  DESCRIPTION_MESSAGE, MAX_DESCRIPTION, NOT_TXT_MESSAGE, NOT_UTF8_MESSAGE, TOO_BIG_MESSAGE,
  apiAttributes, defaultForm, readTxtFile, validateForm,
} from "./estimationForm";

const valid = { ...defaultForm(), description: "Portal de clientes para consultar facturas y abrir incidencias." };

function file(content: BlobPart, name = "reunion.txt") {
  return new File([content], name, { type: "text/plain" });
}

describe("validateForm", () => {
  test("acepta un formulario válido", () => {
    expect(validateForm(valid)).toEqual([]);
  });

  test("valores por defecto", () => {
    expect(defaultForm()).toMatchObject({ project_type: "mobile_app", detail_level: "medium", output_format: "phases_table", prompt_version: "v3" });
  });

  test("rechaza descripciones demasiado cortas o largas con el mensaje exacto", () => {
    expect(DESCRIPTION_MESSAGE).toBe("La descripción debe tener entre 20 y 80000 caracteres.");
    expect(validateForm({ ...valid, description: "corta" })).toEqual([DESCRIPTION_MESSAGE]);
    expect(validateForm({ ...valid, description: "x".repeat(MAX_DESCRIPTION + 1) })).toEqual([DESCRIPTION_MESSAGE]);
    expect(validateForm({ ...valid, description: "x".repeat(MAX_DESCRIPTION) })).toEqual([]);
  });

  test("recorta espacios antes de medir", () => {
    expect(validateForm({ ...valid, description: `   ${"a".repeat(19)}   ` })).toEqual([DESCRIPTION_MESSAGE]);
  });

  test("rechaza opciones fuera de catálogo", () => {
    const errors = validateForm({ ...valid, project_type: "x", detail_level: "x", output_format: "x", prompt_version: "x" });
    expect(errors).toEqual([
      "El tipo de proyecto no es válido.",
      "El nivel de detalle no es válido.",
      "El formato de salida no es válido.",
      "La versión del prompt no es válida.",
    ]);
  });

  test("apiAttributes omite la versión del prompt y recorta la descripción", () => {
    const attrs = apiAttributes({ ...valid, description: `  ${valid.description}  ` });
    expect(Object.keys(attrs)).toEqual(["description", "project_type", "detail_level", "output_format"]);
    expect(attrs.description).toBe(valid.description);
  });
});

describe("readTxtFile", () => {
  test("lee un .txt UTF-8 y quita el BOM", async () => {
    expect(await readTxtFile(file("﻿hola ñandú"))).toEqual({ ok: true, text: "hola ñandú" });
  });

  test("rechaza extensiones distintas de .txt", async () => {
    expect(await readTxtFile(file("hola", "reunion.pdf"))).toEqual({ ok: false, error: NOT_TXT_MESSAGE });
  });

  test("rechaza archivos de más de 400 000 bytes", async () => {
    expect(TOO_BIG_MESSAGE).toBe("El archivo supera el máximo de 400 KB.");
    expect(await readTxtFile(file("a".repeat(400_001)))).toEqual({ ok: false, error: TOO_BIG_MESSAGE });
    expect((await readTxtFile(file("a".repeat(400_000)))).ok).toBe(true);
  });

  test("rechaza contenido que no es UTF-8", async () => {
    expect(await readTxtFile(file(new Uint8Array([0xff, 0xfe, 0xfa])))).toEqual({ ok: false, error: NOT_UTF8_MESSAGE });
  });
});
