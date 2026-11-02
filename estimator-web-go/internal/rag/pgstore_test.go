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
