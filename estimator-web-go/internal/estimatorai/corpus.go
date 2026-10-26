package estimatorai

import (
	"embed"
	"encoding/json"
	"sync"
)

// Corpus estático que viaja con el cliente: los 15 presupuestos de ejemplo del estimador más tres casos límite
// (monolito obeso, tareas mínimas, descripciones de varias frases) y las consultas de referencia. Los presupuestos se
// envían tal cual en el cuerpo de la comparación; FastAPI los valida con Pydantic.
//
// Son datos de referencia (no semillas de base de datos), embebidos desde data/. Si el corpus del estimador evoluciona
// (`estimador-cag/data/`), hay que volver a copiar los tres archivos.

//go:embed data/*.json
var corpusFiles embed.FS

// CorpusLabel identifica el corpus en el historial.
const CorpusLabel = "budgets_sample + budgets_stress_cases"

var (
	loadOnce sync.Once
	budgets  []json.RawMessage
	queries  []string
)

func loadCorpus() {
	for _, name := range []string{"data/budgets_sample.json", "data/budgets_stress_cases.json"} {
		var items []json.RawMessage
		if err := json.Unmarshal(mustRead(name), &items); err != nil {
			panic("corpus inválido " + name + ": " + err.Error())
		}
		budgets = append(budgets, items...)
	}
	if err := json.Unmarshal(mustRead("data/test_queries.json"), &queries); err != nil {
		panic("consultas inválidas: " + err.Error())
	}
}

func mustRead(name string) []byte {
	content, err := corpusFiles.ReadFile(name)
	if err != nil {
		panic(err)
	}
	return content
}

// Budgets devuelve los presupuestos del corpus (no se debe modificar el resultado).
func Budgets() []json.RawMessage {
	loadOnce.Do(loadCorpus)
	return budgets
}

// SampleQueries devuelve las consultas de referencia del formulario del laboratorio.
func SampleQueries() []string {
	loadOnce.Do(loadCorpus)
	return queries
}
