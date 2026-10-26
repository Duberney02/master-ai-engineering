module Rag
  # Refleja `TopChunk` de la API: un chunk ordenado en la recuperación de una consulta.
  #
  # `level` ("parent" o "child") y `parent_chunk_id` solo existen en la estrategia jerárquica.
  class TopChunk
    include ActiveModel::Model
    include ActiveModel::Attributes

    attribute :chunk_id, :string
    attribute :cosine, :float
    attribute :text_preview, :string
    attribute :level, :string
    attribute :parent_chunk_id, :string

    def parent? = level == "parent"
    def child? = level == "child"

    # Puntuación como porcentaje 0-100 para dibujar la barra.
    def cosine_pct
      (cosine.to_f.clamp(0.0, 1.0) * 100).round
    end
  end
end
