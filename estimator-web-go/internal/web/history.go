package web

import (
	"context"
	"errors"

	"estimator-web/internal/rag"
)

// Historial del Chunking Lab: el repositorio es opcional. Sin base de datos configurada, toda operación sobre el
// historial responde «no disponible» y la API REST degrada como ante un fallo de la base.

// historyLimit es el máximo de comparaciones que devuelve el listado.
const historyLimit = 20

var errNoStore = errors.New("web: sin base de datos para el historial")

func (s *Server) recent(ctx context.Context) ([]rag.Comparison, error) {
	if s.store == nil {
		return nil, errNoStore
	}
	return s.store.Recent(ctx, historyLimit)
}

func (s *Server) create(ctx context.Context, comparison *rag.Comparison) error {
	if s.store == nil {
		return errNoStore
	}
	return s.store.Create(ctx, comparison)
}

func (s *Server) find(ctx context.Context, id int64) (*rag.Comparison, error) {
	if s.store == nil {
		return nil, errNoStore
	}
	return s.store.Find(ctx, id)
}
