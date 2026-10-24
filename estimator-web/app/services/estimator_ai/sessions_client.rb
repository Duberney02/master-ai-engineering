module EstimatorAi
  # Contexto «conversación»: sesiones con memoria y estimaciones dentro de ellas.
  class SessionsClient < BaseClient
    # Crea una conversación vacía (vive en memoria de la API) y devuelve su `session_id`.
    def create_session
      body = request(:post, "/api/v1/sessions", expected_status: 201)
      raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body["session_id"].is_a?(String)

      body["session_id"]
    end

    # Una estimación dentro de la conversación: `fields` son los campos de formulario (transcript, opciones,
    # prompt_version) y `attachments` los archivos subidos (ActionDispatch::Http::UploadedFile).
    # Devuelve el cuerpo de la API (con "result", "project_metadata", "estimation_id"...).
    def create_session_estimation(session_id, fields, attachments: [])
      # Cada campo va como parte multipart explícita: así el cuerpo es siempre `multipart/form-data`,
      # incluso sin adjuntos (la API solo lee formularios, no JSON).
      payload = fields.to_h { |key, value| [ key.to_s, Faraday::Multipart::ParamPart.new(value.to_s, "text/plain; charset=UTF-8") ] }
      files = attachments.map do |file|
        file.rewind
        Faraday::Multipart::FilePart.new(file.tempfile, file.content_type.presence || "application/octet-stream", file.original_filename)
      end
      payload["attachments"] = files if files.any?
      body = request(:post, "/api/v1/sessions/#{ERB::Util.url_encode(session_id)}/estimate", body: payload, session: true)
      expect_hash!(body, "result")
      unless body["project_metadata"].is_a?(Hash) && body["project_metadata"]["mentioned_technologies"].is_a?(Array)
        raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE)
      end

      body
    end
  end
end
