package web

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"estimator-web/internal/rag"
)

// pgStore abre el PostgreSQL efímero de `web-test` con la tabla vacía: la prueba de extremo a extremo del historial
// del Chunking Lab usa la base real, no la de memoria.
func pgStore(t *testing.T) rag.Store {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL no definida: se ejecuta con `web-test`")
	}
	pool, err := pgxpool.New(context.Background(), url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	store := rag.NewPgStoreFromPool(pool)
	if err := store.Migrate(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(context.Background(), "TRUNCATE chunking_comparisons RESTART IDENTITY"); err != nil {
		t.Fatal(err)
	}
	return store
}

// Recorrido completo del laboratorio contra PostgreSQL: formulario → comparación → redirección → detalle → historial,
// sin Rails y con la API de IA simulada.
func TestLabEndToEndWithPostgreSQL(t *testing.T) {
	h := newHarness(t, withStore(pgStore(t)))
	stubCompare(h, compareBody([]string{"structural", "hierarchical", "contextual_retrieval"}, []string{"oauth"}, 0.14))

	p := h.get("/rag/chunking_comparisons/new")
	h.wantStatus(p, 200)

	p = h.post("/rag/chunking_comparisons", runValues(map[string][]string{
		"strategies[]": {"structural", "hierarchical", "contextual_retrieval"}, "queries[]": {"oauth"},
	}))
	h.wantStatus(p, 302)
	if p.location != "/rag/chunking_comparisons/1" {
		t.Fatalf("redirección: %q", p.location)
	}

	detail := h.get(p.location)
	h.wantStatus(detail, 200)
	if got := detail.count(`<tr id="stats-`); got != 3 {
		t.Errorf("filas de estadísticas: %d", got)
	}
	if text, _ := detail.textOf("cost-contextual_retrieval"); !strings.Contains(text, "0,140000 USD") {
		t.Errorf("coste: %q", text)
	}
	h.wantContains(detail, "Ejecutada el", "aria-label=\"Similitud 71%\"")

	history := h.get("/rag/chunking_comparisons")
	h.wantStatus(history, 200)
	h.wantContains(history, `<a href="/rag/chunking_comparisons/1">Ver</a>`, "Estructural, Jerárquico, Contextual retrieval", "0,140000 USD")

	h.wantStatus(h.get("/rag/chunking_comparisons/2"), 404)
}

func TestLabHistoryPersistsAcrossServerInstances(t *testing.T) {
	store := pgStore(t)
	first := newHarness(t, withStore(store))
	stubCompare(first, compareBody([]string{"structural"}, nil, 0))
	first.wantStatus(first.post("/rag/chunking_comparisons", runValues(map[string][]string{"strategies[]": {"structural"}})), 302)

	second := newHarness(t, withStore(store))
	history := second.get("/rag/chunking_comparisons")

	second.wantStatus(history, 200)
	second.wantContains(history, `<a href="/rag/chunking_comparisons/1">Ver</a>`)
	second.wantAbsent(history, `id="lab-history-empty"`)
}
