package web

import (
	"context"
	"io"
	"mime/multipart"
	"net/http"

	"estimator-web/internal/estimation"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/jsondoc"
	"estimator-web/internal/session"
)

// Secciones de la barra de navegación.
const (
	sectionHome          = "home"
	sectionNewEstimation = "new_estimation"
	sectionHistory       = "history"
	sectionRag           = "rag"
	sectionSettings      = "settings"
)

// home es el panel de inicio: no consulta la API ni la base de datos, siempre se puede renderizar.
func (s *Server) home(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	s.render(w, r, sess, http.StatusOK, "home", &view{Title: "Inicio · Estimador de proyectos", Section: sectionHome})
}

// newPage son los datos de la pantalla del formulario.
type newPage struct {
	Form   *estimation.Form
	Notice string
}

// --- Conversación con memoria ---
//
// La conversación guarda en la sesión del navegador el `session_id` de la API y los metadatos del proyecto que ésta
// devuelve, para mostrarlos en la barra lateral de todas las pantallas. La API guarda las sesiones solo en memoria (se
// pierden al reiniciarla), así que un 404 de sesión se trata como «conversación caducada»: se abre otra y se avisa.

// ensureConversation devuelve el `session_id` vigente; si aún no hay conversación la abre en la API.
func (s *Server) ensureConversation(ctx context.Context, sess *session.Session) (string, error) {
	if id := sess.ConversationID(); id != "" {
		return id, nil
	}
	return s.startConversation(ctx, sess)
}

// startConversation abre otra conversación vacía en la API y descarta los metadatos de la anterior.
func (s *Server) startConversation(ctx context.Context, sess *session.Session) (string, error) {
	sess.ResetConversation()
	id, err := s.chats.CreateSession(ctx)
	if err != nil {
		return "", err
	}
	sess.SetConversation(id)
	return id, nil
}

// loadSidebar prepara la barra lateral. Es informativa: si la API no puede renderizar el prompt, la página sigue
// funcionando.
func (s *Server) loadSidebar(ctx context.Context, sess *session.Session, options map[string]string, promptVersion string, metrics jsondoc.Doc) *sidebar {
	preview, err := s.estimations.PromptPreview(ctx, promptVersion, options["project_type"], options["detail_level"], options["output_format"])
	if err != nil {
		preview = nil
	}
	return &sidebar{Preview: preview, Metrics: metrics, PromptVersion: promptVersion, Metadata: sess.Metadata()}
}

func (s *Server) estimationsNew(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	form := estimation.New()
	// La conversación se abre al cargar la página y se conserva en la sesión. Si la API no responde ahora, el envío
	// del formulario lo reintenta.
	_, _ = s.ensureConversation(r.Context(), sess)
	s.renderForm(w, r, sess, http.StatusOK, form, "")
}

func (s *Server) renderForm(w http.ResponseWriter, r *http.Request, sess *session.Session, status int, form *estimation.Form, notice string) {
	side := s.loadSidebar(r.Context(), sess, form.APIAttributes(), form.PromptVersion, nil)
	// Como en Rails: solo la acción `new` marca «Nueva estimación»; el reenvío del formulario (create) marca «Historial».
	section := sectionHistory
	if r.Method == http.MethodGet {
		section = sectionNewEstimation
	}
	s.render(w, r, sess, status, "estimations_new", &view{Section: section, Sidebar: side, Data: newPage{Form: form, Notice: notice}})
}

func (s *Server) estimationsCreate(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	form := estimation.FromParams(estimationParams(r))
	form.LoadUpload(uploadFile(r))
	form.LoadAttachments(attachmentFiles(r))
	if len(form.Errors) > 0 || !form.Valid() {
		s.renderForm(w, r, sess, http.StatusUnprocessableEntity, form, "")
		return
	}

	conversationID, err := s.ensureConversation(r.Context(), sess)
	var response jsondoc.Doc
	if err == nil {
		response, err = s.chats.CreateSessionEstimation(r.Context(), conversationID, toFields(form), toAttachments(form))
	}
	if err != nil {
		if estimatorai.IsKind(err, estimatorai.SessionExpired) {
			s.sessionExpired(w, r, sess, form)
			return
		}
		form.AddError(err.Error())
		s.renderForm(w, r, sess, http.StatusUnprocessableEntity, form, "")
		return
	}

	sess.RememberMetadata(response.Doc("project_metadata"))
	if id := response.Get("estimation_id"); jsondoc.Truthy(id) {
		s.redirect(w, r, sess, "/estimations/"+jsondoc.String(id))
		return
	}
	// Historial desactivado o no disponible: se muestra el resultado sin enlace permanente.
	options := jsondoc.Doc{}
	for key, value := range form.APIAttributes() {
		options[key] = value
	}
	shown := jsondoc.Doc{}
	for key, value := range response {
		shown[key] = value
	}
	shown["description"] = form.Description
	shown["options"] = options
	side := s.loadSidebar(r.Context(), sess, form.APIAttributes(), form.PromptVersion, response.Doc("metrics"))
	s.render(w, r, sess, http.StatusOK, "estimations_show", &view{Section: sectionHistory, Sidebar: side, Data: shown})
}

// sessionExpired: la API perdió la sesión; se abre otra, se avisa y el formulario conserva lo escrito.
func (s *Server) sessionExpired(w http.ResponseWriter, r *http.Request, sess *session.Session, form *estimation.Form) {
	if _, err := s.startConversation(r.Context(), sess); err != nil {
		form.AddError(err.Error())
		s.renderForm(w, r, sess, http.StatusUnprocessableEntity, form, "")
		return
	}
	s.renderForm(w, r, sess, http.StatusOK, form, estimatorai.SessionExpiredMessage)
}

func (s *Server) estimationsIndex(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	defaults := estimation.New()
	side := s.loadSidebar(r.Context(), sess, defaults.APIAttributes(), defaults.PromptVersion, nil)
	items, err := s.estimations.ListEstimations(r.Context(), 10)
	page := struct {
		Estimations []jsondoc.Doc
		Error       string
	}{Estimations: items}
	if err != nil {
		page.Estimations, page.Error = nil, err.Error()
	}
	s.render(w, r, sess, http.StatusOK, "estimations_index", &view{Section: sectionHistory, Sidebar: side, Data: page})
}

func (s *Server) estimationsShow(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	found, err := s.estimations.FindEstimation(r.Context(), r.PathValue("id"))
	if err != nil {
		s.renderAPIError(w, r, sess, err)
		return
	}
	options := found.Doc("options")
	side := s.loadSidebar(r.Context(), sess, map[string]string{
		"project_type": options.S("project_type"), "detail_level": options.S("detail_level"), "output_format": options.S("output_format"),
	}, found.S("prompt_version"), found.Doc("metrics"))
	s.render(w, r, sess, http.StatusOK, "estimations_show", &view{Section: sectionHistory, Sidebar: side, Data: found})
}

// renderAPIError: la pantalla de error de la API (sin barra lateral); 404 si no existe, 502 en el resto.
func (s *Server) renderAPIError(w http.ResponseWriter, r *http.Request, sess *session.Session, err error) {
	status := http.StatusBadGateway
	if typed, ok := estimatorai.As(err); ok && typed.Status == http.StatusNotFound {
		status = http.StatusNotFound
	}
	s.render(w, r, sess, status, "estimations_error", &view{Section: sectionHistory, Data: err.Error()})
}

// conversationCreate: «Nueva conversación» descarta la sesión actual y abre otra en la API.
func (s *Server) conversationCreate(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	if _, err := s.startConversation(r.Context(), sess); err != nil {
		// Sin API no se puede abrir la sesión ahora: el estado queda limpio y el siguiente envío la crea.
		sess.ResetConversation()
	}
	s.redirect(w, r, sess, "/estimations/new")
}

// --- Lectura del formulario ---

func estimationParams(r *http.Request) estimation.Params {
	params := estimation.Params{}
	for _, field := range []string{"description", "project_type", "detail_level", "output_format", "prompt_version"} {
		if values, ok := r.PostForm["estimation_form["+field+"]"]; ok && len(values) > 0 {
			params[field] = values[len(values)-1]
		}
	}
	return params
}

// uploadFile lee el archivo .txt de la transcripción (acotado para no cargar en memoria un envío desmesurado).
func uploadFile(r *http.Request) *estimation.File {
	headers := fileHeaders(r, "estimation_form[upload]")
	if len(headers) == 0 {
		return nil
	}
	file := readFile(headers[0], estimation.MaxUploadBytes+1)
	return &file
}

func attachmentFiles(r *http.Request) []estimation.File {
	var files []estimation.File
	for _, header := range fileHeaders(r, "estimation_form[attachments][]") {
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
