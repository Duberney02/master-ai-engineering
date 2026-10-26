// Package estimation contiene el formulario de estimación: valida los campos antes de llamar a la API, carga la
// descripción desde un archivo .txt opcional (que sustituye al texto escrito) y valida los adjuntos PDF/Word cuyo texto
// la API añade a la transcripción.
package estimation

import (
	"fmt"
	"path"
	"slices"
	"strings"
	"unicode/utf8"
)

const (
	MinDescription = 20
	MaxDescription = 80_000
	// MaxUploadBytes: 80 000 caracteres ocupan como mucho ~320 KB en UTF-8.
	MaxUploadBytes = 400_000

	// Adjuntos PDF/Word de la conversación: los mismos límites que aplica la API.
	MaxAttachments     = 5
	MaxAttachmentBytes = 10 * 1024 * 1024
)

var (
	ProjectTypes   = []string{"mobile_app", "web_saas", "internal_tool", "data_pipeline"}
	DetailLevels   = []string{"summary", "medium", "detailed"}
	OutputFormats  = []string{"phases_table", "line_items", "narrative"}
	PromptVersions = []string{"v3", "v1", "v2"}

	attachmentExtensions = []string{".pdf", ".docx"}
)

// Mensajes de validación (los mismos que el cliente Rails).
var (
	DescriptionMessage     = fmt.Sprintf("La descripción debe tener entre %d y %d caracteres.", MinDescription, MaxDescription)
	AttachmentTypeMessage  = "Los adjuntos deben ser PDF (.pdf) o Word (.docx)."
	AttachmentSizeMessage  = fmt.Sprintf("Cada adjunto puede pesar como máximo %d MB.", MaxAttachmentBytes/(1024*1024))
	AttachmentCountMessage = fmt.Sprintf("Se admiten como máximo %d adjuntos.", MaxAttachments)
)

// File es un archivo subido en memoria.
type File struct {
	Filename    string
	ContentType string
	Data        []byte
}

// Size es el tamaño en bytes.
func (f File) Size() int { return len(f.Data) }

// Form es el formulario de estimación.
type Form struct {
	Description   string
	ProjectType   string
	DetailLevel   string
	OutputFormat  string
	PromptVersion string
	Attachments   []File
	// Errors son los mensajes de validación, en el orden en que se produjeron.
	Errors []string
}

// New devuelve el formulario con los valores por defecto.
func New() *Form {
	return &Form{
		ProjectType: ProjectTypes[0], DetailLevel: "medium", OutputFormat: OutputFormats[0], PromptVersion: PromptVersions[0],
	}
}

// Params son los campos de texto enviados (solo los presentes sustituyen al valor por defecto).
type Params map[string]string

// FromParams construye el formulario con los campos presentes; la descripción se recorta.
func FromParams(params Params) *Form {
	form := New()
	if value, ok := params["description"]; ok {
		form.Description = stripRuby(value)
	}
	if value, ok := params["project_type"]; ok {
		form.ProjectType = value
	}
	if value, ok := params["detail_level"]; ok {
		form.DetailLevel = value
	}
	if value, ok := params["output_format"]; ok {
		form.OutputFormat = value
	}
	if value, ok := params["prompt_version"]; ok {
		form.PromptVersion = value
	}
	return form
}

// DescriptionLength cuenta caracteres, no bytes.
func (f *Form) DescriptionLength() int { return utf8.RuneCountInString(f.Description) }

// LoadUpload sustituye la descripción por el contenido del archivo; añade un error y devuelve false si el archivo no
// es un .txt UTF-8 de tamaño admitido. Un archivo nulo no hace nada.
func (f *Form) LoadUpload(file *File) bool {
	if file == nil || (file.Filename == "" && file.Size() == 0) {
		return true
	}
	if !strings.EqualFold(rubyExt(file.Filename), ".txt") {
		return f.addError("El archivo debe ser de texto plano (.txt).")
	}
	if file.Size() > MaxUploadBytes {
		return f.addError(fmt.Sprintf("El archivo supera el máximo de %d KB.", MaxUploadBytes/1000))
	}
	if !utf8.Valid(file.Data) {
		return f.addError("El archivo debe estar codificado en UTF-8.")
	}
	f.Description = stripRuby(strings.TrimPrefix(string(file.Data), "\xef\xbb\xbf"))
	return true
}

// LoadAttachments valida y guarda los adjuntos elegidos. Añade un error y devuelve false si alguno no es PDF/Word,
// pesa demasiado o hay demasiados.
func (f *Form) LoadAttachments(files []File) bool {
	f.Attachments = nil
	var chosen []File
	for _, file := range files {
		if file.Filename == "" && file.Size() == 0 {
			continue // un navegador sin archivo elegido envía una parte vacía
		}
		chosen = append(chosen, file)
	}
	if len(chosen) == 0 {
		return true
	}
	if len(chosen) > MaxAttachments {
		return f.addError(AttachmentCountMessage)
	}
	for _, file := range chosen {
		if !slices.Contains(attachmentExtensions, strings.ToLower(rubyExt(file.Filename))) {
			return f.addError(AttachmentTypeMessage)
		}
	}
	for _, file := range chosen {
		if file.Size() > MaxAttachmentBytes {
			return f.addError(AttachmentSizeMessage)
		}
	}
	f.Attachments = chosen
	return true
}

// Valid ejecuta las validaciones de los campos (como `valid?`, sustituye los errores previos).
func (f *Form) Valid() bool {
	f.Errors = nil
	if !slices.Contains(ProjectTypes, f.ProjectType) {
		f.Errors = append(f.Errors, "El tipo de proyecto no es válido.")
	}
	if !slices.Contains(DetailLevels, f.DetailLevel) {
		f.Errors = append(f.Errors, "El nivel de detalle no es válido.")
	}
	if !slices.Contains(OutputFormats, f.OutputFormat) {
		f.Errors = append(f.Errors, "El formato de salida no es válido.")
	}
	if !slices.Contains(PromptVersions, f.PromptVersion) {
		f.Errors = append(f.Errors, "La versión del prompt no es válida.")
	}
	// Con adjuntos el mensaje puede ser corto: la API valida la longitud de la transcripción más los adjuntos.
	minimum := MinDescription
	if len(f.Attachments) > 0 {
		minimum = 0
	}
	if length := f.DescriptionLength(); length < minimum || length > MaxDescription {
		f.Errors = append(f.Errors, DescriptionMessage)
	}
	return len(f.Errors) == 0
}

// AddError añade un error de formulario (p. ej. el de la API).
func (f *Form) AddError(message string) { f.Errors = append(f.Errors, message) }

func (f *Form) addError(message string) bool {
	f.Errors = append(f.Errors, message)
	return false
}

// APIAttributes son los campos de la estimación sin sesión (también sirven para la vista previa del prompt).
func (f *Form) APIAttributes() map[string]string {
	return map[string]string{
		"description": f.Description, "project_type": f.ProjectType,
		"detail_level": f.DetailLevel, "output_format": f.OutputFormat,
	}
}

// SessionFields son los campos de `POST /sessions/{id}/estimate` (la transcripción va como `transcript`).
func (f *Form) SessionFields() [][2]string {
	return [][2]string{
		{"transcript", f.Description}, {"project_type", f.ProjectType}, {"detail_level", f.DetailLevel},
		{"output_format", f.OutputFormat}, {"prompt_version", f.PromptVersion},
	}
}

// stripRuby replica `String#strip` de Ruby: recorta espacios ASCII y nulos, no los espacios Unicode.
func stripRuby(text string) string { return strings.Trim(text, " \t\n\v\f\r\x00") }

// rubyExt replica `File.extname`: un nombre que empieza por punto y no tiene otro no tiene extensión.
func rubyExt(name string) string {
	base := path.Base(strings.ReplaceAll(name, "\\", "/"))
	index := strings.LastIndex(base, ".")
	if index <= 0 || index == len(base)-1 {
		return ""
	}
	return base[index:]
}
