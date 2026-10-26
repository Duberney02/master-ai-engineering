module Ai
  # Refleja la respuesta completa de GET /api/v1/config/models: los siete knobs (en el orden de la pantalla), el
  # catálogo seleccionable (la API ya lo filtra por las claves configuradas) y el modelo de embeddings, de solo lectura.
  class Catalog
    attr_reader :model_configs, :available_models, :embedding_model, :embedding_model_note

    def self.from_hash(hash)
      hash = hash.to_h
      models = hash["models"].to_h
      configs = Ai::ModelConfig::KEYS.filter_map do |key|
        Ai::ModelConfig.from_hash(key, models[key]) if models.key?(key)
      end
      new(
        model_configs: configs,
        available_models: Array(hash["available_models"]),
        embedding_model: hash["embedding_model"],
        embedding_model_note: hash["embedding_model_note"]
      )
    end

    def initialize(model_configs:, available_models:, embedding_model:, embedding_model_note: nil)
      @model_configs = model_configs
      @available_models = available_models
      @embedding_model = embedding_model
      @embedding_model_note = embedding_model_note
    end

    def primary_model
      model_configs.find { |config| config.key == "primary_model" }&.effective
    end

    def any_overridden?
      model_configs.any?(&:overridden)
    end

    # Modelos que admite un knob: los del catálogo, limitados al proveedor que exige el knob (los chunkers).
    def options_for(config)
      case config.provider
      when "openai" then available_models.reject { |model| model.start_with?("claude") }
      when "anthropic" then available_models.select { |model| model.start_with?("claude") }
      else available_models
      end
    end
  end
end
