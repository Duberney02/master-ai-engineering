module EstimatorAi
  # Contexto «RAG» (Sesión 7): comparación de estrategias de chunking sobre el corpus de presupuestos históricos.
  #
  # Las estrategias de pago (propositional, contextual_retrieval) tardan minutos: la llamada del Chunking Lab crea
  # el cliente con su propio tiempo de espera (`EmbeddingsClient.new(read_timeout: …)`) sin tocar el global.
  class EmbeddingsClient < BaseClient
    # POST /embeddings/compare. `budgets` son los presupuestos tal cual (la API los valida con Pydantic). Sin
    # `queries` se calculan solo las estadísticas; sin `strategies` la API ejecuta solo las gratuitas.
    def compare_chunking(budgets:, queries: [], strategies: [], top_k: 3)
      raise ArgumentError, "budgets must be a non-empty array" if Array(budgets).empty?

      body = request(
        :post, "/embeddings/compare", detail: true,
        body: { budgets: budgets, queries: queries, strategies: strategies, top_k: top_k }
      )
      raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body["stats_per_strategy"].is_a?(Hash)

      body
    end
  end
end
