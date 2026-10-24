require "test_helper"

class ConfigClientTest < ActiveSupport::TestCase
  def client
    EstimatorAi::ConfigClient.new(base_url: API)
  end

  test "models returns the snapshot" do
    stub_request(:get, "#{API}/api/v1/config/models").to_return(json_response(config_body(overrides: { "primary_model" => "gpt-4o" })))

    body = client.models

    assert_equal "gpt-4o", body.dig("models", "primary_model", "effective")
    assert_equal true, body.dig("models", "primary_model", "overridden")
    assert_includes body["available_models"], "claude-sonnet-4-5"
  end

  test "update_models sends a partial body with nulls to reset" do
    stub = stub_request(:put, "#{API}/api/v1/config/models")
      .with(body: { models: { primary_model: "gpt-4o", critic_model: nil } }.to_json)
      .to_return(json_response(config_body(overrides: { "primary_model" => "gpt-4o" })))

    body = client.update_models("primary_model" => "gpt-4o", "critic_model" => nil)

    assert_requested stub
    assert_equal "gpt-4o", body.dig("models", "primary_model", "effective")
  end

  test "update_models refuses an empty change" do
    assert_raises(ArgumentError) { client.update_models({}) }
  end

  test "a response without models is invalid" do
    stub_request(:get, "#{API}/api/v1/config/models").to_return(json_response({ "x" => 1 }))

    assert_raises(EstimatorAi::InvalidResponse) { client.models }
  end
end
