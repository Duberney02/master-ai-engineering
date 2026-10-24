require "test_helper"

module Rag
  class ChunkingComparisonsControllerTest < ActionDispatch::IntegrationTest
    COMPARE_URL = "#{API}/embeddings/compare".freeze

    def stub_compare(body = compare_body)
      stub_request(:post, COMPARE_URL).to_return(json_response(body))
    end

    def create_run(params = {})
      post rag_chunking_comparisons_path, params: { strategies: %w[structural hierarchical], top_k: 3 }.merge(params)
    end

    # --- Formulario ---

    test "new preselects the free strategies and flags the paid ones" do
      get new_rag_chunking_comparison_path

      assert_response :success
      %w[structural fixed_size recursive].each { |name| assert_select "input#strategy_#{name}[checked]" }
      %w[sentence_window hierarchical semantic propositional contextual_retrieval].each do |name|
        assert_select "input#strategy_#{name}:not([checked])"
      end
      assert_select "input#strategy_propositional[data-paid=true]"
      assert_select "input#strategy_structural[data-paid=false]"
      assert_select ".strategy .badge.expensive", text: "de pago (LLM)", minimum: 2
      assert_select ".strategy .badge", text: "requiere ANTHROPIC_API_KEY"
      assert_select "#paid-warning[hidden]"
    end

    test "new offers the predefined queries and top_k" do
      get new_rag_chunking_comparison_path

      assert_select "input[name='queries[]']", count: EstimatorAi::BudgetCorpus.sample_queries.size
      assert_select "input#top_k[min='1'][max='10'][value='3']"
      assert_select "textarea#custom_queries"
    end

    # --- Ejecución ---

    test "create sends the corpus, strategies, queries and top_k, then saves and redirects" do
      stub = stub_request(:post, COMPARE_URL).with { |req|
        body = JSON.parse(req.body)
        body["strategies"] == %w[structural hierarchical] && body["queries"] == [ "oauth", "otra" ] && body["top_k"] == 2 &&
          body["budgets"].size == EstimatorAi::BudgetCorpus.budgets.size
      }.to_return(json_response(compare_body(queries: [ "oauth", "otra" ])))

      assert_difference -> { Rag::ChunkingComparison.count }, 1 do
        create_run(queries: [ "oauth" ], custom_queries: "otra\n\n  ", top_k: 2)
      end

      assert_requested stub
      comparison = Rag::ChunkingComparison.order(:id).last
      assert_redirected_to rag_chunking_comparison_path(comparison)
      assert_equal [ "oauth", "otra" ], comparison.queries
      assert_equal 2, comparison.top_k
      assert_equal EstimatorAi::BudgetCorpus.budgets.size, comparison.corpus_count
      assert_not_nil comparison.duration_ms
    end

    test "create ignores unknown strategies and clamps top_k" do
      stub = stub_request(:post, COMPARE_URL).with { |req|
        body = JSON.parse(req.body)
        body["strategies"] == %w[structural] && body["top_k"] == 10
      }.to_return(json_response(compare_body(strategies: %w[structural])))

      create_run(strategies: %w[structural magic], top_k: 99)

      assert_requested stub
    end

    test "create without strategies is refused before calling the service" do
      assert_no_difference -> { Rag::ChunkingComparison.count } do
        create_run(strategies: [])
      end

      assert_response :unprocessable_content
      assert_select "#flash-alert", text: /al menos una estrategia/
      assert_not_requested :post, COMPARE_URL
    end

    test "create uses the extended timeout only for this call" do
      captured = []
      original = EstimatorAi::EmbeddingsClient.method(:new)
      recorder = lambda do |**options|
        captured << options
        original.call(**options)
      end
      stub_compare

      with_singleton_stub(EstimatorAi::EmbeddingsClient, :new, recorder) { create_run }

      assert_equal [ { read_timeout: Rails.configuration.x.estimator_compare_timeout } ], captured
      assert_operator Rails.configuration.x.estimator_compare_timeout, :>, Rails.configuration.x.estimator_read_timeout
    end

    # --- Mapeo de errores ---

    test "a 400 from the service is a 422 with its detail" do
      stub_request(:post, COMPARE_URL).to_return(json_response({ "detail" => "Estrategia desconocida: magic" }, status: 400))

      create_run

      assert_response :unprocessable_content
      assert_select "#flash-alert", text: /Petición inválida: Estrategia desconocida/
      assert_select "#lab-form"
    end

    test "a 503 for a missing provider key tells which key" do
      stub_request(:post, COMPARE_URL).to_return(
        json_response({ "detail" => "La estrategia 'contextual_retrieval' requiere ANTHROPIC_API_KEY." }, status: 503)
      )

      create_run(strategies: %w[contextual_retrieval])

      assert_response :service_unavailable
      assert_select "#flash-alert", text: /ANTHROPIC_API_KEY/
    end

    test "a service timeout is a 504 that suggests fewer strategies" do
      stub_request(:post, COMPARE_URL).to_raise(Faraday::TimeoutError.new("read timeout"))

      create_run

      assert_response :gateway_timeout
      assert_select "#flash-alert", text: /no respondió.*menos estrategias/
    end

    test "an unreachable service is a sanitized 503" do
      stub_request(:post, COMPARE_URL).to_raise(Faraday::ConnectionFailed.new("getaddrinfo: estimator-api.test"))

      create_run

      assert_response :service_unavailable
      assert_select "#flash-alert", text: /No se pudo conectar/
      refute_includes response.body, "estimator-api.test"
    end

    test "a server error is a bad gateway" do
      stub_request(:post, COMPARE_URL).to_return(status: 500, body: "Traceback secret")

      create_run

      assert_response :bad_gateway
      assert_select "#flash-alert", text: /Error del servicio IA/
      refute_includes response.body, "Traceback"
    end

    test "if the history cannot save a computed run it is shown anyway" do
      stub_compare
      original_new = Rag::ChunkingComparison.method(:new)
      failing = lambda do |*args, **kwargs|
        original_new.call(*args, **kwargs).tap do |record|
          record.define_singleton_method(:save!) { |*| raise ActiveRecord::ConnectionNotEstablished, "db down" }
        end
      end

      with_singleton_stub(Rag::ChunkingComparison, :new, failing) { create_run }

      assert_response :success
      assert_select "#flash-alert", text: /no se pudo guardar en el historial/
      assert_select "#stats-table"
    end

    # --- Resultados ---

    test "show renders the stats table, cost bars and the retrieval playground" do
      comparison = Rag::ChunkingComparison.create!(
        strategies: %w[structural hierarchical contextual_retrieval], queries: [ "oauth" ], top_k: 2, corpus_count: 18, duration_ms: 3200,
        response_payload: compare_body(strategies: %w[structural hierarchical contextual_retrieval], queries: [ "oauth" ], contextual_cost: 0.14)
      )

      get rag_chunking_comparison_path(comparison)

      assert_response :success
      assert_select "#stats-table tbody tr", count: 3
      assert_select "#stats-structural td", text: "10"
      assert_select "#cost-bars .bar-row", count: 3
      assert_select "#cost-contextual_retrieval", text: /0,140000 USD/
      assert_select "#cost-structural", text: /gratis/
      assert_select "#query-0 .strategies-grid > div", count: 3
      assert_select "#query-0-hierarchical .badge.parent", text: "padre"
      assert_select "#query-0-hierarchical .badge", text: /hijo de BUD-1::parent/
      assert_select "#query-0-structural .badge", count: 0
    end

    test "show of a stats-only run says there were no queries and free runs have no cost bars" do
      comparison = Rag::ChunkingComparison.create!(strategies: %w[structural], top_k: 3, response_payload: compare_body(strategies: %w[structural]))

      get rag_chunking_comparison_path(comparison)

      assert_select "#lab-no-queries"
      assert_select "#lab-playground", count: 0
      assert_select "#cost-free"
      assert_select "#cost-bars", count: 0
    end

    test "show of an unknown run is a 404" do
      get rag_chunking_comparison_path(0)

      assert_response :not_found
    end

    # --- Historial ---

    test "index lists persisted runs, newest first, without calling the service" do
      older = Rag::ChunkingComparison.create!(strategies: %w[structural], top_k: 3, response_payload: compare_body(strategies: %w[structural]), created_at: 2.days.ago)
      newer = Rag::ChunkingComparison.create!(strategies: %w[semantic], top_k: 3, response_payload: compare_body(strategies: %w[structural]), created_at: 1.day.ago)

      get rag_chunking_comparisons_path

      assert_response :success
      links = css_select("#lab-history tbody a").map { |link| link["href"] }
      assert_equal [ rag_chunking_comparison_path(newer), rag_chunking_comparison_path(older) ], links
      assert_not_requested :post, COMPARE_URL
    end

    test "index of an empty history invites to create the first run" do
      get rag_chunking_comparisons_path

      assert_select "#lab-history-empty"
    end

    test "index survives an unavailable database" do
      broken = ->(*) { raise ActiveRecord::ConnectionNotEstablished, "db down" }
      with_singleton_stub(Rag::ChunkingComparison, :order, broken) { get rag_chunking_comparisons_path }

      assert_response :success
      assert_select "#flash-alert", text: /historial no está disponible/
      assert_select "#lab-history-empty"
    end
  end
end
