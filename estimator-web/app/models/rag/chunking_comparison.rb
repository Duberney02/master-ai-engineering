module Rag
  # Raíz ActiveRecord del contexto RAG. Guarda cada ejecución del laboratorio (parámetros y respuesta completa de la
  # API como JSONB) para poder volver a ella sin repagar las estrategias de pago.
  class ChunkingComparison < ApplicationRecord
    self.table_name = "chunking_comparisons"

    validates :strategies, presence: true
    validates :top_k, numericality: { only_integer: true, in: 1..10 }

    def to_response
      Rag::ComparisonResponse.from_hash(response_payload)
    end

    def strategy_labels
      strategies.map { |name| Rag::Strategy.label_for(name) }
    end

    def total_cost_usd
      to_response.total_ingestion_cost_usd
    end

    def duration_seconds
      duration_ms && (duration_ms / 1000.0).round(1)
    end
  end
end
