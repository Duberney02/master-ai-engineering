package web

import (
	"encoding/json"
	"errors"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"estimator-web/internal/estimatorai"
)

const (
	jsonLimit      = 1 << 20
	multipartLimit = 55 << 20
	fileLimit      = 10 << 20
)

func (s *Server) apiHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/v1/sessions", s.apiSession)
	mux.HandleFunc("POST /api/v1/sessions/{session_id}/estimate", s.apiTurn)
	mux.HandleFunc("POST /api/v1/estimate", s.apiEstimate)
	mux.HandleFunc("POST /api/v1/estimate/stream", s.apiEstimateStream)
	mux.HandleFunc("POST /api/v1/transcription/estimate/stream", s.apiTranscriptionStream)
	mux.HandleFunc("GET /api/v1/prompts/estimation", s.apiPreview)
	mux.HandleFunc("GET /api/v1/estimations", s.apiHistory)
	mux.HandleFunc("GET /api/v1/estimations/{estimation_id}", s.apiDetail)
	mux.HandleFunc("GET /health", s.apiHealth)
	mux.HandleFunc("GET /api/v1/ai/settings", s.administrativeAPI("settings.read"))
	mux.HandleFunc("PUT /api/v1/ai/settings", s.administrativeAPI("settings.write"))
	mux.HandleFunc("GET /api/v1/rag/chunking-comparisons/options", s.administrativeAPI("lab.options"))
	mux.HandleFunc("GET /api/v1/rag/chunking-comparisons", s.administrativeAPI("lab.list"))
	mux.HandleFunc("POST /api/v1/rag/chunking-comparisons", s.administrativeAPI("lab.create"))
	mux.HandleFunc("GET /api/v1/rag/chunking-comparisons/{id}", s.administrativeAPI("lab.detail"))

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if path.Clean(r.URL.Path) != r.URL.Path {
			apiFailure(w, 404, "Ruta no encontrada.")
			return
		}
		if !safeMethod(r.Method) && !s.sameOrigin(r) {
			apiFailure(w, 403, "Origen no permitido.")
			return
		}
		if _, pattern := mux.Handler(r); pattern == "" || r.Method == http.MethodHead {
			methods := []string{}
			for _, method := range []string{"GET", "POST", "PUT", "PATCH", "DELETE"} {
				clone := *r
				clone.Method = method
				if _, p := mux.Handler(&clone); p != "" {
					methods = append(methods, method)
				}
			}
			if len(methods) > 0 {
				w.Header().Set("Allow", strings.Join(methods, ", "))
				apiFailure(w, 405, "Método no permitido.")
			} else {
				apiFailure(w, 404, "Ruta no encontrada.")
			}
			return
		}
		mux.ServeHTTP(w, r)
	})
}

func apiJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func apiFailure(w http.ResponseWriter, status int, message string) {
	apiJSON(w, status, map[string]string{"detail": message})
}

func apiReply(w http.ResponseWriter, r *http.Request, status int, value estimatorai.Response, err error) {
	if r.Context().Err() != nil {
		return
	}
	if err == nil {
		apiJSON(w, status, value)
		return
	}
	if e, ok := estimatorai.As(err); ok {
		switch {
		case e.Status == 400 && e.Reason != "":
			apiJSON(w, 400, map[string]string{"reason": e.Reason, "message": e.Message})
		case e.IsA(estimatorai.RequestTimeout):
			apiFailure(w, 504, e.Message)
		case e.IsA(estimatorai.ConnectionFailed):
			apiFailure(w, 503, e.Message)
		case e.Status == 400 || e.Status == 404 || e.Status == 413 || e.Status == 415 || e.Status == 422 || e.Status == 429 || e.Status == 503:
			apiFailure(w, e.Status, e.Message)
		default:
			apiFailure(w, 502, estimatorai.InvalidResponseMessage)
		}
		return
	}
	apiFailure(w, 502, estimatorai.ServerMessage)
}

func (s *Server) sameOrigin(r *http.Request) bool {
	origins := r.Header.Values("Origin")
	if len(origins) == 0 {
		return r.Header.Get("Sec-Fetch-Site") != "cross-site"
	}
	if len(origins) != 1 || origins[0] == "" {
		return false
	}
	expected := s.cfg.PublicOrigin
	if expected == "" {
		scheme := "http"
		if r.TLS != nil {
			scheme = "https"
		}
		expected = scheme + "://" + r.Host
	}
	return origins[0] == expected
}

func (s *Server) apiSession(w http.ResponseWriter, r *http.Request) {
	stop := uploadDeadline(w)
	defer stop()
	data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1))
	if err != nil || len(data) != 0 {
		apiFailure(w, 422, "La creación de sesión no admite cuerpo.")
		return
	}
	stop()
	value, err := s.publicAI.CreateSession(r.Context())
	apiReply(w, r, 201, value, err)
}

func readJSON(w http.ResponseWriter, r *http.Request, input any) bool {
	kind, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || kind != "application/json" {
		apiFailure(w, 415, "Se requiere application/json.")
		return false
	}
	stop := uploadDeadline(w)
	defer stop()
	data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, jsonLimit))
	if err != nil {
		requestReadError(w, err)
		return false
	}
	if !utf8.Valid(data) || !json.Valid(data) {
		apiFailure(w, 400, "El cuerpo JSON no es válido.")
		return false
	}
	if len(data) == 0 || strings.TrimSpace(string(data))[0] != '{' || json.Unmarshal(data, input) != nil {
		apiFailure(w, 422, estimatorai.ValidationMessage)
		return false
	}
	return true
}

func uploadDeadline(w http.ResponseWriter) func() {
	controller := http.NewResponseController(w)
	_ = controller.SetReadDeadline(time.Now().Add(30 * time.Second))
	return func() { _ = controller.SetReadDeadline(time.Time{}) }
}

func requestReadError(w http.ResponseWriter, err error) {
	var overflow *http.MaxBytesError
	if errors.As(err, &overflow) {
		apiFailure(w, 413, "El cuerpo supera el tamaño permitido.")
		return
	}
	apiFailure(w, 400, "No se pudo leer el cuerpo de la solicitud.")
}

func oneOf(value string, choices ...string) bool {
	for _, choice := range choices {
		if choice == value {
			return true
		}
	}
	return false
}

func validEstimateOptions(project, detail, output string) bool {
	return oneOf(project, "mobile_app", "web_saas", "internal_tool", "data_pipeline") &&
		oneOf(detail, "summary", "medium", "detailed") && oneOf(output, "phases_table", "line_items", "narrative")
}

func runeLength(s string, min, max int) bool {
	n := utf8.RuneCountInString(s)
	return n >= min && n <= max
}

func referencesValid(data string) bool {
	if data == "" {
		return true
	}
	var projects []estimatorai.ReferenceProject
	if json.Unmarshal([]byte(data), &projects) != nil || len(projects) > 5 {
		return false
	}
	for _, p := range projects {
		if !runeLength(p.Name, 1, 120) || !runeLength(p.Description, 1, 500) || p.ActualHours <= 0 || p.ActualHours > 100000 {
			return false
		}
	}
	return true
}

func readEstimate(w http.ResponseWriter, r *http.Request) (estimatorai.EstimateInput, string, bool) {
	var input estimatorai.EstimateInput
	if !readJSON(w, r, &input) {
		return input, "", false
	}
	query, err := url.ParseQuery(r.URL.RawQuery)
	version := queryDefault(query, "prompt_version", "v3")
	if err != nil || !runeLength(version, 1, 10) || !runeLength(input.Description, 20, 80000) ||
		!validEstimateOptions(input.ProjectType, input.DetailLevel, input.OutputFormat) || !referencesValid(string(input.ReferenceProjects)) {
		apiFailure(w, 422, estimatorai.ValidationMessage)
		return input, "", false
	}
	return input, version, true
}

func (s *Server) apiEstimate(w http.ResponseWriter, r *http.Request) {
	input, version, ok := readEstimate(w, r)
	if !ok {
		return
	}
	value, err := s.publicAI.Estimate(r.Context(), version, input)
	apiReply(w, r, 200, value, err)
}

func queryDefault(query url.Values, key, fallback string) string {
	if query.Has(key) {
		return query.Get(key)
	}
	return fallback
}

func (s *Server) apiPreview(w http.ResponseWriter, r *http.Request) {
	query, err := url.ParseQuery(r.URL.RawQuery)
	fixed := url.Values{}
	for key, fallback := range map[string]string{"prompt_version": "v3", "project_type": "mobile_app", "detail_level": "medium", "output_format": "phases_table"} {
		fixed.Set(key, queryDefault(query, key, fallback))
	}
	if err != nil || !runeLength(fixed.Get("prompt_version"), 1, 10) || !validEstimateOptions(fixed.Get("project_type"), fixed.Get("detail_level"), fixed.Get("output_format")) {
		apiFailure(w, 422, estimatorai.ValidationMessage)
		return
	}
	value, err := s.publicAI.Preview(r.Context(), fixed)
	apiReply(w, r, 200, value, err)
}

func (s *Server) apiHistory(w http.ResponseWriter, r *http.Request) {
	query, err := url.ParseQuery(r.URL.RawQuery)
	limit, parseErr := strconv.Atoi(queryDefault(query, "limit", "10"))
	if err != nil || parseErr != nil || limit < 1 || limit > 50 {
		apiFailure(w, 422, estimatorai.ValidationMessage)
		return
	}
	value, err := s.publicAI.History(r.Context(), limit)
	if typed, ok := estimatorai.As(err); ok && typed.Status == 503 {
		apiFailure(w, 503, estimatorai.HistoryUnavailableMessage)
		return
	}
	apiReply(w, r, 200, value, err)
}

func (s *Server) apiDetail(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("estimation_id"), 10, 64)
	if err != nil {
		apiFailure(w, 422, estimatorai.ValidationMessage)
		return
	}
	value, err := s.publicAI.Detail(r.Context(), id)
	if typed, ok := estimatorai.As(err); ok && typed.Status == 503 {
		apiFailure(w, 503, estimatorai.HistoryUnavailableMessage)
		return
	}
	apiReply(w, r, 200, value, err)
}

func (s *Server) apiHealth(w http.ResponseWriter, r *http.Request) {
	value, err := s.publicAI.Health(r.Context())
	if err != nil {
		apiJSON(w, 503, map[string]string{"status": "unavailable"})
		return
	}
	apiReply(w, r, 200, value, nil)
}

func (s *Server) apiTurn(w http.ResponseWriter, r *http.Request) {
	contentType := r.Header.Get("Content-Type")
	kind, params, err := mime.ParseMediaType(contentType)
	if err != nil || !oneOf(kind, "multipart/form-data", "application/x-www-form-urlencoded") {
		apiFailure(w, 415, "Se requiere un formulario multipart o URL-encoded.")
		return
	}
	stop := uploadDeadline(w)
	defer stop()
	if kind == "application/x-www-form-urlencoded" {
		body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, jsonLimit))
		if err != nil {
			requestReadError(w, err)
			return
		}
		fields, err := url.ParseQuery(string(body))
		if err != nil || !validTurn(fields) {
			apiFailure(w, 422, estimatorai.ValidationMessage)
			return
		}
		stop()
		value, err := s.publicAI.Turn(r.Context(), r.PathValue("session_id"), strings.NewReader(string(body)), contentType)
		apiReply(w, r, 200, value, err)
		return
	}
	if params["boundary"] == "" {
		apiFailure(w, 422, estimatorai.ValidationMessage)
		return
	}
	temp, err := os.CreateTemp("", "estimator-upload-*")
	if err != nil {
		apiFailure(w, 503, "No se pudo preparar la carga.")
		return
	}
	defer os.Remove(temp.Name())
	defer temp.Close()
	if _, err = io.Copy(temp, http.MaxBytesReader(w, r.Body, multipartLimit)); err != nil {
		requestReadError(w, err)
		return
	}
	stop()
	if _, err = temp.Seek(0, io.SeekStart); err != nil {
		apiFailure(w, 503, "No se pudo preparar la carga.")
		return
	}
	if code := validateMultipart(multipart.NewReader(temp, params["boundary"])); code != 0 {
		apiFailure(w, code, estimatorai.ValidationMessage)
		return
	}
	if _, err = temp.Seek(0, io.SeekStart); err != nil {
		apiFailure(w, 503, "No se pudo preparar la carga.")
		return
	}
	value, err := s.publicAI.Turn(r.Context(), r.PathValue("session_id"), temp, contentType)
	apiReply(w, r, 200, value, err)
}

func validateMultipart(reader *multipart.Reader) int {
	fields := url.Values{}
	files := 0
	for count := 0; ; count++ {
		part, err := reader.NextRawPart()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return 422
		}
		if count >= 32 {
			return 413
		}
		if part.FileName() != "" {
			if part.FormName() != "attachments" {
				return 422
			}
			files++
			if files > 5 {
				return 413
			}
			if !oneOf(strings.ToLower(filepath.Ext(part.FileName())), ".pdf", ".docx") {
				return 415
			}
			size, err := io.Copy(io.Discard, io.LimitReader(part, fileLimit+1))
			if err != nil {
				return 422
			}
			if size > fileLimit {
				return 413
			}
			continue
		}
		data, err := io.ReadAll(io.LimitReader(part, jsonLimit+1))
		if err != nil {
			return 422
		}
		if len(data) > jsonLimit {
			return 413
		}
		if !utf8.Valid(data) {
			return 422
		}
		fields.Set(part.FormName(), string(data))
	}
	if !validTurn(fields) {
		return 422
	}
	return 0
}

func validTurn(fields url.Values) bool {
	for _, values := range fields {
		for _, value := range values {
			if !utf8.ValidString(value) {
				return false
			}
		}
	}
	return validEstimateOptions(fields.Get("project_type"), queryDefault(fields, "detail_level", "medium"), queryDefault(fields, "output_format", "phases_table")) &&
		runeLength(fields.Get("prompt_version"), 0, 10) && referencesValid(fields.Get("reference_projects")) &&
		oneOf(strings.ToLower(strings.TrimSpace(fields.Get("tier"))), "", "executive", "pm", "developer", "default")
}
