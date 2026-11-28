// Etiquetas de las ocho estrategias del Chunking Lab (las mismas que el catálogo de Go: `rag.Catalog`).
const LABELS: Record<string, string> = {
  structural: "Estructural",
  fixed_size: "Tamaño fijo",
  recursive: "Recursivo",
  sentence_window: "Ventana de frases",
  hierarchical: "Jerárquico",
  semantic: "Semántico",
  propositional: "Proposicional",
  contextual_retrieval: "Contextual retrieval",
};

export function strategyLabel(name: string): string {
  return LABELS[name] ?? name;
}
