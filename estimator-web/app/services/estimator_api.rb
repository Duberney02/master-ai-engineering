# Cliente HTTP (Faraday) de la API del estimador.
#
# Traduce cualquier fallo a EstimatorApi::Error con un mensaje en español apto para el usuario:
# nunca expone cuerpos de respuesta crudos, trazas ni la URL interna de la API.
class EstimatorApi
  class Error < StandardError
    attr_reader :status

    def initialize(message, status: nil)
      super(message)
      @status = status
    end
  end

  CONNECTION_MESSAGE = "No se pudo conectar con la API del estimador. Inténtalo de nuevo en unos instantes.".freeze
  INVALID_RESPONSE_MESSAGE = "La API del estimador devolvió una respuesta inválida.".freeze
  SERVER_MESSAGE = "La API del estimador no pudo completar la solicitud. Inténtalo de nuevo.".freeze
  VALIDATION_MESSAGE = "La solicitud no es válida. Revisa los campos del formulario.".freeze
  NOT_FOUND_MESSAGE = "No se encontró la estimación solicitada.".freeze
  HISTORY_UNAVAILABLE_MESSAGE = "El historial no está disponible en este momento.".freeze
  REJECTED_MESSAGE = "La API rechazó la solicitud.".freeze
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
      faraday.request :json
      faraday.headers["Accept"] = "application/json"
      adapter ? faraday.adapter(adapter) : faraday.adapter(Faraday.default_adapter)
    end
  end

  # Solicita una estimación. Devuelve el cuerpo de la API (Hash con "result", "estimation_id"...).
  def create_estimation(attributes, prompt_version: nil)
    params = prompt_version.present? ? { prompt_version: prompt_version } : nil
    body = request(:post, "/api/v1/estimate", params: params, body: attributes)
    expect_hash!(body, "result")
  end

  # Últimas estimaciones del historial (Array de Hash).
  def list_estimations(limit: 10)
    body = request(:get, "/api/v1/estimations", params: { limit: limit }, history: true)
    raise Error.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Array) && body.all?(Hash)

    body
  end

  # Prompt de sistema renderizado y ejemplos few-shot para unas opciones (barra lateral).
  def prompt_preview(prompt_version:, project_type:, detail_level:, output_format:)
    body = request(:get, "/api/v1/prompts/estimation", params: {
      prompt_version: prompt_version, project_type: project_type,
      detail_level: detail_level, output_format: output_format
    })
    raise Error.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body["system_prompt"].is_a?(String)

    body
  end

  def find_estimation(id)
    body = request(:get, "/api/v1/estimations/#{Integer(id)}", history: true)
    expect_hash!(body, "result")
  rescue ArgumentError, TypeError
    raise Error.new(NOT_FOUND_MESSAGE, status: 404)
  end

  private

  def request(verb, path, params: nil, body: nil, history: false)
    response = @connection.run_request(verb, path, body, nil) do |req|
      req.params.update(params) if params
    end
    handle(response, history: history)
  rescue Faraday::ConnectionFailed, Faraday::TimeoutError, Faraday::SSLError
    raise Error.new(CONNECTION_MESSAGE)
  rescue Faraday::Error
    raise Error.new(SERVER_MESSAGE)
  end

  def handle(response, history:)
    status = response.status
    return parse(response.body) if status == 200

    raise Error.new(message_for(status, response.body, history: history), status: status)
  end

  def message_for(status, body, history:)
    case status
    when 400 then guardrail_message(body)
    when 404 then NOT_FOUND_MESSAGE
    when 422 then VALIDATION_MESSAGE
    when 503 then history ? HISTORY_UNAVAILABLE_MESSAGE : SERVER_MESSAGE
    when 500..599 then SERVER_MESSAGE
    else REJECTED_MESSAGE
    end
  end

  # El 400 de los guardrails trae `message` redactado por la API sin datos del usuario.
  def guardrail_message(body)
    message = JSON.parse(body.to_s)["message"]
    message.is_a?(String) && message.present? ? message.first(GUARDRAIL_MESSAGE_LIMIT) : REJECTED_MESSAGE
  rescue JSON::ParserError, NoMethodError, TypeError
    REJECTED_MESSAGE
  end

  def parse(body)
    JSON.parse(body.to_s)
  rescue JSON::ParserError
    raise Error.new(INVALID_RESPONSE_MESSAGE)
  end

  def expect_hash!(body, key)
    raise Error.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body[key].is_a?(Hash)

    body
  end
end
