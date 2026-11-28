package web

import (
	"context"
	"net/http"
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
