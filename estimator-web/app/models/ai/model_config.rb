module Ai
  # Refleja una entrada de la instantánea de GET /api/v1/config/models (`models[knob]`): qué modelo está vigente
  # para un knob, cuál es su valor por defecto (`.env`) y si hay un override en runtime.
  class ModelConfig
    include ActiveModel::Model
    include ActiveModel::Attributes

    # Catálogo de presentación de los siete knobs configurables, en el orden de la pantalla.
    Entry = Struct.new(:key, :label, :description, :provider, keyword_init: true)
    CATALOG = [
      Entry.new(key: "primary_model", label: "Modelo primario", provider: nil,
                description: "Genera todas las estimaciones (transaccional, conversación y actor del bucle Actor-Crítico-Boss)."),
      Entry.new(key: "fallback_model", label: "Modelo de respaldo", provider: nil,
                description: "Se usa cuando el primario falla de forma reintentable. Sin valor, no hay segundo intento."),
      Entry.new(key: "critic_model", label: "Crítico (ACB)", provider: nil,
                description: "Audita las estimaciones en el bucle Actor-Crítico-Boss."),
      Entry.new(key: "metadata_model", label: "Extractor de metadatos", provider: nil,
                description: "Extrae nombre, tecnologías y alcance del proyecto una vez por turno."),
      Entry.new(key: "summary_model", label: "Resumen y compresión", provider: nil,
                description: "Resume la memoria de la conversación y detecta anclas."),
      Entry.new(key: "propositional_chunker_model", label: "Chunker proposicional", provider: "openai",
                description: "Descompone componentes en proposiciones atómicas (Chunking Lab). Solo modelos de OpenAI."),
      Entry.new(key: "contextual_chunker_model", label: "Chunker contextual", provider: "anthropic",
                description: "Sitúa cada chunk en su presupuesto (Chunking Lab). Solo modelos de Anthropic.")
    ].freeze

    KEYS = CATALOG.map(&:key).freeze

    attribute :key, :string
    attribute :effective, :string
    attribute :default, :string
    attribute :overridden, :boolean, default: false

    def self.from_hash(key, raw)
      raw = raw.to_h
      new(key: key, effective: raw["effective"], default: raw["default"], overridden: raw["overridden"] || false)
    end

    def entry = CATALOG.find { |candidate| candidate.key == key }
    def label = entry&.label || key
    def description = entry&.description
    def provider = entry&.provider
  end
end
