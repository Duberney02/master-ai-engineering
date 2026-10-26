package rag

import (
	"context"
	"errors"
	"fmt"
	"math"
	"time"
)

// ErrNotFound indica que no existe la ejecución pedida.
var ErrNotFound = errors.New("rag: comparación no encontrada")

// Comparison guarda cada ejecución del laboratorio (parámetros y respuesta completa de la API como JSON) para poder
// volver a ella sin repagar las estrategias de pago. Es la tabla `chunking_comparisons`, sin cambios de esquema.
type Comparison struct {
	ID              int64
	Strategies      []string
	Queries         []string
	TopK            int
	CorpusLabel     string
	CorpusCount     int
	ResponsePayload []byte // JSON de CompareResponse
	DurationMS      *int
	CreatedAt       time.Time // cero mientras no se ha guardado
}

// Validate replica las validaciones del modelo: al menos una estrategia y top_k entero entre 1 y 10.
func (c Comparison) Validate() error {
	if len(c.Strategies) == 0 {
		return errors.New("rag: se necesita al menos una estrategia")
	}
	if c.TopK < 1 || c.TopK > 10 {
		return fmt.Errorf("rag: top_k fuera de rango: %d", c.TopK)
	}
	return nil
}

// Response interpreta la respuesta guardada.
func (c Comparison) Response() ComparisonResponse { return ParseResponse(c.ResponsePayload) }

// StrategyLabels son las etiquetas de las estrategias ejecutadas.
func (c Comparison) StrategyLabels() []string {
	labels := make([]string, len(c.Strategies))
	for index, name := range c.Strategies {
		labels[index] = LabelFor(name)
	}
	return labels
}

// TotalCostUSD es el coste total de ingesta de la ejecución.
func (c Comparison) TotalCostUSD() float64 { return c.Response().TotalIngestionCostUSD() }

// DurationSeconds es la duración en segundos con un decimal (false si no se midió).
func (c Comparison) DurationSeconds() (float64, bool) {
	if c.DurationMS == nil {
		return 0, false
	}
	return math.Round(float64(*c.DurationMS)/100) / 10, true
}

// Saved indica que la ejecución ya está en el historial.
func (c Comparison) Saved() bool { return !c.CreatedAt.IsZero() }

// Store es el historial persistido de ejecuciones.
type Store interface {
	// Create guarda la ejecución y rellena su ID y fecha.
	Create(ctx context.Context, comparison *Comparison) error
	// Recent devuelve las últimas ejecuciones, la más reciente primero.
	Recent(ctx context.Context, limit int) ([]Comparison, error)
	// Find devuelve una ejecución o ErrNotFound.
	Find(ctx context.Context, id int64) (*Comparison, error)
}
