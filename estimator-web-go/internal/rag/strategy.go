// Package rag es el contexto «RAG» (Sesión 7): el catálogo de estrategias de chunking, los contratos de
// POST /embeddings/compare y el historial persistido del Chunking Lab.
package rag

// CostTier es el coste de ejecutar una estrategia.
type CostTier string

const (
	Free      CostTier = "free"
	Cheap     CostTier = "cheap"
	Expensive CostTier = "expensive"
)

// KeyProvider es el proveedor cuya clave necesita una estrategia en el servicio IA.
type KeyProvider string

const (
	NoKey     KeyProvider = ""
	OpenAI    KeyProvider = "openai"
	Anthropic KeyProvider = "anthropic"
)

// Strategy es una entrada del catálogo.
type Strategy struct {
	Name           string
	Label          string
	Description    string
	CostTier       CostTier
	NeedsKey       KeyProvider
	DefaultChecked bool
}

// Paid indica que la estrategia cuesta dinero.
func (s Strategy) Paid() bool { return s.CostTier != Free }

// CostLabel es la etiqueta de coste del formulario.
func (s Strategy) CostLabel() string {
	switch s.CostTier {
	case Cheap:
		return "de pago (embeddings)"
	case Expensive:
		return "de pago (LLM)"
	}
	return "gratis"
}

// KeyName es la variable de entorno de la clave que necesita (vacío si no necesita ninguna).
func (s Strategy) KeyName() string { return keyNames[s.NeedsKey] }

var keyNames = map[KeyProvider]string{OpenAI: "OPENAI_API_KEY", Anthropic: "ANTHROPIC_API_KEY"}

// Catalog son las ocho estrategias que sirve POST /embeddings/compare. Fuente única para el formulario del
// laboratorio (etiquetas, selección por defecto), los avisos de coste y de clave y la validación de nombres.
//
// Refleja `ALL_STRATEGIES` del estimador (`generation/rag/chunking/registry.py`): mismos nombres, mismo orden.
var Catalog = []Strategy{
	{Name: "structural", Label: "Estructural", CostTier: Free, DefaultChecked: true,
		Description: "Un componente del presupuesto es un chunk, con la cabecera de contexto del proyecto."},
	{Name: "fixed_size", Label: "Tamaño fijo", CostTier: Free, DefaultChecked: true,
		Description: "Ventanas de 512 tokens con solapamiento: la línea base degenerada."},
	{Name: "recursive", Label: "Recursivo", CostTier: Free, DefaultChecked: true,
		Description: "Separadores jerárquicos (párrafo, línea, frase): el valor por defecto razonable."},
	{Name: "sentence_window", Label: "Ventana de frases", CostTier: Free,
		Description: "Se indexa cada frase y el contexto (±2 frases) viaja en los metadatos."},
	{Name: "hierarchical", Label: "Jerárquico", CostTier: Free,
		Description: "Dos niveles: padres (presupuesto completo) e hijos (componentes)."},
	{Name: "semantic", Label: "Semántico", CostTier: Cheap, NeedsKey: OpenAI,
		Description: "Corta donde cae la similitud entre frases (embeddings durante la ingesta)."},
	{Name: "propositional", Label: "Proposicional", CostTier: Expensive, NeedsKey: OpenAI,
		Description: "Un LLM descompone cada componente en proposiciones atómicas (una llamada por componente)."},
	{Name: "contextual_retrieval", Label: "Contextual retrieval", CostTier: Expensive, NeedsKey: Anthropic,
		Description: "Un LLM de Anthropic sitúa cada chunk en su presupuesto, con prompt caching (minutos de ejecución)."},
}

// AllNames devuelve los nombres del catálogo, en orden.
func AllNames() []string {
	names := make([]string, len(Catalog))
	for index, strategy := range Catalog {
		names[index] = strategy.Name
	}
	return names
}

// Find busca una estrategia por nombre.
func Find(name string) (Strategy, bool) {
	for _, strategy := range Catalog {
		if strategy.Name == name {
			return strategy, true
		}
	}
	return Strategy{}, false
}

// Defaults son las gratuitas marcadas por defecto: lo que se ejecuta sin más. Las de pago son opt-in.
func Defaults() []string {
	var names []string
	for _, strategy := range Catalog {
		if strategy.DefaultChecked {
			names = append(names, strategy.Name)
		}
	}
	return names
}

// IsPaid indica si la estrategia existe y cuesta dinero.
func IsPaid(name string) bool {
	strategy, ok := Find(name)
	return ok && strategy.Paid()
}

// PaidSelected indica si alguna de las estrategias es de pago.
func PaidSelected(names []string) bool {
	for _, name := range names {
		if IsPaid(name) {
			return true
		}
	}
	return false
}

// KeysNeeded devuelve las variables de clave (sin repetir) que necesitan las estrategias.
func KeysNeeded(names []string) []string {
	var keys []string
	seen := map[string]bool{}
	for _, name := range names {
		strategy, ok := Find(name)
		if !ok || strategy.KeyName() == "" || seen[strategy.KeyName()] {
			continue
		}
		seen[strategy.KeyName()] = true
		keys = append(keys, strategy.KeyName())
	}
	return keys
}

// LabelFor devuelve la etiqueta de una estrategia (o su nombre si no está en el catálogo).
func LabelFor(name string) string {
	if strategy, ok := Find(name); ok {
		return strategy.Label
	}
	return name
}
