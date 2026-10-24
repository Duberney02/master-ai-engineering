require "test_helper"

class ChunkingComparisonTest < ActiveSupport::TestCase
  def build(**attributes)
    Rag::ChunkingComparison.new(
      { strategies: %w[structural hierarchical], queries: [ "oauth" ], top_k: 3, corpus_count: 18, duration_ms: 1500,
        response_payload: compare_body(queries: [ "oauth" ]) }.merge(attributes)
    )
  end

  test "persists the request and the full response as JSON" do
    comparison = build
    comparison.save!

    reloaded = Rag::ChunkingComparison.find(comparison.id)
    assert_equal %w[structural hierarchical], reloaded.strategies
    assert_equal [ "oauth" ], reloaded.queries
    assert_equal 10, reloaded.to_response.stats_for("structural").n_chunks
  end

  test "requires at least one strategy and a top_k between 1 and 10" do
    refute build(strategies: []).valid?
    refute build(top_k: 0).valid?
    refute build(top_k: 11).valid?
    assert build(top_k: 10).valid?
  end

  test "exposes labels, duration and total cost" do
    comparison = build(strategies: %w[structural contextual_retrieval], duration_ms: 1500,
                       response_payload: compare_body(strategies: %w[structural contextual_retrieval], contextual_cost: 0.14))

    assert_equal [ "Estructural", "Contextual retrieval" ], comparison.strategy_labels
    assert_equal 1.5, comparison.duration_seconds
    assert_in_delta 0.14, comparison.total_cost_usd
  end

  test "duration is nil when it was not recorded" do
    assert_nil build(duration_ms: nil).duration_seconds
  end
end
