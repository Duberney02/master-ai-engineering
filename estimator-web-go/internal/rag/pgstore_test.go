package rag

import (
	"context"
	"errors"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// testStore abre el PostgreSQL efímero de `web-test` (TEST_DATABASE_URL), con la tabla vacía.
func testStore(t *testing.T) *PgStore {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL no definida: las pruebas de persistencia se ejecutan con `web-test`")
	}
	pool, err := pgxpool.New(context.Background(), url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	store := NewPgStoreFromPool(pool)
	if err := store.Migrate(context.Background()); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(context.Background(), "TRUNCATE chunking_comparisons RESTART IDENTITY"); err != nil {
		t.Fatal(err)
	}
	return store
}

func TestStorePersistsTheRequestAndTheFullResponse(t *testing.T) {
	store := testStore(t)
	ctx := context.Background()
	duration := 1500
	comparison := &Comparison{
		Strategies: []string{"structural", "hierarchical"}, Queries: []string{"oauth"}, TopK: 3, CorpusLabel: "budgets_sample", CorpusCount: 18,
		DurationMS: &duration, ResponsePayload: compareBody([]string{"structural", "hierarchical"}, []string{"oauth"}, 0),
	}
	if err := store.Create(ctx, comparison); err != nil {
		t.Fatal(err)
	}
	if comparison.ID == 0 || !comparison.Saved() || comparison.CreatedAt.Location() != time.UTC {
		t.Errorf("Create debe rellenar ID y fecha UTC: %+v", comparison)
	}

	reloaded, err := store.Find(ctx, comparison.ID)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(reloaded.Strategies, []string{"structural", "hierarchical"}) || !reflect.DeepEqual(reloaded.Queries, []string{"oauth"}) ||
		reloaded.TopK != 3 || reloaded.CorpusLabel != "budgets_sample" || reloaded.CorpusCount != 18 || *reloaded.DurationMS != 1500 {
		t.Errorf("recargada: %+v", reloaded)
	}
	if reloaded.Response().StatsFor("structural").NChunks != 10 {
		t.Error("la respuesta completa debe sobrevivir como JSONB")
	}
}

func TestStoreLeavesDurationNullAndDefaultsEmptyLists(t *testing.T) {
	store := testStore(t)
	comparison := &Comparison{Strategies: []string{"structural"}, TopK: 3, CorpusLabel: "budgets"}
	if err := store.Create(context.Background(), comparison); err != nil {
		t.Fatal(err)
	}
	reloaded, _ := store.Find(context.Background(), comparison.ID)
	if reloaded.DurationMS != nil || reloaded.Queries == nil || len(reloaded.Queries) != 0 || string(reloaded.ResponsePayload) != "{}" {
		t.Errorf("valores por defecto: %+v payload %s", reloaded, reloaded.ResponsePayload)
	}
}

func TestStoreRejectsInvalidRecords(t *testing.T) {
	store := testStore(t)
	for _, invalid := range []*Comparison{{TopK: 3}, {Strategies: []string{"a"}, TopK: 0}, {Strategies: []string{"a"}, TopK: 11}} {
		if err := store.Create(context.Background(), invalid); err == nil {
			t.Errorf("%+v debería rechazarse", invalid)
		}
	}
}

func TestStoreListsNewestFirstWithALimit(t *testing.T) {
	store := testStore(t)
	ctx := context.Background()
	for _, strategy := range []string{"structural", "recursive", "semantic"} {
		if err := store.Create(ctx, &Comparison{Strategies: []string{strategy}, TopK: 3}); err != nil {
			t.Fatal(err)
		}
		time.Sleep(5 * time.Millisecond)
	}
	recent, err := store.Recent(ctx, 2)
	if err != nil || len(recent) != 2 || recent[0].Strategies[0] != "semantic" || recent[1].Strategies[0] != "recursive" {
		t.Fatalf("recientes: %+v %v", recent, err)
	}
	empty := testStore(t)
	if recent, err := empty.Recent(ctx, 20); err != nil || recent == nil || len(recent) != 0 {
		t.Errorf("un historial vacío es una lista vacía: %v %v", recent, err)
	}
}

func TestStoreFindMissingIsNotFound(t *testing.T) {
	store := testStore(t)
	if _, err := store.Find(context.Background(), 0); !errors.Is(err, ErrNotFound) {
		t.Errorf("se esperaba ErrNotFound: %v", err)
	}
}

func TestMigrateIsIdempotentAndKeepsExistingRows(t *testing.T) {
	store := testStore(t)
	ctx := context.Background()
	if err := store.Create(ctx, &Comparison{Strategies: []string{"structural"}, TopK: 3}); err != nil {
		t.Fatal(err)
	}
	if err := store.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	if recent, _ := store.Recent(ctx, 20); len(recent) != 1 {
		t.Error("migrar de nuevo no debe borrar filas")
	}
}

func TestStoreReadsLegacyComparisonsWithoutChangingIDsOrPayload(t *testing.T) {
	store := testStore(t)
	ctx := context.Background()
	// Las fechas fijas distinguen el orden cronológico del orden por ID y cubren el desempate.
	const olderID int64 = 9007199254740995
	const firstID int64 = 9007199254740993
	const secondID int64 = 9007199254740994
	payload := compareBody([]string{"hierarchical"}, []string{"oauth"}, 0)
	_, err := store.pool.Exec(ctx, `
		INSERT INTO chunking_comparisons
			(id, strategies, queries, top_k, corpus_label, corpus_count, response_payload,
			 duration_ms, created_at, updated_at)
		VALUES
			($1, '["hierarchical"]', '["oauth"]', 3, 'budgets_sample', 18, $4::jsonb,
			 1500, '2026-01-01 10:00:00', '2026-01-01 10:00:00'),
			($2, '["structural"]', '[]', 1, 'budgets_sample', 18, '{}',
			 NULL, '2026-01-02 10:00:00', '2026-01-02 10:00:00'),
			($3, '["recursive"]', '[]', 2, 'budgets_sample', 18, '{}',
			 NULL, '2026-01-02 10:00:00', '2026-01-02 10:00:00')`, olderID, firstID, secondID, string(payload))
	if err != nil {
		t.Fatal(err)
	}

	reopened, err := NewPgStore(ctx, os.Getenv("TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(reopened.Close)
	if err := reopened.Migrate(ctx); err != nil {
		t.Fatal(err)
	}
	recent, err := reopened.Recent(ctx, 20)
	if err != nil {
		t.Fatal(err)
	}
	var ids []int64
	for _, comparison := range recent {
		ids = append(ids, comparison.ID)
	}
	if want := []int64{secondID, firstID, olderID}; !reflect.DeepEqual(ids, want) {
		t.Fatalf("IDs en orden de historial: %v, se esperaba %v", ids, want)
	}
	detail, err := reopened.Find(ctx, olderID)
	if err != nil {
		t.Fatal(err)
	}
	if detail.ID != olderID || detail.TopK != 3 || detail.CorpusLabel != "budgets_sample" || detail.CorpusCount != 18 ||
		detail.DurationMS == nil || *detail.DurationMS != 1500 ||
		!detail.CreatedAt.Equal(time.Date(2026, 1, 1, 10, 0, 0, 0, time.UTC)) ||
		!reflect.DeepEqual(detail.Strategies, []string{"hierarchical"}) ||
		!reflect.DeepEqual(detail.Queries, []string{"oauth"}) {
		t.Fatalf("detalle histórico: %+v", detail)
	}
	var idType string
	var storedPayloadMatches, returnedPayloadMatches bool
	// JSONB compara la estructura completa sin depender del formato ni convertir números a float64.
	err = store.pool.QueryRow(ctx, `
		SELECT pg_typeof(id)::text, response_payload = $2::jsonb, $3::jsonb = $2::jsonb
		FROM chunking_comparisons WHERE id = $1`, olderID, string(payload), string(detail.ResponsePayload)).
		Scan(&idType, &storedPayloadMatches, &returnedPayloadMatches)
	if err != nil {
		t.Fatal(err)
	}
	if idType != "bigint" || !storedPayloadMatches || !returnedPayloadMatches {
		t.Fatalf("tipo del ID: %s, payload almacenado íntegro: %t, payload devuelto íntegro: %t; detalle: %s",
			idType, storedPayloadMatches, returnedPayloadMatches, detail.ResponsePayload)
	}
}
