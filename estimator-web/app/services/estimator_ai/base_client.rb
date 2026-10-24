require "faraday"
require "faraday/multipart"

module EstimatorAi
  # Capa HTTP única: la ÚNICA que habla con el servicio FastAPI. Cada cliente de contexto (estimaciones, sesiones,
  # embeddings, configuración) hereda de aquí la conexión Faraday, el mapeo respuesta → error tipado y los mensajes.
  #
  # No tiene lógica de negocio ni opinión sobre el significado de los payloads: eso es de los contratos de cada contexto.
  # Traduce cualquier fallo a un `EstimatorAi::Error` con un mensaje en español apto para el usuario.
  class BaseClient
    CONNECTION_MESSAGE = "No se pudo conectar con la API del estimador. Inténtalo de nuevo en unos instantes.".freeze
    INVALID_RESPONSE_MESSAGE = "La API del estimador devolvió una respuesta inválida.".freeze
    SERVER_MESSAGE = "La API del estimador no pudo completar la solicitud. Inténtalo de nuevo.".freeze
    VALIDATION_MESSAGE = "La solicitud no es válida. Revisa los campos del formulario.".freeze
    NOT_FOUND_MESSAGE = "No se encontró la estimación solicitada.".freeze
    HISTORY_UNAVAILABLE_MESSAGE = "El historial no está disponible en este momento.".freeze
    REJECTED_MESSAGE = "La API rechazó la solicitud.".freeze
    SESSION_EXPIRED_MESSAGE = "La conversación anterior expiró en el servidor; se inició una nueva. Vuelve a enviar tu mensaje.".freeze
    GUARDRAIL_MESSAGE_LIMIT = 300

    def initialize(base_url: nil, open_timeout: nil, read_timeout: nil, adapter: nil)
      config = Rails.configuration.x
      @connection = Faraday.new(
        url: base_url || config.estimator_api_url,
        request: {
          open_timeout: open_timeout || config.estimator_open_timeout,
          timeout: read_timeout || config.estimator_read_timeout
        }
      ) do |faraday|
        # Multipart antes que JSON: solo codifica los cuerpos con archivos y fija su propio Content-Type.
        # `flat_encode` repite el nombre `attachments` por archivo (sin los corchetes `attachments[]`).
        faraday.request :multipart, flat_encode: true
        faraday.request :json
        faraday.headers["Accept"] = "application/json"
        adapter ? faraday.adapter(adapter) : faraday.adapter(Faraday.default_adapter)
      end
    end

    private

    # `history`: un 503 significa «historial no disponible». `session`: un 404 significa «sesión caducada» y los
    # rechazos de adjuntos (413/415/422) traen un `detail` redactado por la API. `detail`: los `detail` de texto de la
    # API (configuración, embeddings) se muestran tal cual; los redacta el servicio sin datos del usuario.
    def request(verb, path, params: nil, body: nil, history: false, session: false, detail: false, expected_status: 200)
      response = @connection.run_request(verb, path, body, nil) do |req|
        req.params.update(params) if params
      end
      handle(response, history: history, session: session, detail: detail, expected_status: expected_status)
    rescue Faraday::TimeoutError
      raise RequestTimeout.new(CONNECTION_MESSAGE)
    rescue Faraday::ConnectionFailed, Faraday::SSLError
      raise ConnectionFailed.new(CONNECTION_MESSAGE)
    rescue Faraday::Error
      raise ServerError.new(SERVER_MESSAGE)
    end

    def handle(response, history:, session:, detail:, expected_status:)
      status = response.status
      return parse(response.body) if status == expected_status
      raise SessionExpired if session && status == 404

      raise error_for(status, response.body, history: history, session: session, detail: detail)
    end

    def error_for(status, body, history:, session:, detail:)
      if session && [ 413, 415, 422 ].include?(status)
        return InvalidRequest.new(detail_message(body) || (status == 422 ? VALIDATION_MESSAGE : REJECTED_MESSAGE), status: status)
      end
      return detail_error_for(status, body) if detail

      case status
      when 400 then GuardrailViolation.new(guardrail_message(body), status: status)
      when 404 then NotFound.new(NOT_FOUND_MESSAGE, status: status)
      when 422 then InvalidRequest.new(VALIDATION_MESSAGE, status: status)
      when 503 then ServiceUnavailable.new(history ? HISTORY_UNAVAILABLE_MESSAGE : SERVER_MESSAGE, status: status)
      when 500..599 then ServerError.new(SERVER_MESSAGE, status: status)
      else InvalidRequest.new(REJECTED_MESSAGE, status: status)
      end
    end

    def detail_error_for(status, body)
      message = detail_message(body)
      case status
      when 400, 422 then InvalidRequest.new(message || (status == 422 ? VALIDATION_MESSAGE : REJECTED_MESSAGE), status: status)
      when 404 then NotFound.new(message || REJECTED_MESSAGE, status: status)
      when 503 then ServiceUnavailable.new(message || SERVER_MESSAGE, status: status)
      when 500..599 then ServerError.new(message || SERVER_MESSAGE, status: status)
      else InvalidRequest.new(REJECTED_MESSAGE, status: status)
      end
    end

    # El 400 de los guardrails trae `message` redactado por la API sin datos del usuario.
    def guardrail_message(body)
      message = JSON.parse(body.to_s)["message"]
      message.is_a?(String) && message.present? ? message.first(GUARDRAIL_MESSAGE_LIMIT) : REJECTED_MESSAGE
    rescue JSON::ParserError, NoMethodError, TypeError
      REJECTED_MESSAGE
    end

    # Los `detail` de texto los redacta la API sin datos del usuario.
    def detail_message(body)
      detail = JSON.parse(body.to_s)["detail"]
      detail.is_a?(String) && detail.present? ? detail.first(GUARDRAIL_MESSAGE_LIMIT) : nil
    rescue JSON::ParserError, NoMethodError, TypeError
      nil
    end

    def parse(body)
      JSON.parse(body.to_s)
    rescue JSON::ParserError
      raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE)
    end

    def expect_hash!(body, key)
      raise InvalidResponse.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body[key].is_a?(Hash)

      body
    end
  end
end
