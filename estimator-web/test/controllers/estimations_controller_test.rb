require "test_helper"

class EstimationsControllerTest < ActionDispatch::IntegrationTest
  DESCRIPTION = "Portal de clientes para consultar facturas y abrir incidencias de soporte.".freeze

  def params(**overrides)
    { estimation_form: { description: DESCRIPTION, project_type: "web_saas", detail_level: "medium",
                         output_format: "phases_table", prompt_version: "v3" }.merge(overrides) }
  end

  def upload(content, name: "reunion.txt")
    # Rack::Test cambia la codificación del String recibido a binario: se le pasa una copia.
    Rack::Test::UploadedFile.new(StringIO.new(content.dup), "text/plain", original_filename: name)
  end

  def stub_estimate(body = estimate_body, status: 200)
    stub_request(:post, "#{API}/api/v1/estimate").with(query: { prompt_version: "v3" })
      .to_return(json_response(body, status: status))
  end

  # --- Formulario ---

  test "the form shows the fields, the .txt upload, the loading indicator and the timer" do
    get root_path

    assert_response :success
    assert_select "textarea#description[maxlength='80000']"
    assert_select "input#upload[type=file][accept*='.txt']"
    assert_select "select[name='estimation_form[project_type]'] option", 4
    assert_select "select[name='estimation_form[prompt_version]'] option[value=v3]"
    assert_select "#loading .spinner"
    assert_select "#timer"
    assert_select "form#estimation-form[enctype='multipart/form-data']"
    assert_includes response.body, "80.000 caracteres"
  end

  # --- Envío correcto ---

  test "a valid submission calls the API and redirects to the saved estimation" do
    stub = stub_estimate

    post estimations_path, params: params

    assert_redirected_to estimation_path(7)
    assert_requested stub
    assert_requested(:post, "#{API}/api/v1/estimate", query: { prompt_version: "v3" }, body: {
      description: DESCRIPTION, project_type: "web_saas", detail_level: "medium", output_format: "phases_table"
    })
  end

  test "without estimation_id (history disabled) the result is rendered directly" do
    stub_estimate(estimate_body(id: nil))

    post estimations_path, params: params

    assert_response :success
    assert_select "#cost", text: /20\.000,00 EUR/
    assert_select "#phases tbody tr", 2
    assert_includes response.body, DESCRIPTION
  end

  test "a .txt file replaces the typed description" do
    stub_estimate
    transcript = "Reunión de kickoff: el cliente quiere un portal de facturación con alta de incidencias."

    post estimations_path, params: params(description: "texto que se ignora", upload: upload(transcript.dup))

    assert_redirected_to estimation_path(7)
    sent = nil
    assert_requested(:post, "#{API}/api/v1/estimate", query: { prompt_version: "v3" }) { |req| sent = req.body }
    # WebMock entrega el cuerpo como binario: se interpreta como UTF-8 antes de comparar.
    assert_equal transcript, JSON.parse(sent.dup.force_encoding(Encoding::UTF_8))["description"]
  end

  test "an 80000 character transcription is accepted" do
    stub = stub_estimate
    text = ("Planificación del portal de clientes. " * 3000)[0, 80_000]

    post estimations_path, params: params(description: text)

    assert_redirected_to estimation_path(7)
    assert_requested stub
  end

  # --- Rechazos antes de llamar a la API ---

  test "a short description is rejected with the new limits and no API call" do
    post estimations_path, params: params(description: "corta")

    assert_response :unprocessable_content
    assert_select "#form-errors", text: /entre 20 y 80000 caracteres/
    assert_not_requested :post, /estimate/
  end

  test "an over-long description is rejected without calling the API" do
    post estimations_path, params: params(description: "x" * 80_001)

    assert_response :unprocessable_content
    assert_select "#form-errors", text: /entre 20 y 80000 caracteres/
    assert_not_requested :post, /estimate/
  end

  test "invalid files are rejected without calling the API" do
    [ [ upload("a" * 100, name: "doc.pdf"), "texto plano (.txt)" ],
      [ upload("Reunión".encode("ISO-8859-1") * 20), "UTF-8" ],
      [ upload("a" * 400_001), "400 KB" ] ].each do |file, message|
      post estimations_path, params: params(upload: file)

      assert_response :unprocessable_content
      assert_select "#form-errors", text: /#{Regexp.escape(message)}/
    end
    assert_not_requested :post, /estimate/
  end

  test "the form keeps the typed values after a validation error" do
    post estimations_path, params: params(description: "corta", project_type: "data_pipeline")

    assert_select "textarea#description", text: /corta/
    assert_select "select[name='estimation_form[project_type]'] option[selected][value=data_pipeline]"
  end

  # --- Errores de la API ---

  test "a guardrail rejection shows the API message" do
    message = "La descripción contiene un número de teléfono. Elimínalo."
    stub_estimate({ "reason" => "pii_phone", "message" => message }, status: 400)

    post estimations_path, params: params

    assert_response :unprocessable_content
    assert_select "#form-errors", text: /#{Regexp.escape(message)}/
  end

  test "an unreachable API shows a sanitized message and keeps the form" do
    stub_request(:post, "#{API}/api/v1/estimate").with(query: { prompt_version: "v3" })
      .to_raise(Faraday::ConnectionFailed.new("Failed to open TCP connection to estimator-api.test:8000"))

    post estimations_path, params: params

    assert_response :unprocessable_content
    assert_select "#form-errors", text: /No se pudo conectar con la API del estimador/
    refute_includes response.body, "estimator-api.test"
    refute_includes response.body, "TCP"
    assert_select "textarea#description", text: /#{DESCRIPTION}/
  end

  test "a server error never shows the raw API body" do
    stub_request(:post, "#{API}/api/v1/estimate").with(query: { prompt_version: "v3" })
      .to_return(status: 502, body: "Traceback (most recent call last): openai key sk-secret")

    post estimations_path, params: params

    assert_response :unprocessable_content
    assert_select "#form-errors", text: /no pudo completar la solicitud/
    refute_includes response.body, "sk-secret"
  end

  test "an invalid API response shows a generic error" do
    stub_estimate({ "unexpected" => true })

    post estimations_path, params: params

    assert_select "#form-errors", text: /respuesta inválida/
  end

  # --- Resultado ---

  test "the result view shows duration, cost, confidence and the phases table" do
    stub_request(:get, "#{API}/api/v1/estimations/7").to_return(json_response(detail_body(cache_source: "semantic")))

    get estimation_path(7)

    assert_response :success
    assert_select "#confidence", text: "70%"
    assert_select "#duration", text: "10 semanas"
    assert_select "#cost", text: "20.000,00 EUR"
    assert_select "#phases thead th", text: "Fase"
    assert_select "#phases tbody tr:first-child td:first-child", text: "Diseño"
    assert_select "#phases tbody tr:last-child td.num:last-child", text: "16.000,00 EUR"
    assert_select "#estimation-meta", text: /Caché semántica/
    assert_select "#estimation-meta", text: /prompt v3/
    assert_select "#out-of-scope", false
  end

  test "a low confidence result is shown as not estimable without figures" do
    stub_request(:get, "#{API}/api/v1/estimations/8")
      .to_return(json_response(detail_body(id: 8, result: ApiHelpers::OUT_OF_SCOPE)))

    get estimation_path(8)

    assert_select "#out-of-scope", text: /No estimable/
    assert_select "#out-of-scope", text: /la reunión no define el alcance/
    assert_select "#cost", false
    assert_select "#duration", false
    assert_select "#phases", false
    refute_includes response.body, "EUR"
  end

  test "a very long description is truncated in the result view" do
    stub_request(:get, "#{API}/api/v1/estimations/9")
      .to_return(json_response(detail_body(id: 9, description: "palabra " * 10_000)))

    get estimation_path(9)

    assert_operator response.body.length, :<, 20_000
    assert_includes response.body, "caracteres en total"
  end

  test "an unknown estimation renders a 404 page" do
    stub_request(:get, "#{API}/api/v1/estimations/404").to_return(json_response({ "detail" => "Estimation not found" }, status: 404))

    get estimation_path(404)

    assert_response :not_found
    assert_select "#api-error", text: /No se encontró la estimación/
  end

  test "an unreachable API on the result page is a sanitized bad gateway" do
    stub_request(:get, "#{API}/api/v1/estimations/7").to_timeout

    get estimation_path(7)

    assert_response :bad_gateway
    assert_select "#api-error", text: /No se pudo conectar/
  end

  # --- Historial ---

  test "the history lists the latest estimations, newest first, linking to each one" do
    stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 }).to_return(json_response([
      summary_item(id: 3, cache_source: "exact"), summary_item(id: 2, result: ApiHelpers::OUT_OF_SCOPE)
    ]))

    get estimations_path

    assert_response :success
    assert_select "#history tbody tr", 2
    assert_select "#history tbody tr:first-child a[href='#{estimation_path(3)}']"
    assert_select "#history tbody tr:first-child", text: /Caché exacta/
    assert_select "#history tbody tr:first-child", text: /20\.000,00 EUR/
    assert_select "#history tbody tr:last-child", text: /No estimable/
  end

  test "an empty history shows an explanatory message" do
    stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 }).to_return(json_response([]))

    get estimations_path

    assert_response :success
    assert_select "#history-empty"
  end

  test "a disabled history shows a friendly message instead of a technical error" do
    stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 })
      .to_return(json_response({ "detail" => "History is not configured" }, status: 503))

    get estimations_path

    assert_response :success
    assert_select "#history-error", text: /historial no está disponible/
    refute_includes response.body, "not configured"
  end

  test "an unreachable API on the history page shows the connection message" do
    stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 }).to_timeout

    get estimations_path

    assert_response :success
    assert_select "#history-error", text: /No se pudo conectar/
  end

  # --- Barra lateral (equivalente a la de Streamlit) ---

  test "the form page has the left sidebar with the system prompt and few-shot examples" do
    get root_path

    assert_select "aside#sidebar h2", text: "Contexto del prompt"
    assert_select "aside#sidebar textarea#system-prompt[readonly]", text: /arquitecto sénior de estimación/
    assert_select "#few-shot .example", 2
    assert_select "#few-shot", text: /Portal de reservas para un gimnasio/
    assert_select "#few-shot", text: /Plataforma de IA para todo el hospital/
    assert_select "#no-metrics", text: /Aún no se ha generado ninguna estimación/
    assert_select "button#sidebar-toggle"
    assert_requested(:get, "#{API}/api/v1/prompts/estimation", query: { prompt_version: "v3", project_type: "mobile_app",
                                                                      detail_level: "medium", output_format: "phases_table" })
  end

  test "the result page shows the last call metrics in the sidebar" do
    stub_request(:get, "#{API}/api/v1/estimations/7").to_return(json_response(detail_body))

    get estimation_path(7)

    assert_select "#metric-model", text: "gpt-4o-mini"
    assert_select "#metric-prompt-version", text: "v3"
    assert_select "#metric-input-tokens", text: "12.400"
    assert_select "#metric-output-tokens", text: "860"
    assert_select "#metric-latency", text: "8.450"
    assert_select "#metric-cost", text: "0,000412 USD"
    assert_select "#metric-cache", text: "Respuesta generada"
    assert_select "#no-metrics", false
  end

  test "the sidebar prompt follows the options of the viewed estimation" do
    stub_request(:get, "#{API}/api/v1/estimations/7").to_return(json_response(detail_body))

    get estimation_path(7)

    assert_requested(:get, "#{API}/api/v1/prompts/estimation", query: { prompt_version: "v3", project_type: "web_saas",
                                                                      detail_level: "medium", output_format: "phases_table" })
  end

  test "cache hits and unknown prices are labelled" do
    stub_request(:get, "#{API}/api/v1/estimations/7")
      .to_return(json_response(detail_body(cache_source: "exact", metrics: metrics_body(cache_hit: true, cost: nil))))

    get estimation_path(7)

    assert_select "#metric-cache", text: "Respuesta de caché"
    assert_select "#metric-cost", text: "Sin tarifa"
  end

  test "an old record without metrics shows the empty state" do
    stub_request(:get, "#{API}/api/v1/estimations/7").to_return(json_response(detail_body(metrics: nil)))

    get estimation_path(7)

    assert_response :success
    assert_select "#no-metrics"
    assert_select "#last-call", false
  end

  test "the result rendered without history also shows the metrics" do
    stub_estimate(estimate_body(id: nil))

    post estimations_path, params: params

    assert_select "#metric-model", text: "gpt-4o-mini"
  end

  test "the sidebar survives a validation error and the history page has it too" do
    post estimations_path, params: params(description: "corta")
    assert_response :unprocessable_content
    assert_select "aside#sidebar textarea#system-prompt"

    stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 }).to_return(json_response([]))
    get estimations_path
    assert_select "aside#sidebar #few-shot .example", 2
  end

  test "if the prompt cannot be rendered the page still works with a notice" do
    stub_prompt_preview(status: 500)

    get root_path

    assert_response :success
    assert_select "#prompt-unavailable"
    assert_select "form#estimation-form"
    refute_includes response.body, "boom"
  end

  test "the error page has no sidebar" do
    stub_request(:get, "#{API}/api/v1/estimations/404").to_return(json_response({ "detail" => "x" }, status: 404))

    get estimation_path(404)

    assert_select "aside#sidebar", false
  end

  # --- Salud ---

  test "the health probe answers 200" do
    get rails_health_check_path

    assert_response :success
  end
end
