module EstimatorAi
  # Contexto «configuración del servicio»: modelos del LLM en tiempo de ejecución (pantalla de Ajustes).
  class ConfigClient < BaseClient
    # GET /api/v1/config/models → { "models" => { knob => { effective, default, overridden } }, "available_models" => […], … }
    def models
      body = request(:get, "/api/v1/config/models", detail: true)
      raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body["models"].is_a?(Hash)

      body
    end

    # PUT /api/v1/config/models. `changes` es parcial: { "primary_model" => "gpt-4o", "critic_model" => nil };
    # nil restablece ese knob a su valor por defecto. La API valida todo antes de aplicar nada.
    def update_models(changes)
      raise ArgumentError, "changes must be a non-empty hash" if changes.blank?

      body = request(:put, "/api/v1/config/models", body: { models: changes }, detail: true)
      raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body["models"].is_a?(Hash)

      body
    end
  end
end
