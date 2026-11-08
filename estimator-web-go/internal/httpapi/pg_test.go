package httpapi

import (
	"context"
	"os"
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

// Recorrido completo del laboratorio contra PostgreSQL: opciones → comparación → detalle → historial.
func TestLabEndToEndWithPostgreSQL(t *testing.T) {
	h := newHarness(t, withStore(pgStore(t)))
	stubCompare(h, compareBody([]string{"structural", "hierarchical", "contextual_retrieval"}, []string{"oauth"}, 0.14))

	h.wantStatus(h.get("/api/chunking-comparisons/options"), 200)

	created := h.sendJSON("POST", "/api/chunking-comparisons", map[string]any{
		"strategies": []string{"structural", "hierarchical", "contextual_retrieval"}, "queries": []string{"oauth"},
	})
	h.wantStatus(created, 201)
	if body := created.object(t); body["id"].(float64) != 1 || body["saved"] != true || body["total_ingestion_cost_usd"].(float64) != 0.14 {
		t.Fatalf("creada: %v", body)
	}

	detail := h.get("/api/chunking-comparisons/1")
	h.wantStatus(detail, 200)
	stats := detail.object(t)["response"].(map[string]any)["stats_per_strategy"].(map[string]any)
	if len(stats) != 3 {
		t.Errorf("estadísticas: %d", len(stats))
	}

	history := h.get("/api/chunking-comparisons")
	h.wantStatus(history, 200)
	if len(history.list(t)) != 1 {
		t.Errorf("historial: %s", history.body)
	}
	h.wantStatus(h.get("/api/chunking-comparisons/2"), 404)
}

func TestLabHistoryPersistsAcrossServerInstances(t *testing.T) {
	store := pgStore(t)
	first := newHarness(t, withStore(store))
	stubCompare(first, compareBody([]string{"structural"}, nil, 0))
	first.wantStatus(first.sendJSON("POST", "/api/chunking-comparisons", map[string]any{"strategies": []string{"structural"}}), 201)

	second := newHarness(t, withStore(store))
	history := second.get("/api/chunking-comparisons")

	second.wantStatus(history, 200)
	if len(history.list(t)) != 1 {
		t.Errorf("historial tras reiniciar: %s", history.body)
	}
}
