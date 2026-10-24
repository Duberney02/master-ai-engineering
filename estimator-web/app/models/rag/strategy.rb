module Rag
  # Catálogo de las ocho estrategias de chunking que sirve POST /embeddings/compare. Fuente única para el formulario
  # del laboratorio (etiquetas, selección por defecto), los avisos de coste y de clave y la validación de nombres.
  #
  # Refleja `ALL_STRATEGIES` del estimador (`generation/rag/chunking/registry.py`): mismos nombres, mismo orden.
  class Strategy
    Entry = Struct.new(:name, :label, :description, :cost_tier, :needs_key, :default_checked, keyword_init: true)

    CATALOG = [
      Entry.new(name: "structural", label: "Estructural", cost_tier: :free, needs_key: nil, default_checked: true,
                description: "Un componente del presupuesto es un chunk, con la cabecera de contexto del proyecto."),
      Entry.new(name: "fixed_size", label: "Tamaño fijo", cost_tier: :free, needs_key: nil, default_checked: true,
                description: "Ventanas de 512 tokens con solapamiento: la línea base degenerada."),
      Entry.new(name: "recursive", label: "Recursivo", cost_tier: :free, needs_key: nil, default_checked: true,
                description: "Separadores jerárquicos (párrafo, línea, frase): el valor por defecto razonable."),
      Entry.new(name: "sentence_window", label: "Ventana de frases", cost_tier: :free, needs_key: nil, default_checked: false,
                description: "Se indexa cada frase y el contexto (±2 frases) viaja en los metadatos."),
      Entry.new(name: "hierarchical", label: "Jerárquico", cost_tier: :free, needs_key: nil, default_checked: false,
                description: "Dos niveles: padres (presupuesto completo) e hijos (componentes)."),
      Entry.new(name: "semantic", label: "Semántico", cost_tier: :cheap, needs_key: :openai, default_checked: false,
                description: "Corta donde cae la similitud entre frases (embeddings durante la ingesta)."),
      Entry.new(name: "propositional", label: "Proposicional", cost_tier: :expensive, needs_key: :openai, default_checked: false,
                description: "Un LLM descompone cada componente en proposiciones atómicas (una llamada por componente)."),
      Entry.new(name: "contextual_retrieval", label: "Contextual retrieval", cost_tier: :expensive, needs_key: :anthropic,
                default_checked: false,
                description: "Un LLM de Anthropic sitúa cada chunk en su presupuesto, con prompt caching (minutos de ejecución).")
    ].freeze

    ALL_NAMES = CATALOG.map(&:name).freeze
    KEY_NAMES = { openai: "OPENAI_API_KEY", anthropic: "ANTHROPIC_API_KEY" }.freeze

    def self.find(name)
      CATALOG.find { |entry| entry.name == name }
    end

    # Las gratuitas: lo que se ejecuta por defecto. Las de pago son opt-in.
    def self.defaults
      CATALOG.select(&:default_checked).map(&:name)
    end

    def self.paid?(name)
      entry = find(name)
      !entry.nil? && entry.cost_tier != :free
    end

    def self.paid_selected?(names)
      names.any? { |name| paid?(name) }
    end

    def self.keys_needed(names)
      names.filter_map { |name| KEY_NAMES[find(name)&.needs_key] }.uniq
    end

    def self.label_for(name)
      find(name)&.label || name
    end
  end
end
