require "test_helper"

class ConversationTest < ActionDispatch::IntegrationTest
  DESCRIPTION = "Portal de clientes para consultar facturas y abrir incidencias de soporte.".freeze
  SECOND_ID = "0b1d9f3a-3c55-4d3e-8d2a-5a8d8c6b7e21".freeze
  DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document".freeze

  def params(**overrides)
    { estimation_form: { description: DESCRIPTION, project_type: "web_saas", detail_level: "medium",
                         output_format: "phases_table", prompt_version: "v3" }.merge(overrides) }
  end

  def upload(name, content = "contenido", type: "application/pdf")
    Rack::Test::UploadedFile.new(StringIO.new(content.dup), type, original_filename: name)
  end

  def sessions_requested
    WebMock::RequestRegistry.instance.times_executed(WebMock::RequestPattern.new(:post, "#{API}/api/v1/sessions"))
  end

  def stub_estimate(body = estimate_body, status: 200, url: SESSION_ESTIMATE_URL)
    stub_request(:post, url).to_return(json_response(body, status: status))
  end

  # --- Sesión al cargar la página ---

  test "opening the page creates a session once and keeps it across page loads" do
    stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 }).to_return(json_response([]))

    get root_path
    get root_path
    get estimations_path

    assert_response :success
    assert_equal 1, sessions_requested
  end

  test "the estimate is sent to the session created on load" do
    stub = stub_estimate
    get root_path

    post estimations_path, params: params

    assert_redirected_to estimation_path(7)
    assert_requested stub
    assert_equal 1, sessions_requested
  end

  test "if the API could not create the session on load, submitting retries it" do
    stub_request(:post, "#{API}/api/v1/sessions").to_return(status: 500).then.to_return(json_response({ "session_id" => SESSION_ID }, status: 201))
    stub = stub_estimate

    get root_path
    assert_response :success
    assert_select "form#estimation-form"

    post estimations_path, params: params

    assert_redirected_to estimation_path(7)
    assert_requested stub
    assert_equal 2, sessions_requested
  end

  # --- Adjuntos ---

  test "the form offers a multiple attachments field for PDF and Word" do
    get root_path

    assert_select "input#attachments[type=file][multiple][accept*='.pdf'][accept*='.docx']"
    assert_select "label[for=attachments]", text: "Adjuntos (PDF o Word)"
  end

  test "several attachments are sent to the API as multipart files" do
    stub_estimate
    files = [ upload("requisitos.pdf", "%PDF-uno"), upload("alcance.docx", "PK-dos", type: DOCX) ]

    post estimations_path, params: params(attachments: files)

    assert_redirected_to estimation_path(7)
    assert_requested(:post, SESSION_ESTIMATE_URL) do |req|
      body = req.body.dup.force_encoding(Encoding::BINARY)
      body.scan(/name="attachments"; filename="([^"]+)"/).flatten == %w[requisitos.pdf alcance.docx] &&
        body.include?("%PDF-uno") && body.include?("PK-dos")
    end
  end

  test "a short message is accepted when there are attachments" do
    stub_estimate

    post estimations_path, params: params(description: "Revisa", attachments: [ upload("req.pdf") ])

    assert_redirected_to estimation_path(7)
  end

  test "an empty attachments value (no file chosen) is ignored" do
    stub_estimate

    post estimations_path, params: params(attachments: [ "" ])

    assert_redirected_to estimation_path(7)
  end

  test "invalid attachments are rejected without calling the API" do
    [ [ [ upload("notas.txt") ], EstimationForm::ATTACHMENT_TYPE_MESSAGE ],
      [ [ upload("grande.pdf", "x" * (EstimationForm::MAX_ATTACHMENT_BYTES + 1)) ], EstimationForm::ATTACHMENT_SIZE_MESSAGE ],
      [ Array.new(6) { |n| upload("#{n}.pdf") }, EstimationForm::ATTACHMENT_COUNT_MESSAGE ] ].each do |files, message|
      post estimations_path, params: params(attachments: files)

      assert_response :unprocessable_content
      assert_select "#form-errors", text: /#{Regexp.escape(message)}/
    end
    assert_not_requested :post, /estimate/
  end

  test "an attachment rejected by the API shows its message and keeps the form" do
    message = "No se pudo extraer texto de «escaneado.pdf» (¿está escaneado o vacío?)."
    stub_estimate({ "detail" => message }, status: 422)

    post estimations_path, params: params(attachments: [ upload("escaneado.pdf") ])

    assert_response :unprocessable_content
    assert_select "#form-errors", text: /#{Regexp.escape(message)}/
    assert_select "textarea#description", text: /#{DESCRIPTION}/
  end

  # --- Metadatos del proyecto ---

  test "the sidebar starts with an empty metadata panel and the new conversation button" do
    get root_path

    assert_select "aside#sidebar h2", text: "Metadatos del proyecto"
    assert_select "#no-project-metadata", text: /Aún no hay datos del proyecto/
    assert_select "aside#sidebar form[action='#{conversation_path}'] button#new-conversation", text: "Nueva conversación"
  end

  test "the metadata returned by the API is shown on the result page and on later pages" do
    stub_estimate(estimate_body(project_metadata: PROJECT_METADATA))
    stub_request(:get, "#{API}/api/v1/estimations/7").to_return(json_response(detail_body))

    post estimations_path, params: params
    follow_redirect!

    assert_select "#metadata-name", text: "Orion"
    assert_select "#metadata-team", text: "4"
    assert_select "#metadata-technologies", text: "FastAPI, Kafka"
    assert_select "#metadata-scope", text: "Portal y panel de administración"
    assert_select "#no-project-metadata", false

    get root_path
    assert_select "#metadata-name", text: "Orion"
  end

  test "metadata are shown when the result is rendered without history" do
    stub_estimate(estimate_body(id: nil, project_metadata: PROJECT_METADATA))

    post estimations_path, params: params

    assert_response :success
    assert_select "#metadata-technologies", text: "FastAPI, Kafka"
  end

  test "very large metadata do not overflow the cookie session" do
    huge = { "project_name" => "n" * 120, "assumed_team_size" => 1000,
             "mentioned_technologies" => Array.new(30) { |n| "tecnología-#{n}-" + ("t" * 40) },
             "agreed_scope" => "ñ" * 1000 }
    stub_estimate(estimate_body(project_metadata: huge))

    post estimations_path, params: params
    get root_path

    assert_response :success
    assert_select "#metadata-name"
    assert_operator response.body[/id="metadata-scope">([^<]*)/, 1].length, :<=, 300
  end

  # --- Nueva conversación ---

  test "new conversation opens another session and clears the metadata" do
    stub_estimate(estimate_body(id: nil, project_metadata: PROJECT_METADATA))
    post estimations_path, params: params
    assert_select "#metadata-name", text: "Orion"
    stub_request(:post, "#{API}/api/v1/sessions").to_return(json_response({ "session_id" => SECOND_ID }, status: 201))

    post conversation_path

    assert_redirected_to root_path
    follow_redirect!
    assert_select "#no-project-metadata"
    assert_select "#metadata-name", false
    assert_equal 2, sessions_requested

    second = stub_estimate(estimate_body, url: "#{API}/api/v1/sessions/#{SECOND_ID}/estimate")
    post estimations_path, params: params
    assert_requested second
  end

  test "new conversation works even if the API cannot open the session right now" do
    get root_path
    stub_request(:post, "#{API}/api/v1/sessions").to_return(status: 503)

    post conversation_path

    assert_redirected_to root_path
    follow_redirect!
    assert_response :success
    assert_select "#no-project-metadata"
  end

  # --- Sesión caducada ---

  test "when the API lost the session a new one is opened and the user is told" do
    stub_estimate({ "detail" => "Session not found or expired" }, status: 404)
    get root_path
    stub_request(:post, "#{API}/api/v1/sessions").to_return(json_response({ "session_id" => SECOND_ID }, status: 201))

    post estimations_path, params: params(project_type: "data_pipeline")

    assert_response :success
    assert_select "#conversation-notice", text: /La conversación anterior expiró/
    assert_select "#form-errors", false
    assert_select "textarea#description", text: /#{DESCRIPTION}/
    assert_select "select[name='estimation_form[project_type]'] option[selected][value=data_pipeline]"
    assert_select "#no-project-metadata"
    assert_equal 2, sessions_requested

    second = stub_estimate(estimate_body, url: "#{API}/api/v1/sessions/#{SECOND_ID}/estimate")
    post estimations_path, params: params
    assert_requested second
  end
end
