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

  # La API ya no conoce la sesión (reinicio del servicio o caducidad): hay que abrir otra conversación.
  class SessionExpired < Error
    def initialize
      super(SESSION_EXPIRED_MESSAGE, status: 404)
    end
  end

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

  # Solicita una estimación. Devuelve el cuerpo de la API (Hash con "result", "estimation_id"...).
  def create_estimation(attributes, prompt_version: nil)
    params = prompt_version.present? ? { prompt_version: prompt_version } : nil
    body = request(:post, "/api/v1/estimate", params: params, body: attributes)
    expect_hash!(body, "result")
  end

  # Crea una conversación vacía (vive en memoria de la API) y devuelve su `session_id`.
  def create_session
    body = request(:post, "/api/v1/sessions", expected_status: 201)
    raise Error.new(INVALID_RESPONSE_MESSAGE) unless body.is_a?(Hash) && body["session_id"].is_a?(String)

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
      raise Error.new(INVALID_RESPONSE_MESSAGE)
    end

    body
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

  def request(verb, path, params: nil, body: nil, history: false, session: false, expected_status: 200)
    response = @connection.run_request(verb, path, body, nil) do |req|
      req.params.update(params) if params
    end
    handle(response, history: history, session: session, expected_status: expected_status)
  rescue Faraday::ConnectionFailed, Faraday::TimeoutError, Faraday::SSLError
    raise Error.new(CONNECTION_MESSAGE)
  rescue Faraday::Error
    raise Error.new(SERVER_MESSAGE)
  end

  def handle(response, history:, session: false, expected_status: 200)
    status = response.status
    return parse(response.body) if status == expected_status
    raise SessionExpired if session && status == 404

    raise Error.new(message_for(status, response.body, history: history, session: session), status: status)
  end

  def message_for(status, body, history:, session: false)
    return detail_message(body) || (status == 422 ? VALIDATION_MESSAGE : REJECTED_MESSAGE) if session && [ 413, 415, 422 ].include?(status)

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

  # Los `detail` de texto de los rechazos de adjuntos los redacta la API sin datos del usuario.
  def detail_message(body)
    detail = JSON.parse(body.to_s)["detail"]
    detail.is_a?(String) && detail.present? ? detail.first(GUARDRAIL_MESSAGE_LIMIT) : nil
  rescue JSON::ParserError, NoMethodError, TypeError
    nil
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
