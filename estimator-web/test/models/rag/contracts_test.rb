require "test_helper"

# Los contratos del contexto RAG reflejan los schemas Pydantic de POST /embeddings/compare.
class RagContractsTest < ActiveSupport::TestCase
  def response(**options)
    Rag::ComparisonResponse.from_hash(compare_body(**options))
  end

  test "strategy catalog mirrors the eight strategies of the service in canonical order" do
    assert_equal %w[structural fixed_size recursive sentence_window hierarchical semantic propositional contextual_retrieval],
                 Rag::Strategy::ALL_NAMES
  end

  test "free strategies are the default and paid ones are opt-in" do
    assert_equal %w[structural fixed_size recursive], Rag::Strategy.defaults
    assert Rag::Strategy.defaults.none? { |name| Rag::Strategy.paid?(name) }
    assert_equal %w[semantic propositional contextual_retrieval], Rag::Strategy::ALL_NAMES.select { |name| Rag::Strategy.paid?(name) }
  end

  test "paid strategies declare the provider key they need" do
    assert_equal %w[OPENAI_API_KEY ANTHROPIC_API_KEY], Rag::Strategy.keys_needed(%w[semantic structural contextual_retrieval propositional])
    assert_empty Rag::Strategy.keys_needed(Rag::Strategy.defaults)
    assert Rag::Strategy.paid_selected?(%w[structural propositional])
    refute Rag::Strategy.paid_selected?(%w[structural magic])
  end

  test "stats mirror ChunkingStats including the token distribution" do
    stats = response.stats_for("structural")

    assert_equal 10, stats.n_chunks
    assert_equal 79.0, stats.token_distribution.p50
    assert_equal 300, stats.token_distribution.max
    assert stats.free?
    refute stats.orphans?
  end

  test "unknown attributes from a newer service are ignored" do
    body = compare_body(strategies: %w[structural])
    body["stats_per_strategy"]["structural"]["something_new"] = 1
    body["stats_per_strategy"]["structural"]["token_distribution"]["p99"] = 5

    assert_equal 10, Rag::ComparisonResponse.from_hash(body).stats_for("structural").n_chunks
  end

  test "strategy names keep the canonical order and queries are unique" do
    full = response(strategies: %w[hierarchical structural], queries: [ "a", "b" ])

    assert_equal %w[structural hierarchical], full.strategy_names
    assert_equal [ "a", "b" ], full.queries
    assert full.any_queries?
    refute response.any_queries?
  end

  test "results are grouped by strategy for one query" do
    grouped = response(queries: [ "oauth" ]).results_by_strategy_for("oauth")

    assert_equal %w[structural hierarchical], grouped.map(&:first)
    assert_equal "oauth", grouped.first.last.query
  end

  test "hierarchical top chunks expose parent and child level" do
    top = response(queries: [ "oauth" ]).query_results_for("hierarchical").first.top_k

    assert top.first.parent?
    assert top.last.child?
    assert_equal "BUD-1::parent", top.last.parent_chunk_id
    assert_equal 71, top.first.cosine_pct
  end

  test "other strategies have no level" do
    chunk = response(queries: [ "oauth" ]).query_results_for("structural").first.top_k.first

    assert_nil chunk.level
    refute chunk.parent?
    refute chunk.child?
  end

  test "costs add up and the maximum drives the bars" do
    full = response(strategies: %w[structural contextual_retrieval], contextual_cost: 0.14)

    assert_in_delta 0.14, full.total_ingestion_cost_usd
    assert_in_delta 0.14, full.max_ingestion_cost_usd
    assert_equal 0.0, response.max_ingestion_cost_usd
  end

  test "an empty payload yields an empty response" do
    empty = Rag::ComparisonResponse.from_hash({})

    assert_empty empty.strategy_names
    assert_equal 0.0, empty.total_ingestion_cost_usd
  end
end
