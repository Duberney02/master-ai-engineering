package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"

	"estimator-web/internal/ai"
	"estimator-web/internal/estimatorai"
)

// Ajustes del servicio IA: modelos del LLM en tiempo de ejecución. Lee y escribe GET/PUT /api/v1/config/models; el
// cambio aplica desde la siguiente solicitud, sin tocar `.env` ni reiniciar nada. Solo transporte: la validación y la
// persistencia de los overrides son del servicio.

// modelJSON es un knob de modelo tal como lo necesita la pantalla.
type modelJSON struct {
	Key         string   `json:"key"`
	Label       string   `json:"label"`
	Description string   `json:"description"`
	Provider    string   `json:"provider"`
	Effective   string   `json:"effective"`
	Default     string   `json:"default"`
	Overridden  bool     `json:"overridden"`
	Selected    string   `json:"selected"`
	Options     []string `json:"options"`
}

func catalogJSON(catalog ai.Catalog) map[string]any {
	models := make([]modelJSON, len(catalog.ModelConfigs))
	for index, config := range catalog.ModelConfigs {
		options := catalog.OptionsFor(config)
		if options == nil {
			options = []string{}
		}
		models[index] = modelJSON{
			Key: config.Key, Label: config.Label(), Description: config.Description(), Provider: config.Provider(),
			Effective: config.Effective, Default: config.Default, Overridden: config.Overridden, Selected: config.Selected(),
			Options: options,
		}
	}
	available := catalog.AvailableModels
	if available == nil {
		available = []string{}
	}
	return map[string]any{
		"models": models, "available_models": available, "embedding_model": catalog.EmbeddingModel,
		"embedding_model_note": catalog.EmbeddingModelNote, "any_overridden": catalog.AnyOverridden(),
	}
}

func (s *Server) settingsShow(w http.ResponseWriter, r *http.Request) {
	catalog, err := s.loadCatalog(r.Context())
	if err != nil {
		s.writeAPIError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, catalogJSON(catalog))
}

// settingsRequest es el cuerpo de PUT /api/ai-settings: `null` o vacío restablece el knob a su valor por defecto.
type settingsRequest struct {
	Models map[string]*string `json:"models"`
}

func (s *Server) settingsUpdate(w http.ResponseWriter, r *http.Request) {
	var body settingsRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeDetail(w, http.StatusUnprocessableEntity, estimatorai.ValidationMessage)
		return
	}
	changes := sanitizedChanges(body.Models)
	if len(changes) == 0 {
		writeDetail(w, http.StatusUnprocessableEntity, "No hay ningún modelo que cambiar.")
		return
	}

	updated, err := s.models.UpdateModels(r.Context(), changes)
	if err != nil {
		if estimatorai.IsKind(err, estimatorai.InvalidRequest) {
			writeDetail(w, http.StatusUnprocessableEntity, "Cambio rechazado: "+err.Error())
			return
		}
		s.writeAPIError(w, err)
		return
	}
	// El indicador cachea el primario unos segundos: se descarta para que el cambio se vea ya.
	s.badge.Invalidate()
	writeJSON(w, http.StatusOK, catalogJSON(ai.FromDoc(updated)))
}

func (s *Server) primaryModel(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"primary_model": s.badge.Get(r.Context())})
}

func (s *Server) loadCatalog(ctx context.Context) (ai.Catalog, error) {
	models, err := s.models.Models(ctx)
	if err != nil {
		return ai.Catalog{}, err
	}
	return ai.FromDoc(models), nil
}

// sanitizedChanges: cada guardado envía todos los knobs; un valor vacío significa «usar el valor por defecto»
// (restablecer). Los knobs desconocidos se ignoran.
func sanitizedChanges(models map[string]*string) map[string]*string {
	changes := map[string]*string{}
	for _, key := range ai.Keys() {
		value, submitted := models[key]
		if !submitted {
			continue
		}
		if value == nil || strings.TrimSpace(*value) == "" {
			changes[key] = nil
			continue
		}
		changes[key] = value
	}
	return changes
}
