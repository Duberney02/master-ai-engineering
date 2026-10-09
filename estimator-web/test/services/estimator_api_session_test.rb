require "test_helper"

class EstimatorApiSessionTest < ActiveSupport::TestCase
  FIELDS = { "transcript" => "Portal de clientes para facturas.", "project_type" => "web_saas",
             "detail_level" => "medium", "output_format" => "phases_table", "prompt_version" => "v3" }.freeze

  def api
    EstimatorApi.new(base_url: API)
  end

  def upload(name, content = "contenido", type: "application/pdf")
    tempfile = Tempfile.new([ "adjunto", File.extname(name) ])
    tempfile.binmode
    tempfile.write(content)
    tempfile.rewind
    ActionDispatch::Http::UploadedFile.new(tempfile: tempfile, filename: name, type: type)
  end

  def assert_api_error(expected_message, status: nil)
    error = assert_raises(EstimatorApi::Error) { yield }
    assert_equal expected_message, error.message
    assert_equal status, error.status if status
    refute_includes error.message, "estimator-api.test", "no debe exponer la URL interna"
    error
  end

  # --- create_session ---

  test "create_session posts to /sessions and returns the session id" do
    stub = stub_session_create("abc-123")

    assert_equal "abc-123", api.create_session
    assert_requested stub
  end

  test "create_session rejects bodies without a session id" do
    stub_request(:post, "#{API}/api/v1/sessions").to_return(json_response({ "otro" => 1 }, status: 201))

    assert_api_error(EstimatorApi::INVALID_RESPONSE_MESSAGE) { api.create_session }
  end

  test "create_session expects 201 and sanitizes server errors" do
    stub_request(:post, "#{API}/api/v1/sessions").to_return(status: 500, body: "Traceback password=hunter2")

    error = assert_api_error(EstimatorApi::SERVER_MESSAGE, status: 500) { api.create_session }
    refute_includes error.message, "hunter2"
  end

  test "create_session turns connection failures into the generic message" do
    stub_request(:post, "#{API}/api/v1/sessions").to_raise(Faraday::ConnectionFailed.new("getaddrinfo: estimator-api.test"))

    assert_api_error(EstimatorApi::CONNECTION_MESSAGE) { api.create_session }
  end

  # --- create_session_estimation ---

  test "it sends multipart form data with every field, even without attachments" do
    stub = stub_request(:post, SESSION_ESTIMATE_URL).to_return(json_response(estimate_body))

    response = api.create_session_estimation(SESSION_ID, FIELDS)

    assert_requested stub
    assert_equal 7, response["estimation_id"]
    assert_requested(:post, SESSION_ESTIMATE_URL) do |req|
      body = req.body.dup.force_encoding(Encoding::UTF_8)
      req.headers["Content-Type"].start_with?("multipart/form-data; boundary=") &&
        FIELDS.all? { |name, value| body.include?(%(name="#{name}")) && body.include?(value) } &&
        !body.include?("filename=")
    end
  end

  test "each attachment is sent as a file part named attachments, in order" do
    stub_request(:post, SESSION_ESTIMATE_URL).to_return(json_response(estimate_body))
    files = [ upload("requisitos.pdf", "%PDF-uno"), upload("alcance.docx", "PK-dos", type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document") ]

    api.create_session_estimation(SESSION_ID, FIELDS, attachments: files)

    assert_requested(:post, SESSION_ESTIMATE_URL) do |req|
      body = req.body.dup.force_encoding(Encoding::BINARY)
      names = body.scan(/name="attachments"; filename="([^"]+)"/).flatten
      names == %w[requisitos.pdf alcance.docx] && body.include?("%PDF-uno") && body.include?("PK-dos") &&
        body.include?("Content-Type: application/pdf") && !body.include?("attachments[]")
    end
  end

  test "a 404 means the session expired" do
    stub_request(:post, SESSION_ESTIMATE_URL).to_return(json_response({ "detail" => "Session not found or expired" }, status: 404))

    error = assert_raises(EstimatorApi::SessionExpired) { api.create_session_estimation(SESSION_ID, FIELDS) }

    assert_equal EstimatorApi::SESSION_EXPIRED_MESSAGE, error.message
    assert_equal 404, error.status
  end

  test "rejections of attachments show the text detail written by the API" do
    { 413 => "Cada adjunto puede pesar como máximo 10 MB.",
      415 => "Solo se admiten adjuntos PDF (.pdf) y Word (.docx).",
      422 => "No se pudo extraer texto de «escaneado.pdf» (¿está escaneado o vacío?)." }.each do |status, detail|
      stub_request(:post, SESSION_ESTIMATE_URL).to_return(json_response({ "detail" => detail }, status: status))

      assert_api_error(detail, status: status) { api.create_session_estimation(SESSION_ID, FIELDS) }
    end
  end

  test "details that are not plain text fall back to generic messages and never leak the body" do
    stub_request(:post, SESSION_ESTIMATE_URL)
      .to_return(json_response({ "detail" => [ { "loc" => [ "body" ], "input" => "texto privado" } ] }, status: 422))
    error = assert_api_error(EstimatorApi::VALIDATION_MESSAGE, status: 422) { api.create_session_estimation(SESSION_ID, FIELDS) }
    refute_includes error.message, "privado"

    stub_request(:post, SESSION_ESTIMATE_URL).to_return(status: 413, body: "<html>nginx</html>")
    assert_api_error(EstimatorApi::REJECTED_MESSAGE, status: 413) { api.create_session_estimation(SESSION_ID, FIELDS) }
  end

  test "guardrail rejections show the API message" do
    stub_request(:post, SESSION_ESTIMATE_URL)
      .to_return(json_response({ "reason" => "pii_email", "message" => "Elimina el correo." }, status: 400))

    assert_api_error("Elimina el correo.", status: 400) { api.create_session_estimation(SESSION_ID, FIELDS) }
  end

  test "bodies outside the contract are invalid responses" do
    [ { "nope" => 1 },
      { "result" => RESULT },
      { "result" => RESULT, "project_metadata" => { "mentioned_technologies" => "python" } } ].each do |body|
      stub_request(:post, SESSION_ESTIMATE_URL).to_return(json_response(body))

      assert_api_error(EstimatorApi::INVALID_RESPONSE_MESSAGE) { api.create_session_estimation(SESSION_ID, FIELDS) }
    end
  end

  test "the session id is escaped in the path" do
    stub = stub_request(:post, "#{API}/api/v1/sessions/a%2Fb/estimate").to_return(json_response(estimate_body))

    api.create_session_estimation("a/b", FIELDS)

    assert_requested stub
  end

  test "the stateless estimate still sends JSON" do
    stub_request(:post, "#{API}/api/v1/estimate").to_return(json_response(estimate_body))

    api.create_estimation({ "description" => "Portal de clientes para facturas." })

    assert_requested(:post, "#{API}/api/v1/estimate") { |req| req.headers["Content-Type"].start_with?("application/json") }
  end
end
