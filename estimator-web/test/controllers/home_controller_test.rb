require "test_helper"

class HomeControllerTest < ActionDispatch::IntegrationTest
  test "the landing page is the dashboard with one card per context" do
    get root_path

    assert_response :success
    assert_select "#home-estimations a[href=?]", new_estimation_path
    assert_select "#home-rag a[href=?]", new_rag_chunking_comparison_path
    assert_select "#home-settings a[href=?]", ai_settings_path
  end

  test "the layout renders without the service: the primary-model badge just disappears" do
    stub_request(:get, "#{API}/api/v1/config/models").to_raise(Faraday::ConnectionFailed.new("down"))

    get root_path

    assert_response :success
    assert_select "#primary-model", count: 0
    assert_select "nav a", minimum: 5
  end

  test "the navbar shows the effective primary model" do
    stub_config_models(config_body(overrides: { "primary_model" => "gpt-4o" }))

    get root_path

    assert_select "#primary-model", text: "gpt-4o"
  end

  test "the navbar marks the active section on every screen" do
    {
      root_path => "Inicio",
      new_estimation_path => "Nueva estimación",
      estimations_path => "Historial",
      new_rag_chunking_comparison_path => "Chunking Lab",
      ai_settings_path => "Ajustes"
    }.each do |path, label|
      stub_request(:get, "#{API}/api/v1/estimations").with(query: hash_including({})).to_return(json_response([]))
      get path

      assert_select "nav a.active", count: 1, text: label
      assert_select "nav a[aria-current=page]", count: 1
    end
  end
end
