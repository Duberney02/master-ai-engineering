package estimation

import (
	"strings"
	"testing"
)

func form(overrides Params) *Form {
	params := Params{"description": "Portal de clientes para consultar facturas."}
	for key, value := range overrides {
		params[key] = value
	}
	return FromParams(params)
}

func txt(content, name string) *File {
	return &File{Filename: name, ContentType: "text/plain", Data: []byte(content)}
}

func attachment(name string, size int) File {
	return File{Filename: name, ContentType: "application/octet-stream", Data: make([]byte, size)}
}

func has(form *Form, message string) bool {
	for _, got := range form.Errors {
		if got == message {
			return true
		}
	}
	return false
}

func TestAValidFormPassesAndExposesTheAPIAttributes(t *testing.T) {
	subject := form(nil)
	if !subject.Valid() {
		t.Fatalf("debería ser válido: %v", subject.Errors)
	}
	attributes := subject.APIAttributes()
	if len(attributes) != 4 || attributes["prompt_version"] != "" {
		t.Errorf("atributos de la API: %v", attributes)
	}
}

func TestDefaultsWhenFieldsAreMissing(t *testing.T) {
	subject := FromParams(Params{})
	if subject.ProjectType != "mobile_app" || subject.DetailLevel != "medium" || subject.OutputFormat != "phases_table" || subject.PromptVersion != "v3" {
		t.Errorf("valores por defecto: %+v", subject)
	}
}

func TestDescriptionLengthLimitsAre20And80000(t *testing.T) {
	for _, length := range []int{19, 80_001} {
		subject := form(Params{"description": strings.Repeat("x", length)})
		if subject.Valid() || !has(subject, "La descripción debe tener entre 20 y 80000 caracteres.") {
			t.Errorf("%d caracteres debería ser inválido", length)
		}
	}
	for _, length := range []int{20, 80_000} {
		if !form(Params{"description": strings.Repeat("x", length)}).Valid() {
			t.Errorf("%d caracteres debería ser válido", length)
		}
	}
}

func TestLengthCountsCharactersNotBytes(t *testing.T) {
	if !form(Params{"description": strings.Repeat("ñ", 20)}).Valid() {
		t.Error("20 caracteres con tilde son válidos aunque ocupen 40 bytes")
	}
}

func TestTheDescriptionIsStrippedBeforeValidating(t *testing.T) {
	if form(Params{"description": "   corta   "}).Valid() {
		t.Error("la descripción recortada es demasiado corta")
	}
	if got := form(Params{"description": "  texto  "}).Description; got != "texto" {
		t.Errorf("descripción: %q", got)
	}
}

func TestEnumsAreValidated(t *testing.T) {
	for _, field := range []string{"project_type", "detail_level", "output_format", "prompt_version"} {
		if form(Params{field: "inventado"}).Valid() {
			t.Errorf("%s debería validarse", field)
		}
	}
}

func TestErrorsComeInTheOrderOfTheValidations(t *testing.T) {
	subject := form(Params{"project_type": "x", "description": "corta", "prompt_version": "v9"})
	subject.Valid()
	want := []string{"El tipo de proyecto no es válido.", "La versión del prompt no es válida.", DescriptionMessage}
	if strings.Join(subject.Errors, "|") != strings.Join(want, "|") {
		t.Errorf("errores: %v", subject.Errors)
	}
}

func TestATxtUploadReplacesTheDescription(t *testing.T) {
	subject := form(Params{"description": "se sustituye"})
	if !subject.LoadUpload(txt("Contenido de la transcripción de la reunión.", "reunion.txt")) || subject.Description != "Contenido de la transcripción de la reunión." || !subject.Valid() {
		t.Errorf("descripción: %q errores %v", subject.Description, subject.Errors)
	}
}

func TestAnUploadStripsTheUTF8BOMAndKeepsAccents(t *testing.T) {
	subject := form(nil)
	subject.LoadUpload(txt("\xef\xbb\xbfReunión: añadir facturación al portal de clientes", "r.txt"))
	if subject.Description != "Reunión: añadir facturación al portal de clientes" {
		t.Errorf("descripción: %q", subject.Description)
	}
}

func TestNoUploadKeepsTheTypedDescription(t *testing.T) {
	subject := form(nil)
	if !subject.LoadUpload(nil) || !subject.LoadUpload(&File{}) || subject.Description != "Portal de clientes para consultar facturas." {
		t.Error("sin archivo se conserva lo escrito")
	}
}

func TestInvalidUploadsAreRejectedAndKeepTheDescription(t *testing.T) {
	cases := []struct {
		file    *File
		message string
	}{
		{txt(strings.Repeat("a", 50), "reunion.pdf"), "El archivo debe ser de texto plano (.txt)."},
		{txt("Reuni\xf3n de planificaci\xf3n", "r.txt"), "El archivo debe estar codificado en UTF-8."},
		{txt(strings.Repeat("a", MaxUploadBytes+1), "r.txt"), "El archivo supera el máximo de 400 KB."},
	}
	for _, tc := range cases {
		subject := form(nil)
		if subject.LoadUpload(tc.file) || !has(subject, tc.message) || subject.Description != "Portal de clientes para consultar facturas." {
			t.Errorf("%q: %v", tc.message, subject.Errors)
		}
	}
}

func TestTheExtensionCheckIsCaseInsensitive(t *testing.T) {
	if !form(nil).LoadUpload(txt(strings.Repeat("a", 50), "REUNION.TXT")) {
		t.Error(".TXT debe aceptarse")
	}
	if form(nil).LoadUpload(txt("x", ".txt")) {
		t.Error("un archivo llamado «.txt» no tiene extensión (como File.extname)")
	}
}

func TestValidAttachmentsAreKeptInOrder(t *testing.T) {
	subject := form(nil)
	if !subject.LoadAttachments([]File{attachment("requisitos.pdf", 10), attachment("ALCANCE.DOCX", 10)}) ||
		len(subject.Attachments) != 2 || subject.Attachments[1].Filename != "ALCANCE.DOCX" || len(subject.Errors) != 0 {
		t.Errorf("adjuntos: %+v %v", subject.Attachments, subject.Errors)
	}
}

func TestEmptyAttachmentPartsAreIgnored(t *testing.T) {
	subject := form(nil)
	if !subject.LoadAttachments([]File{{}}) || !subject.LoadAttachments(nil) || len(subject.Attachments) != 0 {
		t.Error("un navegador sin archivo elegido envía una parte vacía")
	}
}

func TestInvalidAttachmentsAreRejected(t *testing.T) {
	cases := []struct {
		files   []File
		message string
	}{
		{[]File{attachment("notas.txt", 10)}, AttachmentTypeMessage},
		{[]File{attachment("grande.pdf", MaxAttachmentBytes+1)}, AttachmentSizeMessage},
		{[]File{attachment("0.pdf", 1), attachment("1.pdf", 1), attachment("2.pdf", 1), attachment("3.pdf", 1), attachment("4.pdf", 1), attachment("5.pdf", 1)}, AttachmentCountMessage},
	}
	for _, tc := range cases {
		subject := form(nil)
		if subject.LoadAttachments(tc.files) || len(subject.Errors) != 1 || subject.Errors[0] != tc.message || len(subject.Attachments) != 0 {
			t.Errorf("%q: %v", tc.message, subject.Errors)
		}
	}
}

func TestAShortMessageIsValidWithAttachmentsButNotWithoutThem(t *testing.T) {
	if form(Params{"description": "Revisa"}).Valid() {
		t.Error("sin adjuntos, 6 caracteres no bastan")
	}
	withFiles := form(Params{"description": "Revisa"})
	withFiles.LoadAttachments([]File{attachment("req.pdf", 1)})
	if !withFiles.Valid() {
		t.Errorf("con adjuntos basta: %v", withFiles.Errors)
	}
	tooLong := form(Params{"description": strings.Repeat("x", 80_001)})
	tooLong.LoadAttachments([]File{attachment("req.pdf", 1)})
	if tooLong.Valid() {
		t.Error("el máximo se aplica siempre")
	}
}

func TestSessionFieldsCarryTheTranscriptAndTheOptions(t *testing.T) {
	fields := form(nil).SessionFields()
	want := [][2]string{
		{"transcript", "Portal de clientes para consultar facturas."}, {"project_type", "mobile_app"}, {"detail_level", "medium"},
		{"output_format", "phases_table"}, {"prompt_version", "v3"},
	}
	for index := range want {
		if fields[index] != want[index] {
			t.Errorf("campo %d: %v", index, fields[index])
		}
	}
}
