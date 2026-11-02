package ai

import (
	"reflect"
	"testing"

	"estimator-web/internal/jsondoc"
)

var knobs = []string{"primary_model", "fallback_model", "critic_model", "metadata_model", "summary_model", "propositional_chunker_model", "contextual_chunker_model"}

// configBody es la respuesta de GET /api/v1/config/models.
func configBody(overrides map[string]string) jsondoc.Doc {
	defaults := map[string]any{"fallback_model": nil, "propositional_chunker_model": "gpt-4o-mini", "contextual_chunker_model": "claude-sonnet-4-5"}
	models := map[string]any{}
	for _, key := range knobs {
		def, ok := defaults[key]
		if !ok {
			def = "gpt-4o-mini"
		}
		effective, overridden := overrides[key]
		if !overridden && def != nil {
			effective = def.(string)
		}
		models[key] = map[string]any{"effective": effective, "default": def, "overridden": overridden}
	}
	return jsondoc.Doc{
		"models": models, "available_models": []any{"gpt-4o-mini", "gpt-4o", "claude-haiku-4-5", "claude-sonnet-4-5"},
		"embedding_model": "text-embedding-3-small", "embedding_model_note": "Solo lectura: cambiarlo invalidaría todos los vectores guardados.",
	}
}

func TestKeepsTheSevenKnobsInScreenOrder(t *testing.T) {
	catalog := FromDoc(configBody(nil))
	var keys []string
	for _, config := range catalog.ModelConfigs {
		keys = append(keys, config.Key)
	}
	if !reflect.DeepEqual(keys, knobs) || !reflect.DeepEqual(Keys(), knobs) {
		t.Errorf("knobs: %v", keys)
	}
}

func TestEmbeddingModelIsReadOnlyAndNotAKnob(t *testing.T) {
	catalog := FromDoc(configBody(nil))
	if catalog.EmbeddingModel != "text-embedding-3-small" || catalog.EmbeddingModelNote == "" || IsKey("embedding_model") {
		t.Errorf("modelo de embeddings: %+v", catalog)
	}
}

func TestExposesEffectiveDefaultAndOverriddenPerKnob(t *testing.T) {
	config := FromDoc(configBody(map[string]string{"primary_model": "gpt-4o"})).ModelConfigs[0]
	if config.Effective != "gpt-4o" || config.Default != "gpt-4o-mini" || !config.Overridden || config.Label() != "Modelo primario" || config.Selected() != "gpt-4o" {
		t.Errorf("knob: %+v", config)
	}
	if FromDoc(configBody(nil)).ModelConfigs[0].Selected() != "" {
		t.Error("sin override no se preselecciona ningún modelo")
	}
}

func TestPrimaryModelAndAnyOverriddenSummarizeTheSnapshot(t *testing.T) {
	catalog := FromDoc(configBody(nil))
	if catalog.PrimaryModel() != "gpt-4o-mini" || catalog.AnyOverridden() || !FromDoc(configBody(map[string]string{"critic_model": "gpt-4o"})).AnyOverridden() {
		t.Error("resumen de la instantánea")
	}
}

func TestChunkerKnobsOnlyOfferModelsOfTheirProvider(t *testing.T) {
	catalog := FromDoc(configBody(nil))
	byKey := map[string]ModelConfig{}
	for _, config := range catalog.ModelConfigs {
		byKey[config.Key] = config
	}
	if got := catalog.OptionsFor(byKey["propositional_chunker_model"]); !reflect.DeepEqual(got, []string{"gpt-4o-mini", "gpt-4o"}) {
		t.Errorf("proposicional: %v", got)
	}
	if got := catalog.OptionsFor(byKey["contextual_chunker_model"]); !reflect.DeepEqual(got, []string{"claude-haiku-4-5", "claude-sonnet-4-5"}) {
		t.Errorf("contextual: %v", got)
	}
	if got := catalog.OptionsFor(byKey["primary_model"]); !reflect.DeepEqual(got, catalog.AvailableModels) {
		t.Errorf("primario: %v", got)
	}
}

func TestKnobsMissingFromTheResponseAreSkipped(t *testing.T) {
	body := configBody(nil)
	delete(body["models"].(map[string]any), "fallback_model")
	if got := len(FromDoc(body).ModelConfigs); got != 6 {
		t.Errorf("knobs: %d", got)
	}
}
