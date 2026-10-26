module EstimatorAi
  # Contexto «estimación transaccional»: estimar, historial y vista previa del prompt.
  class EstimationsClient < BaseClient
    # Solicita una estimación. Devuelve el cuerpo de la API (Hash con "result", "estimation_id"...).
    def create_estimation(attributes, prompt_version: nil)
      params = prompt_version.present? ? { prompt_version: prompt_version } : nil
      body = request(:post, "/api/v1/estimate", params: params, body: attributes)
      expect_hash!(body, "result")
    end

    # Últimas estimaciones del historial (Array de Hash).
    def list_estimations(limit: 10)
      body = request(:get, "/api/v1/estimations", params: { limit: limit }, history: true)
      raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Array) && body.all?(Hash)

      body
    end

    # Prompt de sistema renderizado y ejemplos few-shot para unas opciones (barra lateral).
    def prompt_preview(prompt_version:, project_type:, detail_level:, output_format:)
      body = request(:get, "/api/v1/prompts/estimation", params: {
        prompt_version: prompt_version, project_type: project_type,
        detail_level: detail_level, output_format: output_format
      })
      raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body["system_prompt"].is_a?(String)

      body
    end

    def find_estimation(id)
      body = request(:get, "/api/v1/estimations/#{Integer(id)}", history: true)
      expect_hash!(body, "result")
    rescue ArgumentError, TypeError
      raise NotFound.new(NOT_FOUND_MESSAGE, status: 404)
    end
  end
end
