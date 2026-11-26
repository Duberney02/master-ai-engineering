package web

import (
	"context"
	"net/http"
	"strings"
)

type administrativeOperation string

// El ensamblado normal deja la decisión sin implementar hasta integrar identidad.
type administrativeDecision func(context.Context, administrativeOperation) (bool, error)

func (s *Server) permitsAdministration(r *http.Request, operation administrativeOperation) bool {
	if s.adminDecision == nil {
		return false
	}
	allowed, err := s.adminDecision(r.Context(), operation)
	return err == nil && allowed
}

// administrativeAPI consulta la decisión antes de entrar al handler: una denegación, la ausencia de mecanismo o un
// fallo de la decisión responden 403 sin leer datos, tocar cachés, invocar IA ni acceder al repositorio.
func (s *Server) administrativeAPI(op administrativeOperation, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !s.permitsAdministration(r, op) {
			apiFailure(w, http.StatusForbidden, "Acceso administrativo denegado.")
			return
		}
		next(w, r)
	}
}

func legacyAdministrativeOperation(r *http.Request) administrativeOperation {
	switch {
	case r.URL.Path == "/ai_settings":
		if safeMethod(r.Method) {
			return "settings.read"
		}
		return "settings.write"
	case r.URL.Path == "/rag/chunking_comparisons/new":
		return "lab.options"
	case r.URL.Path == "/rag/chunking_comparisons":
		if safeMethod(r.Method) {
			return "lab.list"
		}
		return "lab.create"
	case strings.HasPrefix(r.URL.Path, "/rag/chunking_comparisons/"):
		return "lab.detail"
	}
	return ""
}

func (s *Server) protectLegacy(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !safeMethod(r.Method) && !s.sameOrigin(r) {
			http.Error(w, "Origen no permitido.", http.StatusForbidden)
			return
		}
		if op := legacyAdministrativeOperation(r); op != "" && !s.permitsAdministration(r, op) {
			http.Error(w, "Acceso administrativo denegado.", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}
