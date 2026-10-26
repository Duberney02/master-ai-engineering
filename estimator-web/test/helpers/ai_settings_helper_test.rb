require "test_helper"

class AiSettingsHelperTest < ActionView::TestCase
  include AiSettingsHelper

  setup do
    Rails.cache = ActiveSupport::Cache::MemoryStore.new
  end

  teardown do
    Rails.cache = ActiveSupport::Cache::NullStore.new
  end

  test "returns the effective primary model" do
    stub_config_models(config_body(overrides: { "primary_model" => "gpt-4o" }))

    assert_equal "gpt-4o", current_primary_model
  end

  test "is nil when the service is unreachable instead of breaking the page" do
    stub_request(:get, "#{API}/api/v1/config/models").to_raise(Faraday::ConnectionFailed.new("down"))

    assert_nil current_primary_model
  end

  test "is nil on a timeout, a server error or a malformed response" do
    stub_request(:get, "#{API}/api/v1/config/models").to_raise(Faraday::TimeoutError.new("slow"))
    assert_nil current_primary_model

    Rails.cache.clear
    stub_request(:get, "#{API}/api/v1/config/models").to_return(status: 500, body: "boom")
    assert_nil current_primary_model

    Rails.cache.clear
    stub_request(:get, "#{API}/api/v1/config/models").to_return(json_response({ "x" => 1 }))
    assert_nil current_primary_model
  end

  test "caches the answer so the navbar costs at most one call per window" do
    stub = stub_config_models

    3.times { current_primary_model }

    assert_requested stub, times: 1
  end

  test "a failure is cached too, so a dead service is not retried on every page" do
    stub = stub_request(:get, "#{API}/api/v1/config/models").to_raise(Faraday::ConnectionFailed.new("down"))

    3.times { current_primary_model }

    assert_requested stub, times: 1
  end

  test "dropping the cache entry refreshes the indicator" do
    stub_config_models(config_body)
    assert_equal "gpt-4o-mini", current_primary_model

    stub_config_models(config_body(overrides: { "primary_model" => "gpt-4o" }))
    assert_equal "gpt-4o-mini", current_primary_model # sigue la caché

    Rails.cache.delete(AiSettingsHelper::CACHE_KEY)
    assert_equal "gpt-4o", current_primary_model
  end
end
