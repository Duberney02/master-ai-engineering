require "test_helper"

class EstimatorApiTest < ActiveSupport::TestCase
  ATTRIBUTES = { "description" => "Portal de clientes para facturas.", "project_type" => "web_saas",
                 "detail_level" => "medium", "output_format" => "phases_table" }.freeze

  def api
    EstimatorApi.new(base_url: API)
  end

  def assert_api_error(expected_message, status: nil)
    error = assert_raises(EstimatorApi::Error) { yield }
    assert_equal expected_message, error.message
    assert_equal status, error.status if status
    refute_includes error.message, "estimator-api.test", "no debe exponer la URL interna"
    error
  end

  test "create_estimation posts the typed request with the prompt version" do
    stub = stub_request(:post, "#{API}/api/v1/estimate").with(query: { prompt_version: "v2" }, body: ATTRIBUTES)
      .to_return(json_response(estimate_body))

    response = api.create_estimation(ATTRIBUTES, prompt_version: "v2")

    assert_requested stub
    assert_equal 7, response["estimation_id"]
    assert_equal 20_000, response["result"]["total_cost_eur"]
  end

  test "create_estimation sends a JSON body" do
    stub_request(:post, "#{API}/api/v1/estimate").to_return(json_response(estimate_body))

    api.create_estimation(ATTRIBUTES)

    assert_requested(:post, "#{API}/api/v1/estimate") { |req| req.headers["Content-Type"].start_with?("application/json") }
  end

  test "400 shows the guardrail message from the API" do
    message = "La descripción contiene una dirección de correo electrónico. Elimínala."
    stub_request(:post, "#{API}/api/v1/estimate")
      .to_return(json_response({ "reason" => "pii_email", "message" => message }, status: 400))

    assert_api_error(message, status: 400) { api.create_estimation(ATTRIBUTES) }
  end

  test "400 without a usable message gets a generic rejection" do
    stub_request(:post, "#{API}/api/v1/estimate").to_return(status: 400, body: "<html>proxy</html>")

    assert_api_error(EstimatorApi::REJECTED_MESSAGE, status: 400) { api.create_estimation(ATTRIBUTES) }
  end

  test "400 messages are truncated" do
    stub_request(:post, "#{API}/api/v1/estimate").to_return(json_response({ "message" => "x" * 1000 }, status: 400))

    error = assert_raises(EstimatorApi::Error) { api.create_estimation(ATTRIBUTES) }

    assert_equal EstimatorApi::GUARDRAIL_MESSAGE_LIMIT, error.message.length
  end

  test "422 gets a validation message without the response body" do
    body = { "detail" => [ { "loc" => [ "body", "description" ], "msg" => "secret detail" } ] }
    stub_request(:post, "#{API}/api/v1/estimate").to_return(json_response(body, status: 422))

    error = assert_api_error(EstimatorApi::VALIDATION_MESSAGE, status: 422) { api.create_estimation(ATTRIBUTES) }
    refute_includes error.message, "secret detail"
  end

  test "5xx never leaks the response body" do
    stub_request(:post, "#{API}/api/v1/estimate").to_return(status: 502, body: "Traceback: db password=hunter2")

    error = assert_api_error(EstimatorApi::SERVER_MESSAGE, status: 502) { api.create_estimation(ATTRIBUTES) }
    refute_includes error.message, "hunter2"
  end

  test "connection failures are translated" do
    stub_request(:post, "#{API}/api/v1/estimate").to_raise(Faraday::ConnectionFailed.new("getaddrinfo: estimator-api.test"))

    assert_api_error(EstimatorApi::CONNECTION_MESSAGE) { api.create_estimation(ATTRIBUTES) }
  end

  test "timeouts are translated" do
    stub_request(:post, "#{API}/api/v1/estimate").to_timeout

    assert_api_error(EstimatorApi::CONNECTION_MESSAGE) { api.create_estimation(ATTRIBUTES) }
  end

  test "non-JSON and out-of-contract 200 responses are invalid" do
    stub_request(:post, "#{API}/api/v1/estimate").to_return(status: 200, body: "<html>no es json</html>")
    assert_api_error(EstimatorApi::INVALID_RESPONSE_MESSAGE) { api.create_estimation(ATTRIBUTES) }

    stub_request(:post, "#{API}/api/v1/estimate").to_return(json_response({ "nope" => 1 }))
    assert_api_error(EstimatorApi::INVALID_RESPONSE_MESSAGE) { api.create_estimation(ATTRIBUTES) }

    stub_request(:post, "#{API}/api/v1/estimate").to_return(json_response([ 1, 2 ]))
    assert_api_error(EstimatorApi::INVALID_RESPONSE_MESSAGE) { api.create_estimation(ATTRIBUTES) }
  end

  test "list_estimations requests the limit and returns the items" do
    stub = stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 })
      .to_return(json_response([ summary_item(id: 2), summary_item(id: 1) ]))

    items = api.list_estimations

    assert_requested stub
    assert_equal [ 2, 1 ], items.map { |item| item["id"] }
  end

  test "list_estimations maps 503 to the history-unavailable message" do
    stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 })
      .to_return(json_response({ "detail" => "History is not configured" }, status: 503))

    assert_api_error(EstimatorApi::HISTORY_UNAVAILABLE_MESSAGE, status: 503) { api.list_estimations }
  end

  test "list_estimations rejects a non-array body" do
    stub_request(:get, "#{API}/api/v1/estimations").with(query: { limit: 10 }).to_return(json_response({ "a" => 1 }))

    assert_api_error(EstimatorApi::INVALID_RESPONSE_MESSAGE) { api.list_estimations }
  end

  test "find_estimation returns the detail" do
    stub_request(:get, "#{API}/api/v1/estimations/7").to_return(json_response(detail_body))

    assert_equal "v3", api.find_estimation("7")["prompt_version"]
  end

  test "find_estimation 404 and non numeric ids are not found" do
    stub_request(:get, "#{API}/api/v1/estimations/99").to_return(json_response({ "detail" => "Estimation not found" }, status: 404))

    assert_api_error(EstimatorApi::NOT_FOUND_MESSAGE, status: 404) { api.find_estimation(99) }
    assert_api_error(EstimatorApi::NOT_FOUND_MESSAGE, status: 404) { api.find_estimation("../etc/passwd") }
  end

  test "prompt_preview requests the rendered prompt for the given options" do
    stub = stub_request(:get, "#{API}/api/v1/prompts/estimation")
      .with(query: { prompt_version: "v2", project_type: "web_saas", detail_level: "detailed", output_format: "narrative" })
      .to_return(json_response(prompt_body(version: "v2")))

    preview = api.prompt_preview(prompt_version: "v2", project_type: "web_saas", detail_level: "detailed", output_format: "narrative")

    assert_requested stub
    assert_equal "v2", preview["prompt_version"]
    assert_equal 2, preview["examples"].size
  end

  test "prompt_preview rejects a body without the system prompt" do
    stub_request(:get, "#{API}/api/v1/prompts/estimation").with(query: hash_including({})).to_return(json_response({ "x" => 1 }))

    assert_api_error(EstimatorApi::INVALID_RESPONSE_MESSAGE) do
      api.prompt_preview(prompt_version: "v3", project_type: "web_saas", detail_level: "medium", output_format: "phases_table")
    end
  end

  test "defaults come from the application configuration" do
    stub_request(:get, "#{API}/api/v1/estimations/1").to_return(json_response(detail_body(id: 1)))

    assert_equal 1, EstimatorApi.new.find_estimation(1)["id"]
  end
end
