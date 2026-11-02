// Package ai es el contexto «configuración del servicio»: los modelos del LLM que se cambian en tiempo de ejecución
// (pantalla de Ajustes). Refleja la instantánea de GET /api/v1/config/models.
package ai

import (
	"strings"

	"estimator-web/internal/jsondoc"
)

// Entry es la presentación de un knob configurable.
type Entry struct {
	Key         string
	Label       string
	Description string
	// Provider limita los modelos seleccionables a un proveedor («openai» o «anthropic»); vacío admite todos.
	Provider string
}

// Entries es el catálogo de presentación de los siete knobs configurables, en el orden de la pantalla. Los nombres
// son los de `MODEL_KNOBS` del servicio.
var Entries = []Entry{
	{Key: "primary_model", Label: "Modelo primario",
		Description: "Genera todas las estimaciones (transaccional, conversación y actor del bucle Actor-Crítico-Boss)."},
	{Key: "fallback_model", Label: "Modelo de respaldo",
		Description: "Se usa cuando el primario falla de forma reintentable. Sin valor, no hay segundo intento."},
	{Key: "critic_model", Label: "Crítico (ACB)",
		Description: "Audita las estimaciones en el bucle Actor-Crítico-Boss."},
	{Key: "metadata_model", Label: "Extractor de metadatos",
		Description: "Extrae nombre, tecnologías y alcance del proyecto una vez por turno."},
	{Key: "summary_model", Label: "Resumen y compresión",
		Description: "Resume la memoria de la conversación y detecta anclas."},
	{Key: "propositional_chunker_model", Label: "Chunker proposicional", Provider: "openai",
		Description: "Descompone componentes en proposiciones atómicas (Chunking Lab). Solo modelos de OpenAI."},
	{Key: "contextual_chunker_model", Label: "Chunker contextual", Provider: "anthropic",
		Description: "Sitúa cada chunk en su presupuesto (Chunking Lab). Solo modelos de Anthropic."},
}

// Keys son los nombres de los knobs, en el orden de la pantalla.
func Keys() []string {
	keys := make([]string, len(Entries))
	for index, entry := range Entries {
		keys[index] = entry.Key
	}
	return keys
}

// IsKey indica si el nombre es un knob conocido.
func IsKey(name string) bool {
	for _, entry := range Entries {
		if entry.Key == name {
			return true
		}
	}
	return false
}

// ModelConfig refleja una entrada `models[knob]`: qué modelo está vigente para un knob, cuál es su valor por defecto
// (`.env`) y si hay un override en runtime.
type ModelConfig struct {
	Key        string
	Effective  string
	Default    string
	Overridden bool
}

func (c ModelConfig) entry() (Entry, bool) {
	for _, entry := range Entries {
		if entry.Key == c.Key {
			return entry, true
		}
	}
	return Entry{}, false
}

// Label es el nombre de pantalla (o la clave si el knob no está en el catálogo).
func (c ModelConfig) Label() string {
	if entry, ok := c.entry(); ok {
		return entry.Label
	}
	return c.Key
}

func (c ModelConfig) Description() string {
	entry, _ := c.entry()
	return entry.Description
}

func (c ModelConfig) Provider() string {
	entry, _ := c.entry()
	return entry.Provider
}

// Selected es el modelo preseleccionado en el formulario: el vigente solo si hay override.
func (c ModelConfig) Selected() string {
	if c.Overridden {
		return c.Effective
	}
	return ""
}

// Catalog refleja la respuesta completa de GET /api/v1/config/models: los siete knobs (en el orden de la pantalla),
// el catálogo seleccionable (la API ya lo filtra por las claves configuradas) y el modelo de embeddings, de solo
// lectura.
type Catalog struct {
	ModelConfigs       []ModelConfig
	AvailableModels    []string
	EmbeddingModel     string
	EmbeddingModelNote string
}

// FromDoc construye el catálogo a partir de la respuesta de la API.
func FromDoc(doc jsondoc.Doc) Catalog {
	models := doc.Doc("models")
	catalog := Catalog{
		AvailableModels:    doc.Strings("available_models"),
		EmbeddingModel:     doc.S("embedding_model"),
		EmbeddingModelNote: doc.S("embedding_model_note"),
	}
	for _, key := range Keys() {
		if !models.Has(key) {
			continue
		}
		raw := models.Doc(key)
		catalog.ModelConfigs = append(catalog.ModelConfigs, ModelConfig{
			Key: key, Effective: raw.S("effective"), Default: raw.S("default"), Overridden: raw.Truthy("overridden"),
		})
	}
	return catalog
}

// PrimaryModel es el modelo primario vigente.
func (c Catalog) PrimaryModel() string {
	for _, config := range c.ModelConfigs {
		if config.Key == "primary_model" {
			return config.Effective
		}
	}
	return ""
}

// AnyOverridden indica si algún knob tiene un override en runtime.
func (c Catalog) AnyOverridden() bool {
	for _, config := range c.ModelConfigs {
		if config.Overridden {
			return true
		}
	}
	return false
}

// OptionsFor devuelve los modelos que admite un knob: los del catálogo, limitados al proveedor que exige el knob
// (los chunkers).
func (c Catalog) OptionsFor(config ModelConfig) []string {
	var options []string
	for _, model := range c.AvailableModels {
		isClaude := strings.HasPrefix(model, "claude")
		switch config.Provider() {
		case "openai":
			if isClaude {
				continue
			}
		case "anthropic":
			if !isClaude {
				continue
			}
		}
		options = append(options, model)
	}
	return options
}
