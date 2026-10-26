require "test_helper"

class AiSettingsControllerTest < ActionDispatch::IntegrationTest
  CONFIG_URL = "#{API}/api/v1/config/models".freeze

  test "show lists the seven knobs with their default and effective model" do
    stub_config_models(config_body(overrides: { "critic_model" => "gpt-4o" }))

    get ai_settings_path

    assert_response :success
    assert_select "#models-table tbody tr", count: 7
    assert_select "#knob-critic_model code", text: "gpt-4o"
    assert_select "#knob-critic_model .badge", text: "override"
    assert_select "#knob-primary_model .badge", count: 0
    assert_select "#embedding-model", text: /text-embedding-3-small/
    assert_select "#embedding-model", text: /invalidaría/
  end

  test "each select offers an empty option that means reset to the default" do
    get ai_settings_path

    assert_select "select#models_primary_model option[value='']", text: /Valor por defecto \(gpt-4o-mini\)/
    assert_select "select#models_primary_model option[value='gpt-4o']"
  end

  test "an overridden knob is preselected" do
    stub_config_models(config_body(overrides: { "primary_model" => "gpt-4o" }))

    get ai_settings_path

    assert_select "select#models_primary_model option[selected][value='gpt-4o']"
  end

  test "chunker selects only offer models of their provider" do
    get ai_settings_path

    assert_select "select#models_propositional_chunker_model option[value='claude-sonnet-4-5']", count: 0
    assert_select "select#models_propositional_chunker_model option[value='gpt-4o']"
    assert_select "select#models_contextual_chunker_model option[value='gpt-4o']", count: 0
    assert_select "select#models_contextual_chunker_model option[value='claude-sonnet-4-5']"
  end

  test "update sends every knob, with blanks as nulls, and confirms" do
    stub = stub_request(:put, CONFIG_URL).with { |req|
      JSON.parse(req.body)["models"] == { "primary_model" => "gpt-4o", "critic_model" => nil }
    }.to_return(json_response(config_body(overrides: { "primary_model" => "gpt-4o" })))

    patch ai_settings_path, params: { models: { primary_model: "gpt-4o", critic_model: "" } }

    assert_requested stub
    assert_redirected_to ai_settings_path
    follow_redirect!
    assert_select "#flash-notice", text: /Modelos actualizados/
  end

  test "saving refreshes the navbar indicator at once" do
    Rails.cache = ActiveSupport::Cache::MemoryStore.new
    stub_config_models(config_body)
    get ai_settings_path
    assert_select "#primary-model", text: "gpt-4o-mini"

    stub_request(:put, CONFIG_URL).to_return(json_response(config_body(overrides: { "primary_model" => "gpt-4o" })))
    stub_config_models(config_body(overrides: { "primary_model" => "gpt-4o" }))
    patch ai_settings_path, params: { models: { primary_model: "gpt-4o" } }
    follow_redirect!

    assert_select "#primary-model", text: "gpt-4o"
  ensure
    Rails.cache = ActiveSupport::Cache::NullStore.new
  end

  test "update ignores unknown knobs" do
    stub = stub_request(:put, CONFIG_URL).with { |req| JSON.parse(req.body)["models"].keys == [ "primary_model" ] }
      .to_return(json_response(config_body))

    patch ai_settings_path, params: { models: { primary_model: "gpt-4o", embedding_model: "x" } }

    assert_requested stub
  end

  test "update without any model does not call the service" do
    patch ai_settings_path, params: {}

    assert_redirected_to ai_settings_path
    assert_not_requested :put, CONFIG_URL
  end

  test "a rejected change (400 or 422) is shown with the API detail and the form is kept" do
    stub_request(:put, CONFIG_URL).to_return(
      json_response({ "detail" => "El modelo 'claude-sonnet-4-5' requiere ANTHROPIC_API_KEY, que no está configurada" }, status: 400)
    )

    patch ai_settings_path, params: { models: { primary_model: "claude-sonnet-4-5" } }

    assert_response :unprocessable_content
    assert_select "#flash-alert", text: /Cambio rechazado.*ANTHROPIC_API_KEY/
    assert_select "#models-table tbody tr", count: 7
  end

  test "an unavailable config store is a 503 with the API message" do
    stub_request(:put, CONFIG_URL).to_return(json_response({ "detail" => "El almacén de configuración no está disponible" }, status: 503))

    patch ai_settings_path, params: { models: { primary_model: "gpt-4o" } }

    assert_response :service_unavailable
    assert_select "#flash-alert", text: /almacén de configuración/
  end

  test "an unreachable service on update is a sanitized 503" do
    stub_request(:put, CONFIG_URL).to_raise(Faraday::ConnectionFailed.new("getaddrinfo: estimator-api.test"))

    patch ai_settings_path, params: { models: { primary_model: "gpt-4o" } }

    assert_response :service_unavailable
    assert_select "#flash-alert", text: /No se pudo conectar/
    refute_includes response.body, "estimator-api.test"
  end

  test "an unreachable service on show renders the page without the form" do
    stub_request(:get, CONFIG_URL).to_raise(Faraday::ConnectionFailed.new("down"))

    get ai_settings_path

    assert_response :service_unavailable
    assert_select "#settings-unavailable"
    assert_select "#settings-form", count: 0
    assert_select "#flash-alert", text: /No se pudo leer la configuración/
  end

  test "a server error on show is a bad gateway" do
    stub_request(:get, CONFIG_URL).to_return(status: 500, body: "boom")

    get ai_settings_path

    assert_response :bad_gateway
    assert_select "#settings-unavailable"
  end
end
