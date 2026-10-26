module Rag
  # Refleja `QueryResult` de la API: los mejores chunks que recupera una estrategia para una consulta.
  class QueryResult
    include ActiveModel::Model
    include ActiveModel::Attributes

    attribute :strategy, :string
    attribute :query, :string

    attr_reader :top_k

    def initialize(attributes = {})
      stringified = attributes.to_h.transform_keys(&:to_s)
      chunks = stringified.delete("top_k") || []
      super(stringified.slice(*self.class.attribute_names))
      @top_k = chunks.map { |raw| Rag::TopChunk.new(raw.to_h.transform_keys(&:to_s).slice(*Rag::TopChunk.attribute_names)) }
    end
  end
end
