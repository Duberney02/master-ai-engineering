package web

import (
	"context"
	"estimator-web/internal/config"
	"regexp"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestTheLandingPageIsTheDashboardWithOneCardPerContext(t *testing.T) {
	h := newHarness(t)
	p := h.get("/")

	h.wantStatus(p, 200)
	for id, link := range map[string]string{
		"home-estimations": `href="/estimations/new"`, "home-rag": `href="/rag/chunking_comparisons/new"`, "home-settings": `href="/ai_settings"`,
	} {
		if text, ok := p.textOf(id); !ok || text == "" {
			t.Errorf("falta la tarjeta %s", id)
		}
		if !strings.Contains(p.body[strings.Index(p.body, `id="`+id+`"`):], link) {
			t.Errorf("la tarjeta %s no enlaza a %s", id, link)
		}
	}
	if !strings.Contains(p.body, "<title>Inicio · Estimador de proyectos</title>") {
		t.Error("título de la pantalla de inicio")
	}
}

func TestTheHomePageDoesNotCallTheAIServiceForItsContent(t *testing.T) {
	h := newHarness(t)
	h.get("/")

	if h.api.count("GET", "/api/v1/estimations") != 0 || h.api.count("POST", "/api/v1/sessions") != 0 || h.api.count("GET", "/api/v1/prompts/estimation") != 0 {
		t.Error("el inicio solo puede consultar el modelo primario de la barra")
	}
}

func TestTheLayoutRendersWithoutTheServiceThePrimaryModelBadgeJustDisappears(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("GET", configPath, reply{drop: true})

	p := h.get("/")

	h.wantStatus(p, 200)
	h.wantAbsent(p, `id="primary-model"`)
	if got := p.count(`<nav>[\s\S]*?</nav>`); got != 1 || p.count(`<a (class="active" aria-current="page" )?href=`) < 5 {
		t.Error("la barra de navegación debe tener al menos 5 enlaces")
	}
}

func TestTheNavbarShowsTheEffectivePrimaryModel(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", configPath, 200, configBody(map[string]string{"primary_model": "gpt-4o"}))

	p := h.get("/")

	if text, _ := p.textOf("primary-model"); text != "gpt-4o" {
		t.Errorf("indicador: %q", text)
	}
	h.wantContains(p, `class="model-badge"`, `href="/ai_settings"`)
}

func TestTheNavbarMarksTheActiveSectionOnEveryScreen(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{})
	active := regexp.MustCompile(`<a class="active" aria-current="page" href="[^"]+">([^<]+)</a>`)
	cases := map[string]string{
		"/": "Inicio", "/estimations/new": "Nueva estimación", "/estimations": "Historial",
		"/rag/chunking_comparisons/new": "Chunking Lab", "/rag/chunking_comparisons": "Chunking Lab", "/ai_settings": "Ajustes",
	}
	for path, label := range cases {
		p := h.get(path)
		matches := active.FindAllStringSubmatch(p.body, -1)
		if len(matches) != 1 || matches[0][1] != label {
			t.Errorf("%s: secciones activas %v, se esperaba solo %q", path, matches, label)
		}
		if got := p.count(`aria-current="page"`); got != 1 {
			t.Errorf("%s: aria-current aparece %d veces", path, got)
		}
	}
}

func TestResubmittingTheFormMarksHistoryLikeRails(t *testing.T) {
	h := newHarness(t)
	p := h.post("/estimations", formValues(map[string]string{"description": "corta"}))

	if got := active(p); got != "Historial" {
		t.Errorf("tras reenviar el formulario Rails marca «Historial»: %q", got)
	}
}

func active(p *page) string {
	match := regexp.MustCompile(`<a class="active" aria-current="page" href="[^"]+">([^<]+)</a>`).FindStringSubmatch(p.body)
	if match == nil {
		return ""
	}
	return match[1]
}

// --- Indicador del modelo primario: caché de 15 s ---

func TestTheBadgeIsCachedSoTheNavbarCostsAtMostOneCallPerWindow(t *testing.T) {
	h := newHarness(t)

	h.get("/")
	h.get("/")
	h.get("/")

	if got := h.api.count("GET", configPath); got != 1 {
		t.Errorf("llamadas a la configuración: %d", got)
	}
}

func TestAFailureIsCachedTooSoADeadServiceIsNotRetriedOnEveryPage(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("GET", configPath, reply{drop: true})

	h.get("/")
	h.get("/")
	h.get("/")

	if got := h.api.count("GET", configPath); got != 1 {
		t.Errorf("llamadas a la configuración: %d", got)
	}
}

func TestTheBadgeIsNilOnATimeoutAServerErrorOrAMalformedResponse(t *testing.T) {
	cases := map[string]reply{
		"tiempo agotado":        {status: 200, body: `{}`, delay: 400 * time.Millisecond},
		"error del servidor":    {status: 500, body: "boom"},
		"respuesta mal formada": {status: 200, body: `{"x":1}`},
	}
	for name, answer := range cases {
		h := newHarness(t, withConfig(func(c *config.Config) { c.BadgeTimeout = 100 * time.Millisecond }))
		h.api.stubReply("GET", configPath, answer)

		p := h.get("/")

		h.wantStatus(p, 200)
		h.wantAbsent(p, `id="primary-model"`)
		_ = name
	}
}

func TestTheBadgeCacheExpiresAfterTheWindowAndCanBeInvalidated(t *testing.T) {
	now := time.Now()
	var calls atomic.Int32
	cache := newBadgeCache(15*time.Second, func() time.Time { return now }, func(ctxValue context.Context) string {
		calls.Add(1)
		return "gpt-4o-mini"
	})
	ctx := context.Background()

	cache.Get(ctx)
	cache.Get(ctx)
	if calls.Load() != 1 {
		t.Fatalf("llamadas dentro de la ventana: %d", calls.Load())
	}
	now = now.Add(16 * time.Second)
	cache.Get(ctx)
	if calls.Load() != 2 {
		t.Errorf("debe volver a consultar tras 15 s: %d", calls.Load())
	}
	cache.Invalidate()
	cache.Get(ctx)
	if calls.Load() != 3 {
		t.Errorf("tras invalidar debe volver a consultar: %d", calls.Load())
	}
}
