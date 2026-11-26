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

// Recorrido completo del laboratorio contra PostgreSQL por la API REST: opciones → comparación (201 y Location) →
// detalle → historial → ID ausente, con la API de IA simulada. Sustituye al recorrido HTML formulario → redirección →
// detalle → historial.
func TestLabEndToEndWithPostgreSQL(t *testing.T) {
	h := newHarness(t, withStore(pgStore(t)))
	stubCompare(h, compareBody([]string{"structural", "hierarchical", "contextual_retrieval"}, []string{"oauth"}, 0.14))

	h.wantREST(h.rest("GET", labAPI+"/options", ""), 200)
	created := h.rest("POST", labAPI, `{"strategies":["structural","hierarchical","contextual_retrieval"],"queries":["oauth"],"top_k":3}`)
	h.wantREST(created, 201)
	if created.header.Get("Location") != labAPI+"/1" || created.json(t)["id"] != "1" {
		t.Fatalf("alta: Location=%q cuerpo=%s", created.header.Get("Location"), abbreviate(string(created.body)))
	}

	detail := h.rest("GET", created.header.Get("Location"), "")
	h.wantREST(detail, 200)
	body := detail.json(t)
	result := body["result"].(map[string]any)
	if got := len(result["stats_per_strategy"].([]any)); got != 3 || body["id"] != "1" || body["created_at"] == nil || body["corpus_count"] == nil {
		t.Errorf("detalle: estadísticas=%d %v", got, body)
	}
	if len(h.api.requests("POST", comparePath)) != 1 {
		t.Errorf("el detalle no debe recalcular: %d llamadas", len(h.api.requests("POST", comparePath)))
	}

	history := h.rest("GET", labAPI, "")
	h.wantREST(history, 200)
	items := history.json(t)["items"].([]any)
	if len(items) != 1 || items[0].(map[string]any)["id"] != "1" || !strings.Contains(strings.Join(toStrings(items[0].(map[string]any)["strategies"]), ","), "structural,hierarchical,contextual_retrieval") {
		t.Errorf("historial: %s", abbreviate(string(history.body)))
	}

	h.wantREST(h.rest("GET", labAPI+"/2", ""), 404)
}

func TestLabHistoryPersistsAcrossServerInstances(t *testing.T) {
	store := pgStore(t)
	first := newHarness(t, withStore(store))
	stubCompare(first, compareBody([]string{"structural"}, nil, 0))
	first.wantREST(first.rest("POST", labAPI, `{"strategies":["structural"]}`), 201)

	second := newHarness(t, withStore(store))
	history := second.rest("GET", labAPI, "")

	second.wantREST(history, 200)
	body := history.json(t)
	if items := body["items"].([]any); len(items) != 1 || items[0].(map[string]any)["id"] != "1" || body["warning"] != nil {
		t.Errorf("historial tras reinicio: %s", abbreviate(string(history.body)))
	}
}

// DA-27: los IDs de comparación superiores a 2^53 − 1 conservan sus dígitos en el alta, `Location`, el listado y el
// detalle, y PostgreSQL mantiene el tipo y el valor. Un segundo servidor sobre la misma base representa el reinicio.
func TestLabLargeIDsKeepExactDigitsThroughGoAndPostgreSQL(t *testing.T) {
	store := pgStore(t)
	pool, err := pgxpool.New(context.Background(), os.Getenv("TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	const previous, next = "9007199254740993", "9007199254741001" // 2^53 + 1 y el siguiente valor de la secuencia
	payload, _ := jsonMarshal(compareBody([]string{"structural", "hierarchical"}, []string{"oauth"}, 0))
	if _, err := pool.Exec(context.Background(), `
		INSERT INTO chunking_comparisons (id, strategies, queries, top_k, corpus_label, corpus_count, response_payload, duration_ms, created_at, updated_at)
		VALUES (9007199254740993, '["structural","hierarchical"]', '["oauth"]', 4, 'budgets_previos', 18, $1::jsonb, 3200, '2026-10-05 10:00:00', '2026-10-05 10:00:00')`,
		string(payload)); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(context.Background(), `SELECT setval('chunking_comparisons_id_seq', 9007199254741000)`); err != nil {
		t.Fatal(err)
	}

	h := newHarness(t, withStore(store))
	stubCompare(h, compareBody([]string{"structural"}, nil, 0))
	created := h.rest("POST", labAPI, `{"strategies":["structural"]}`)
	h.wantREST(created, 201)
	if !strings.Contains(string(created.body), `"id":"`+next+`"`) || created.header.Get("Location") != labAPI+"/"+next {
		t.Fatalf("alta: Location=%q cuerpo=%s", created.header.Get("Location"), abbreviate(string(created.body)))
	}

	restarted := newHarness(t, withStore(store)) // otro servidor, la misma base
	list := restarted.rest("GET", labAPI, "")
	restarted.wantREST(list, 200)
	if !strings.Contains(string(list.body), `"id":"`+previous+`"`) || !strings.Contains(string(list.body), `"id":"`+next+`"`) {
		t.Errorf("listado: %s", abbreviate(string(list.body)))
	}
	ids := []string{}
	for _, item := range list.json(t)["items"].([]any) {
		ids = append(ids, item.(map[string]any)["id"].(string))
	}
	if strings.Join(ids, ",") != next+","+previous {
		t.Errorf("orden del listado: %v", ids)
	}
	detail := restarted.rest("GET", created.header.Get("Location"), "")
	restarted.wantREST(detail, 200)
	if !strings.Contains(string(detail.body), `"id":"`+next+`"`) {
		t.Errorf("detalle nuevo: %s", abbreviate(string(detail.body)))
	}
	old := restarted.rest("GET", labAPI+"/"+previous, "")
	restarted.wantREST(old, 200)
	body := old.json(t)
	if body["id"] != previous || body["corpus_label"] != "budgets_previos" || body["corpus_count"] != float64(18) || body["duration_ms"] != float64(3200) ||
		body["top_k"] != float64(4) || body["created_at"] != "2026-10-05T10:00:00Z" {
		t.Errorf("registro previo: %v", body)
	}
	if got := len(body["result"].(map[string]any)["stats_per_strategy"].([]any)); got != 2 || len(restarted.api.calls) != 0 {
		t.Errorf("el detalle no debe recalcular: estadísticas=%d llamadas a IA=%d", got, len(restarted.api.calls))
	}

	var dataType, row string
	if err := pool.QueryRow(context.Background(), `SELECT data_type FROM information_schema.columns WHERE table_name='chunking_comparisons' AND column_name='id'`).Scan(&dataType); err != nil || dataType != "bigint" {
		t.Errorf("tipo de la columna: %q %v", dataType, err)
	}
	if err := pool.QueryRow(context.Background(), `SELECT string_agg(id::text, ',' ORDER BY id) FROM chunking_comparisons`).Scan(&row); err != nil || row != previous+","+next {
		t.Errorf("valores en PostgreSQL: %q %v", row, err)
	}
}

// Persistencia atómica en PostgreSQL: la cancelación durante el cálculo, un contexto cancelado y una ejecución inválida
// no dejan filas parciales; una ejecución guardada es una única fila completa.
func TestLabAtomicPersistenceInPostgreSQL(t *testing.T) {
	store := pgStore(t)
	count := func() int {
		rows, err := store.Recent(context.Background(), 50)
		if err != nil {
			t.Fatal(err)
		}
		return len(rows)
	}
	if posts := cancelDuringCompare(t, store); posts != 1 || count() != 0 {
		t.Fatalf("cancelación durante el cálculo: POST=%d filas=%d", posts, count())
	}
	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	payload, _ := jsonMarshal(compareBody([]string{"structural"}, nil, 0))
	row := rag.Comparison{Strategies: []string{"structural"}, TopK: 3, CorpusLabel: "x", CorpusCount: 1, ResponsePayload: payload}
	if err := store.Create(canceled, &row); err == nil || count() != 0 {
		t.Fatalf("contexto cancelado: error=%v filas=%d", err, count())
	}
	for _, invalid := range []rag.Comparison{{TopK: 3}, {Strategies: []string{"structural"}, TopK: 11}, {Strategies: []string{"structural"}, TopK: 0}} {
		if err := store.Create(context.Background(), &invalid); err == nil || count() != 0 {
			t.Fatalf("ejecución inválida %+v: error=%v filas=%d", invalid, err, count())
		}
	}
	h := newHarness(t, withStore(store))
	stubCompare(h, compareBody([]string{"structural"}, nil, 0))
	h.wantREST(h.rest("POST", labAPI, `{"strategies":["structural"]}`), 201)
	rows, err := store.Recent(context.Background(), 50)
	if err != nil || len(rows) != 1 || rows[0].CreatedAt.IsZero() || len(rows[0].ResponsePayload) == 0 || rows[0].DurationMS == nil {
		t.Fatalf("una ejecución guardada es una fila completa: %v %+v", err, rows)
	}
}
