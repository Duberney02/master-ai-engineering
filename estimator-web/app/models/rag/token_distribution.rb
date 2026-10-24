module Rag
  # Refleja `TokenDistribution` de la API: mínimo, p50, p95 y máximo de tokens por chunk.
  class TokenDistribution
    include ActiveModel::Model
    include ActiveModel::Attributes

    attribute :min, :integer
    attribute :p50, :float
    attribute :p95, :float
    attribute :max, :integer
  end
end
