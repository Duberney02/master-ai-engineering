package web

import (
	"net/url"
	"strings"
	"testing"
)

const configPath = "/api/v1/config/models"

func TestSettingsShowListsTheSevenKnobsWithTheirDefaultAndEffectiveModel(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", configPath, 200, configBody(map[string]string{"critic_model": "gpt-4o"}))

	p := h.get("/ai_settings")

	h.wantStatus(p, 200)
	if got := p.count(`<tr id="knob-`); got != 7 {
		t.Errorf("filas: %d", got)
	}
	if text, _ := p.textOf("knob-critic_model"); !strings.Contains(text, "gpt-4o") || !strings.Contains(text, "override") {
		t.Errorf("crítico: %q", text)
	}
	if text, _ := p.textOf("knob-primary_model"); strings.Contains(text, "override") {
		t.Errorf("el primario no tiene override: %q", text)
	}
	if text, _ := p.textOf("embedding-model"); !strings.Contains(text, "text-embedding-3-small") || !strings.Contains(text, "invalidaría") {
		t.Errorf("embeddings: %q", text)
	}
}

func TestEachSelectOffersAnEmptyOptionThatMeansResetToTheDefault(t *testing.T) {
	h := newHarness(t)
	p := h.get("/ai_settings")

	h.wantContains(p, `<option value="">Valor por defecto (gpt-4o-mini)</option>`, `<option value="gpt-4o">gpt-4o</option>`, `name="models[primary_model]"`, `id="models_primary_model"`)
}

func TestAnOverriddenKnobIsPreselected(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", configPath, 200, configBody(map[string]string{"primary_model": "gpt-4o"}))

	p := h.get("/ai_settings")

	h.wantContains(p, `<option value="gpt-4o" selected="selected">gpt-4o</option>`)
}

func TestChunkerSelectsOnlyOfferModelsOfTheirProvider(t *testing.T) {
	h := newHarness(t)
	p := h.get("/ai_settings")

	selectOf := func(key string) string {
		start := strings.Index(p.body, `id="models_`+key+`"`)
		end := strings.Index(p.body[start:], "</select>")
		return p.body[start : start+end]
	}
	propositional, contextual := selectOf("propositional_chunker_model"), selectOf("contextual_chunker_model")
	if strings.Contains(propositional, "claude-sonnet-4-5") || !strings.Contains(propositional, `value="gpt-4o"`) {
		t.Errorf("proposicional: %s", propositional)
	}
	if strings.Contains(contextual, `value="gpt-4o"`) || !strings.Contains(contextual, "claude-sonnet-4-5") {
		t.Errorf("contextual: %s", contextual)
	}
}

func TestUpdateSendsEveryKnobWithBlanksAsNullsAndConfirms(t *testing.T) {
	h := newHarness(t)
	h.api.stub("PUT", configPath, func(apiCall) reply { return jsonReply(configBody(map[string]string{"primary_model": "gpt-4o"})) })

	p := h.patch("/ai_settings", url.Values{"models[primary_model]": {"gpt-4o"}, "models[critic_model]": {""}})

	h.wantStatus(p, 302)
	if p.location != "/ai_settings" {
		t.Errorf("redirección: %q", p.location)
	}
	calls := h.api.requests("PUT", configPath)
	if len(calls) != 1 {
		t.Fatalf("peticiones PUT: %d", len(calls))
	}
	models := jsonBody(t, calls[0])["models"].(map[string]any)
	if len(models) != 2 || models["primary_model"] != "gpt-4o" || models["critic_model"] != nil {
		t.Errorf("cuerpo: %v", models)
	}
	if !strings.HasPrefix(calls[0].contentType, "application/json") {
		t.Errorf("Content-Type: %s", calls[0].contentType)
	}

	p = h.get(p.location)
	if text, _ := p.textOf("flash-notice"); !strings.Contains(text, "Modelos actualizados") {
		t.Errorf("aviso: %q", text)
	}
	if again := h.get("/ai_settings"); again.has(`id="flash-notice"`) {
		t.Error("el aviso debe mostrarse una sola vez")
	}
}

func TestSavingRefreshesTheNavbarIndicatorAtOnce(t *testing.T) {
	h := newHarness(t)
	p := h.get("/ai_settings")
	if text, _ := p.textOf("primary-model"); text != "gpt-4o-mini" {
		t.Fatalf("indicador inicial: %q", text)
	}

	h.api.stubJSON("PUT", configPath, 200, configBody(map[string]string{"primary_model": "gpt-4o"}))
	h.api.stubJSON("GET", configPath, 200, configBody(map[string]string{"primary_model": "gpt-4o"}))
	p = h.patch("/ai_settings", url.Values{"models[primary_model]": {"gpt-4o"}})
	p = h.get(p.location)

	if text, _ := p.textOf("primary-model"); text != "gpt-4o" {
		t.Errorf("indicador tras guardar: %q", text)
	}
}

func TestUpdateIgnoresUnknownKnobs(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("PUT", configPath, 200, configBody(nil))

	h.patch("/ai_settings", url.Values{"models[primary_model]": {"gpt-4o"}, "models[embedding_model]": {"x"}})

	models := jsonBody(t, h.api.requests("PUT", configPath)[0])["models"].(map[string]any)
	if len(models) != 1 || models["primary_model"] != "gpt-4o" {
		t.Errorf("cuerpo: %v", models)
	}
}

func TestUpdateWithoutAnyModelDoesNotCallTheService(t *testing.T) {
	h := newHarness(t)

	p := h.patch("/ai_settings", nil)

	h.wantStatus(p, 302)
	if h.api.count("PUT", configPath) != 0 {
		t.Error("no debe llamarse al servicio")
	}
	if text, _ := h.get(p.location).textOf("flash-alert"); !strings.Contains(text, "No hay ningún modelo que cambiar") {
		t.Errorf("aviso: %q", text)
	}
}

func TestPUTIsAcceptedAsWellAsPATCH(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("PUT", configPath, 200, configBody(nil))

	p := h.post("/ai_settings", url.Values{"_method": {"put"}, "models[primary_model]": {"gpt-4o"}})

	h.wantStatus(p, 302)
	if h.api.count("PUT", configPath) != 1 {
		t.Error("el PUT debe llegar a la API")
	}
}

func TestARejectedChangeIsShownWithTheAPIDetailAndTheFormIsKept(t *testing.T) {
	for _, status := range []int{400, 422} {
		h := newHarness(t)
		h.api.stubJSON("PUT", configPath, status, map[string]any{"detail": "El modelo 'claude-sonnet-4-5' requiere ANTHROPIC_API_KEY, que no está configurada"})

		p := h.patch("/ai_settings", url.Values{"models[primary_model]": {"claude-sonnet-4-5"}})

		h.wantStatus(p, 422)
		if text, _ := p.textOf("flash-alert"); !strings.Contains(text, "Cambio rechazado: El modelo") || !strings.Contains(text, "ANTHROPIC_API_KEY") {
			t.Errorf("aviso: %q", text)
		}
		if got := p.count(`<tr id="knob-`); got != 7 {
			t.Errorf("filas: %d", got)
		}
	}
}

func TestAnUnavailableConfigStoreIsA503WithTheAPIMessage(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("PUT", configPath, 503, map[string]any{"detail": "El almacén de configuración no está disponible"})

	p := h.patch("/ai_settings", url.Values{"models[primary_model]": {"gpt-4o"}})

	h.wantStatus(p, 503)
	if text, _ := p.textOf("flash-alert"); !strings.Contains(text, "almacén de configuración") {
		t.Errorf("aviso: %q", text)
	}
}

func TestAnUnreachableServiceOnUpdateIsASanitized503(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("PUT", configPath, reply{drop: true})

	p := h.patch("/ai_settings", url.Values{"models[primary_model]": {"gpt-4o"}})

	h.wantStatus(p, 503)
	if text, _ := p.textOf("flash-alert"); !strings.Contains(text, "No se pudo conectar") {
		t.Errorf("aviso: %q", text)
	}
	h.wantAbsent(p, h.api.server.URL)
}

func TestAnUnreachableServiceOnShowRendersThePageWithoutTheForm(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("GET", configPath, reply{drop: true})

	p := h.get("/ai_settings")

	h.wantStatus(p, 503)
	h.wantContains(p, `id="settings-unavailable"`)
	h.wantAbsent(p, `id="settings-form"`)
	if text, _ := p.textOf("flash-alert"); !strings.Contains(text, "No se pudo leer la configuración") {
		t.Errorf("aviso: %q", text)
	}
}

func TestAServerErrorOnShowIsABadGateway(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("GET", configPath, reply{status: 500, body: "boom"})

	p := h.get("/ai_settings")

	h.wantStatus(p, 502)
	h.wantContains(p, `id="settings-unavailable"`)
	h.wantAbsent(p, "boom")
}
