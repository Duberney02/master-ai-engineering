package rag

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// schema es el esquema de Rails (`db/schema.rb`) sin cambios: si el volumen ya lo tiene (creado por Rails) no se
// toca, y si está vacío se crea igual.
const schema = `
CREATE TABLE IF NOT EXISTS chunking_comparisons (
	id bigserial PRIMARY KEY,
	strategies jsonb NOT NULL DEFAULT '[]'::jsonb,
	queries jsonb NOT NULL DEFAULT '[]'::jsonb,
	top_k integer NOT NULL DEFAULT 3,
	corpus_label character varying NOT NULL DEFAULT 'budgets',
	corpus_count integer NOT NULL DEFAULT 0,
	response_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
	duration_ms integer,
	created_at timestamp(6) without time zone NOT NULL,
	updated_at timestamp(6) without time zone NOT NULL
);
CREATE INDEX IF NOT EXISTS index_chunking_comparisons_on_created_at ON chunking_comparisons (created_at);
`

const columns = `id, strategies, queries, top_k, corpus_label, corpus_count, response_payload, duration_ms, created_at`

// PgStore guarda el historial en PostgreSQL.
type PgStore struct{ pool *pgxpool.Pool }

// NewPgStore abre el pool contra la base indicada (no conecta hasta el primer uso).
func NewPgStore(ctx context.Context, databaseURL string) (*PgStore, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, fmt.Errorf("base de datos del historial: %w", err)
	}
	return &PgStore{pool: pool}, nil
}

// NewPgStoreFromPool envuelve un pool existente (pruebas).
func NewPgStoreFromPool(pool *pgxpool.Pool) *PgStore { return &PgStore{pool: pool} }

// Close libera las conexiones.
func (s *PgStore) Close() { s.pool.Close() }

// Migrate crea la tabla si no existe (idempotente).
func (s *PgStore) Migrate(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, schema)
	return err
}

// Create guarda la ejecución.
func (s *PgStore) Create(ctx context.Context, comparison *Comparison) error {
	if err := comparison.Validate(); err != nil {
		return err
	}
	strategies, err := json.Marshal(nonNil(comparison.Strategies))
	if err != nil {
		return err
	}
	queries, err := json.Marshal(nonNil(comparison.Queries))
	if err != nil {
		return err
	}
	payload := comparison.ResponsePayload
	if len(payload) == 0 {
		payload = []byte("{}")
	}
	now := time.Now().UTC()
	err = s.pool.QueryRow(ctx, `
		INSERT INTO chunking_comparisons
			(strategies, queries, top_k, corpus_label, corpus_count, response_payload, duration_ms, created_at, updated_at)
		VALUES ($1::jsonb, $2::jsonb, $3, $4, $5, $6::jsonb, $7, $8, $8)
		RETURNING id, created_at`,
		string(strategies), string(queries), comparison.TopK, comparison.CorpusLabel, comparison.CorpusCount,
		string(payload), comparison.DurationMS, now,
	).Scan(&comparison.ID, &comparison.CreatedAt)
	if err != nil {
		return err
	}
	comparison.CreatedAt = comparison.CreatedAt.UTC()
	return nil
}

// Recent devuelve las últimas ejecuciones, la más reciente primero.
func (s *PgStore) Recent(ctx context.Context, limit int) ([]Comparison, error) {
	rows, err := s.pool.Query(ctx, `SELECT `+columns+` FROM chunking_comparisons ORDER BY created_at DESC, id DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	comparisons := []Comparison{}
	for rows.Next() {
		comparison, err := scan(rows)
		if err != nil {
			return nil, err
		}
		comparisons = append(comparisons, comparison)
	}
	return comparisons, rows.Err()
}

// Find devuelve una ejecución o ErrNotFound.
func (s *PgStore) Find(ctx context.Context, id int64) (*Comparison, error) {
	rows, err := s.pool.Query(ctx, `SELECT `+columns+` FROM chunking_comparisons WHERE id = $1`, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	if !rows.Next() {
		if err := rows.Err(); err != nil {
			return nil, err
		}
		return nil, ErrNotFound
	}
	comparison, err := scan(rows)
	if err != nil {
		return nil, err
	}
	return &comparison, nil
}

func scan(row pgx.Rows) (Comparison, error) {
	var (
		comparison                       Comparison
		strategies, queries, payloadJSON []byte
	)
	if err := row.Scan(&comparison.ID, &strategies, &queries, &comparison.TopK, &comparison.CorpusLabel,
		&comparison.CorpusCount, &payloadJSON, &comparison.DurationMS, &comparison.CreatedAt); err != nil {
		return Comparison{}, err
	}
	if err := json.Unmarshal(strategies, &comparison.Strategies); err != nil {
		return Comparison{}, errors.New("rag: estrategias guardadas inválidas")
	}
	if err := json.Unmarshal(queries, &comparison.Queries); err != nil {
		return Comparison{}, errors.New("rag: consultas guardadas inválidas")
	}
	comparison.ResponsePayload = payloadJSON
	comparison.CreatedAt = comparison.CreatedAt.UTC()
	return comparison, nil
}

func nonNil(values []string) []string {
	if values == nil {
		return []string{}
	}
	return values
}
