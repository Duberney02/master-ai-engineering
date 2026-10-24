require "test_helper"

# Taxonomía de errores tipados de la capa HTTP única, común a todos los clientes por contexto.
class BaseClientTest < ActiveSupport::TestCase
  def client
    EstimatorAi::EstimationsClient.new(base_url: API)
  end

  def call
    client.find_estimation(7)
  end

  def error_for(status, body = "boom")
    stub_request(:get, "#{API}/api/v1/estimations/7").to_return(status: status, body: body)
    assert_raises(EstimatorAi::Error) { call }
  end

  test "every typed error descends from EstimatorAi::Error" do
    [ EstimatorAi::ConnectionFailed, EstimatorAi::RequestTimeout, EstimatorAi::InvalidRequest, EstimatorAi::GuardrailViolation,
      EstimatorAi::NotFound, EstimatorAi::SessionExpired, EstimatorAi::ServiceUnavailable, EstimatorAi::ServerError,
      EstimatorAi::InvalidResponse ].each do |error|
      assert_operator error, :<, EstimatorAi::Error
    end
    assert_operator EstimatorAi::RequestTimeout, :<, EstimatorAi::ConnectionFailed
    assert_operator EstimatorAi::SessionExpired, :<, EstimatorAi::NotFound
  end

  test "statuses map to typed errors with sanitized messages" do
    assert_kind_of EstimatorAi::NotFound, error_for(404)
    assert_kind_of EstimatorAi::InvalidRequest, error_for(422)
    assert_kind_of EstimatorAi::ServiceUnavailable, error_for(503)
    assert_kind_of EstimatorAi::ServerError, error_for(500)
    assert_kind_of EstimatorAi::ServerError, error_for(502)
    assert_kind_of EstimatorAi::GuardrailViolation, error_for(400, { "reason" => "pii", "message" => "Hay un correo." }.to_json)
  end

  test "a 400 carries the guardrail message written by the API" do
    error = error_for(400, { "reason" => "pii", "message" => "Elimina el correo." }.to_json)

    assert_equal "Elimina el correo.", error.message
    assert_equal 400, error.status
  end

  test "raw bodies never reach the message" do
    error = error_for(500, "Traceback (most recent call last): secret sk-abc http://estimator-api.test/internal")

    assert_equal EstimatorAi::BaseClient::SERVER_MESSAGE, error.message
    refute_includes error.message, "sk-abc"
    refute_includes error.message, "estimator-api.test"
  end

  test "connection failures and timeouts are typed without leaking the URL" do
    stub_request(:get, "#{API}/api/v1/estimations/7").to_raise(Faraday::ConnectionFailed.new("getaddrinfo: estimator-api.test"))
    refused = assert_raises(EstimatorAi::ConnectionFailed) { call }
    assert_equal EstimatorAi::BaseClient::CONNECTION_MESSAGE, refused.message

    stub_request(:get, "#{API}/api/v1/estimations/7").to_raise(Faraday::TimeoutError.new("read timeout"))
    timed_out = assert_raises(EstimatorAi::RequestTimeout) { call }
    assert_kind_of EstimatorAi::ConnectionFailed, timed_out
    refute_includes timed_out.message, "estimator-api.test"
  end

  test "an out-of-contract 200 is an invalid response" do
    stub_request(:get, "#{API}/api/v1/estimations/7").to_return(json_response({ "nope" => 1 }))

    assert_raises(EstimatorAi::InvalidResponse) { call }
  end

  test "detail mode shows the API detail for 400, 422 and 503, and is typed" do
    stub = ->(status, detail) { stub_request(:put, "#{API}/api/v1/config/models").to_return(json_response({ "detail" => detail }, status: status)) }
    config = EstimatorAi::ConfigClient.new(base_url: API)

    stub.call(400, "El modelo 'x' requiere ANTHROPIC_API_KEY, que no está configurada")
    invalid = assert_raises(EstimatorAi::InvalidRequest) { config.update_models("primary_model" => "x") }
    assert_includes invalid.message, "ANTHROPIC_API_KEY"

    stub.call(422, "Knob desconocido: nope")
    assert_raises(EstimatorAi::InvalidRequest) { config.update_models("nope" => "x") }

    stub.call(503, "El almacén de configuración no está disponible")
    unavailable = assert_raises(EstimatorAi::ServiceUnavailable) { config.update_models("primary_model" => "gpt-4o") }
    assert_equal "El almacén de configuración no está disponible", unavailable.message
  end

  test "the legacy monolithic client is gone" do
    refute defined?(EstimatorApi), "EstimatorApi se sustituyó por un cliente por contexto"
  end
end
