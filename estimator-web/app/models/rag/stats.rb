module Rag
  # Refleja `ChunkingStats` de la API: estadísticas del corpus de una estrategia (chunks, percentiles de tokens,
  # chunks degenerados y coste de la ingesta).
  class Stats
    include ActiveModel::Model
    include ActiveModel::Attributes

    attribute :strategy, :string
    attribute :n_chunks, :integer
    attribute :n_orphan_chunks, :integer # chunks de menos de 20 tokens
    attribute :n_obese_chunks, :integer  # chunks de más de 800 tokens
    attribute :ingestion_cost_usd, :float
    attribute :extra_api_calls, :integer
    attribute :ingestion_seconds, :float

    attr_reader :token_distribution

    def initialize(attributes = {})
      stringified = attributes.to_h.transform_keys(&:to_s)
      distribution = stringified.delete("token_distribution") || {}
      super(stringified.slice(*self.class.attribute_names))
      @token_distribution = Rag::TokenDistribution.new(distribution.to_h.transform_keys(&:to_s).slice("min", "p50", "p95", "max"))
    end

    def orphans? = n_orphan_chunks.to_i.positive?
    def obese? = n_obese_chunks.to_i.positive?
    def free? = ingestion_cost_usd.to_f.zero?
  end
end
