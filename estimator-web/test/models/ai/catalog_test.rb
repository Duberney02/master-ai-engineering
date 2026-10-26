require "test_helper"

# Los contratos del contexto de configuración reflejan GET /api/v1/config/models.
class AiCatalogTest < ActiveSupport::TestCase
  def catalog(**options)
    Ai::Catalog.from_hash(config_body(**options))
  end

  test "keeps the seven knobs in screen order" do
    assert_equal Ai::ModelConfig::KEYS, catalog.model_configs.map(&:key)
    assert_equal 7, Ai::ModelConfig::KEYS.size
  end

  test "the embedding model is read-only and not a knob" do
    result = catalog

    assert_equal "text-embedding-3-small", result.embedding_model
    assert_includes result.embedding_model_note, "invalidaría"
    refute_includes Ai::ModelConfig::KEYS, "embedding_model"
  end

  test "exposes effective, default and overridden per knob" do
    config = catalog(overrides: { "primary_model" => "gpt-4o" }).model_configs.first

    assert_equal "gpt-4o", config.effective
    assert_equal "gpt-4o-mini", config.default
    assert config.overridden
    assert_equal "Modelo primario", config.label
  end

  test "primary_model and any_overridden? summarize the snapshot" do
    assert_equal "gpt-4o-mini", catalog.primary_model
    refute catalog.any_overridden?
    assert catalog(overrides: { "critic_model" => "gpt-4o" }).any_overridden?
  end

  test "chunker knobs only offer models of the provider they use" do
    result = catalog
    propositional = result.model_configs.find { |config| config.key == "propositional_chunker_model" }
    contextual = result.model_configs.find { |config| config.key == "contextual_chunker_model" }
    primary = result.model_configs.first

    assert_equal %w[gpt-4o-mini gpt-4o], result.options_for(propositional)
    assert_equal %w[claude-haiku-4-5 claude-sonnet-4-5], result.options_for(contextual)
    assert_equal result.available_models, result.options_for(primary)
  end

  test "knobs missing from the response are skipped" do
    body = config_body
    body["models"].delete("fallback_model")

    assert_equal 6, Ai::Catalog.from_hash(body).model_configs.size
  end
end
