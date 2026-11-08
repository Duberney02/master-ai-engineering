package httpapi

import (
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"strconv"
	"strings"

	"estimator-web/internal/estimation"
	"estimator-web/internal/estimatorai"
)

// Conversación con memoria y estimaciones. El `conversation_id` es el `session_id` de la API de IA: lo conserva el
// cliente. La API guarda las sesiones solo en memoria (se pierden al reiniciarla), así que un 404 de sesión es
// «conversación caducada»: el cliente abre otra.

const (
	defaultHistoryLimit = 10
	maxHistoryLimit     = 50
)

func (s *Server) conversationCreate(w http.ResponseWriter, r *http.Request) {
	id, err := s.chats.CreateSession(r.Context())
	if err != nil {
		s.writeAPIError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]string{"conversation_id": id})
}

func (s *Server) estimationCreate(w http.ResponseWriter, r *http.Request) {
	if err := parseForm(r); err != nil {
		s.log.Warn("form_rejected", "path", "/api/conversations/{id}/estimations", "error_type", fmt.Sprintf("%T", err))
		writeDetail(w, http.StatusRequestEntityTooLarge, "La solicitud es demasiado grande o no es válida.")
		return
	}
	form := estimation.FromParams(estimationParams(r))
	form.LoadUpload(uploadFile(r))
	form.LoadAttachments(attachmentFiles(r))
	if len(form.Errors) > 0 || !form.Valid() {
		writeDetail(w, http.StatusUnprocessableEntity, form.Errors[0])
		return
	}

	response, err := s.chats.CreateSessionEstimation(r.Context(), r.PathValue("id"), toFields(form), toAttachments(form))
	if err != nil {
		s.writeAPIError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, response)
}

func (s *Server) estimationsIndex(w http.ResponseWriter, r *http.Request) {
	limit := defaultHistoryLimit
	if raw := r.URL.Query().Get("limit"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 {
			writeDetail(w, http.StatusUnprocessableEntity, estimatorai.ValidationMessage)
			return
		}
		limit = min(parsed, maxHistoryLimit)
	}
	items, err := s.estimations.ListEstimations(r.Context(), limit)
	if err != nil {
		s.writeAPIError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

func (s *Server) estimationsShow(w http.ResponseWriter, r *http.Request) {
	found, err := s.estimations.FindEstimation(r.Context(), r.PathValue("id"))
	if err != nil {
		s.writeAPIError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, found)
}

func (s *Server) promptPreview(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query()
	preview, err := s.estimations.PromptPreview(r.Context(), query.Get("prompt_version"), query.Get("project_type"), query.Get("detail_level"), query.Get("output_format"))
	if err != nil {
		s.writeAPIError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, preview)
}

// --- Lectura del formulario multipart ---

func parseForm(r *http.Request) error {
	if strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data") {
		return r.ParseMultipartForm(maxBodyBytes)
	}
	return r.ParseForm()
}

func estimationParams(r *http.Request) estimation.Params {
	params := estimation.Params{}
	for _, field := range []string{"description", "project_type", "detail_level", "output_format", "prompt_version"} {
		if values, ok := r.PostForm[field]; ok && len(values) > 0 {
			params[field] = values[len(values)-1]
		}
	}
	return params
}

// uploadFile lee el archivo .txt de la transcripción (acotado para no cargar en memoria un envío desmesurado).
func uploadFile(r *http.Request) *estimation.File {
	headers := fileHeaders(r, "upload")
	if len(headers) == 0 {
		return nil
	}
	file := readFile(headers[0], estimation.MaxUploadBytes+1)
	return &file
}

func attachmentFiles(r *http.Request) []estimation.File {
	var files []estimation.File
	for _, header := range fileHeaders(r, "attachments") {
		files = append(files, readFile(header, estimation.MaxAttachmentBytes+1))
	}
	return files
}

func fileHeaders(r *http.Request, name string) []*multipart.FileHeader {
	if r.MultipartForm == nil {
		return nil
	}
	return r.MultipartForm.File[name]
}

// readFile lee como mucho `limit` bytes: basta para detectar que supera el máximo sin cargarlo entero.
func readFile(header *multipart.FileHeader, limit int64) estimation.File {
	file := estimation.File{Filename: header.Filename, ContentType: header.Header.Get("Content-Type")}
	handle, err := header.Open()
	if err != nil {
		return file
	}
	defer handle.Close()
	file.Data, _ = io.ReadAll(io.LimitReader(handle, limit))
	return file
}

func toFields(form *estimation.Form) []estimatorai.Field {
	pairs := form.SessionFields()
	fields := make([]estimatorai.Field, len(pairs))
	for index, pair := range pairs {
		fields[index] = estimatorai.Field{Name: pair[0], Value: pair[1]}
	}
	return fields
}

func toAttachments(form *estimation.Form) []estimatorai.Attachment {
	attachments := make([]estimatorai.Attachment, len(form.Attachments))
	for index, file := range form.Attachments {
		attachments[index] = estimatorai.Attachment{Filename: file.Filename, ContentType: file.ContentType, Data: file.Data}
	}
	return attachments
}
