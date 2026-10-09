import {
  ATTACHMENT_COUNT_MESSAGE, ATTACHMENT_SIZE_MESSAGE, ATTACHMENT_TYPE_MESSAGE, DESCRIPTION_MESSAGE, MAX_ATTACHMENTS,
  MAX_ATTACHMENT_BYTES, MAX_DESCRIPTION, defaultForm, sessionFormData, validateForm,
} from "./estimationForm";

const valid = { ...defaultForm(), description: "Portal de clientes para consultar facturas y abrir incidencias." };
const pdf = new File(["%PDF"], "requisitos.pdf");
const docx = new File(["PK"], "ALCANCE.DOCX");

describe("adjuntos y envío de sesión", () => {
  test("el formulario por defecto no tiene adjuntos", () => {
    expect(defaultForm().attachments).toEqual([]);
  });

  test("los adjuntos válidos no producen errores y permiten un mensaje corto", () => {
    expect(validateForm({ ...valid, description: "Revisa", attachments: [pdf, docx] })).toEqual([]);
    expect(validateForm({ ...valid, description: "", attachments: [pdf] })).toEqual([]);
  });

  test("sin adjuntos el mensaje corto sigue siendo inválido y el largo lo es siempre", () => {
    expect(validateForm({ ...valid, description: "Revisa" })).toEqual([DESCRIPTION_MESSAGE]);
    expect(validateForm({ ...valid, description: "x".repeat(MAX_DESCRIPTION + 1), attachments: [pdf] })).toEqual([DESCRIPTION_MESSAGE]);
  });

  test("rechaza tipo, tamaño y cantidad de adjuntos con mensajes en español", () => {
    expect(validateForm({ ...valid, attachments: [new File(["x"], "notas.txt")] })).toEqual([ATTACHMENT_TYPE_MESSAGE]);
    expect(validateForm({ ...valid, attachments: [new File([new Uint8Array(MAX_ATTACHMENT_BYTES + 1)], "a.pdf")] })).toEqual([ATTACHMENT_SIZE_MESSAGE]);
    expect(validateForm({ ...valid, attachments: Array.from({ length: MAX_ATTACHMENTS + 1 }, () => pdf) })).toEqual([ATTACHMENT_COUNT_MESSAGE]);
  });

  test("sessionFormData incluye transcripción recortada, opciones y todos los adjuntos en orden", () => {
    const data = sessionFormData({ ...valid, description: `  ${valid.description}  `, project_type: "web_saas", attachments: [pdf, docx] });

    expect(Object.fromEntries([...data.entries()].filter(([key]) => key !== "attachments"))).toEqual({
      transcript: valid.description, project_type: "web_saas", detail_level: "medium", output_format: "phases_table", prompt_version: "v3",
    });
    expect(data.getAll("attachments").map((file) => (file as File).name)).toEqual(["requisitos.pdf", "ALCANCE.DOCX"]);
  });
});
