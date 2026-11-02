package web

import (
	"context"
	"net/http"
	"strings"

	"estimator-web/internal/ai"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/session"
)

// Ajustes del servicio IA: modelos del LLM en tiempo de ejecución. Lee y escribe GET/PUT /api/v1/config/models; el
// cambio aplica desde la siguiente solicitud, sin tocar `.env` ni reiniciar nada. Solo transporte: la validación y la
// persistencia de los overrides son del servicio.

// settingsPage lleva el catálogo (nil si no se pudo leer: la pantalla se muestra sin formulario).
type settingsPage struct{ Catalog *ai.Catalog }

func (s *Server) settingsShow(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	catalog, err := s.loadCatalog(r.Context())
	if err != nil {
		sess.FlashNow("alert", "No se pudo leer la configuración del servicio IA: "+err.Error())
		s.renderSettings(w, r, sess, settingsStatus(err), nil)
		return
	}
	s.renderSettings(w, r, sess, http.StatusOK, &catalog)
}

func (s *Server) settingsUpdate(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	changes := sanitizedChanges(r)
	if len(changes) == 0 {
		sess.FlashNext("alert", "No hay ningún modelo que cambiar.")
		s.redirect(w, r, sess, "/ai_settings")
		return
	}

	if _, err := s.models.UpdateModels(r.Context(), changes); err != nil {
		message := err.Error()
		if estimatorai.IsKind(err, estimatorai.InvalidRequest) {
			message = "Cambio rechazado: " + message
		}
		sess.FlashNow("alert", message)
		// Tras un rechazo se vuelve a leer lo vigente; si tampoco se puede, la pantalla se muestra sin formulario.
		var current *ai.Catalog
		if catalog, loadErr := s.loadCatalog(r.Context()); loadErr == nil {
			current = &catalog
		}
		s.renderSettings(w, r, sess, settingsStatus(err), current)
		return
	}
	// El indicador de la barra cachea el primario unos segundos: se descarta para que el cambio se vea ya.
	s.badge.Invalidate()
	sess.FlashNext("notice", "Modelos actualizados. El cambio aplica desde la siguiente solicitud.")
	s.redirect(w, r, sess, "/ai_settings")
}

func (s *Server) renderSettings(w http.ResponseWriter, r *http.Request, sess *session.Session, status int, catalog *ai.Catalog) {
	s.render(w, r, sess, status, "settings", &view{Title: "Ajustes · Estimador de proyectos", Section: sectionSettings, Data: settingsPage{Catalog: catalog}})
}

func (s *Server) loadCatalog(ctx context.Context) (ai.Catalog, error) {
	models, err := s.models.Models(ctx)
	if err != nil {
		return ai.Catalog{}, err
	}
	return ai.FromDoc(models), nil
}

// sanitizedChanges: cada guardado envía todos los knobs; un select vacío significa «usar el valor por defecto»
// (restablecer). Los knobs desconocidos se ignoran.
func sanitizedChanges(r *http.Request) map[string]*string {
	changes := map[string]*string{}
	for _, key := range ai.Keys() {
		values, submitted := r.PostForm["models["+key+"]"]
		if !submitted || len(values) == 0 {
			continue
		}
		value := values[len(values)-1]
		if strings.TrimSpace(value) == "" {
			changes[key] = nil
			continue
		}
		changes[key] = &value
	}
	return changes
}

func settingsStatus(err error) int {
	switch {
	case estimatorai.IsKind(err, estimatorai.InvalidRequest):
		return http.StatusUnprocessableEntity
	case estimatorai.IsKind(err, estimatorai.ConnectionFailed), estimatorai.IsKind(err, estimatorai.ServiceUnavailable):
		return http.StatusServiceUnavailable
	}
	return http.StatusBadGateway
}
