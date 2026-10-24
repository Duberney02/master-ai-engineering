require "test_helper"

class EmbeddingsClientTest < ActiveSupport::TestCase
  BUDGETS = [ { "budget_id" => "B-1" } ].freeze

  def client(**options)
    EstimatorAi::EmbeddingsClient.new(base_url: API, **options)
  end

  test "compare_chunking posts the corpus, queries, strategies and top_k" do
    stub = stub_request(:post, "#{API}/embeddings/compare")
      .with(body: { budgets: BUDGETS, queries: [ "oauth" ], strategies: %w[structural], top_k: 2 }.to_json)
      .to_return(json_response(compare_body(strategies: %w[structural], queries: [ "oauth" ])))

    body = client.compare_chunking(budgets: BUDGETS, queries: [ "oauth" ], strategies: %w[structural], top_k: 2)

    assert_requested stub
    assert_equal [ "structural" ], body["stats_per_strategy"].keys
  end

  test "defaults send no queries and no strategies (the API then runs the free ones)" do
    stub = stub_request(:post, "#{API}/embeddings/compare")
      .with(body: { budgets: BUDGETS, queries: [], strategies: [], top_k: 3 }.to_json)
      .to_return(json_response(compare_body))

    client.compare_chunking(budgets: BUDGETS)

    assert_requested stub
  end

  test "an empty corpus is refused before calling the API" do
    assert_raises(ArgumentError) { client.compare_chunking(budgets: []) }
  end

  test "400, 503 and 500 carry the API detail as typed errors" do
    url = "#{API}/embeddings/compare"

    stub_request(:post, url).to_return(json_response({ "detail" => "Estrategia desconocida: magic" }, status: 400))
    assert_includes assert_raises(EstimatorAi::InvalidRequest) { client.compare_chunking(budgets: BUDGETS) }.message, "magic"

    stub_request(:post, url).to_return(json_response({ "detail" => "La estrategia 'contextual_retrieval' requiere ANTHROPIC_API_KEY." }, status: 503))
    assert_includes assert_raises(EstimatorAi::ServiceUnavailable) { client.compare_chunking(budgets: BUDGETS) }.message, "ANTHROPIC_API_KEY"

    stub_request(:post, url).to_return(json_response({ "detail" => "No se pudo ejecutar la comparación de chunking." }, status: 500))
    assert_raises(EstimatorAi::ServerError) { client.compare_chunking(budgets: BUDGETS) }
  end

  test "a per-instance read timeout does not change the global default" do
    default = Rails.configuration.x.estimator_read_timeout

    stub_request(:post, "#{API}/embeddings/compare").to_return(json_response(compare_body))
    client(read_timeout: 600).compare_chunking(budgets: BUDGETS)

    assert_equal default, Rails.configuration.x.estimator_read_timeout
    assert_operator Rails.configuration.x.estimator_compare_timeout, :>, default
  end

  test "an out-of-contract response is invalid" do
    stub_request(:post, "#{API}/embeddings/compare").to_return(json_response({ "x" => 1 }))

    assert_raises(EstimatorAi::InvalidResponse) { client.compare_chunking(budgets: BUDGETS) }
  end
end
