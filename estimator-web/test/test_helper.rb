ENV["RAILS_ENV"] ||= "test"
require_relative "../config/environment"
require "rails/test_help"
require "webmock/minitest"

# Las pruebas nunca llaman a la API real: todo acceso de red no simulado falla.
WebMock.disable_net_connect!

API = "http://estimator-api.test".freeze

module ApiHelpers
  RESULT = {
    "summary" => "Portal mediano con facturación y soporte.",
    "confidence_pct" => 70,
    "total_duration_weeks" => 10,
    "total_cost_eur" => 20_000,
    "out_of_scope" => false,
    "phases" => [
      { "name" => "Diseño", "description" => "UX y prototipos", "duration_weeks" => 2, "cost_eur" => 4000 },
      { "name" => "Desarrollo", "description" => "App y API", "duration_weeks" => 8, "cost_eur" => 16_000 }
    ]
  }.freeze

  OUT_OF_SCOPE = {
    "summary" => "Out of scope: la reunión no define el alcance.",
    "confidence_pct" => 12,
    "total_duration_weeks" => 1,
    "total_cost_eur" => 0,
    "out_of_scope" => true,
    "phases" => [ { "name" => "No estimable", "description" => "", "duration_weeks" => 1, "cost_eur" => 0 } ]
  }.freeze

  def estimate_body(result: RESULT, id: 7, cache_source: "none")
    { "result" => result, "prompt_version" => "v3", "cached" => cache_source != "none",
      "cache_source" => cache_source, "estimation_id" => id, "metrics" => metrics_body }
  end

  def detail_body(id: 7, result: RESULT, cache_source: "none", metrics: metrics_body, description: "Portal de clientes para facturas e incidencias.")
    { "id" => id, "requested_at" => "2026-10-05T10:30:00Z", "completed_at" => "2026-10-05T10:30:09Z",
      "description" => description,
      "options" => { "project_type" => "web_saas", "detail_level" => "medium", "output_format" => "phases_table" },
      "result" => result, "prompt_version" => "v3", "cached" => cache_source != "none",
      "cache_source" => cache_source, "model" => "gpt-4o-mini", "provider" => "openai", "metrics" => metrics }
  end

  def summary_item(id: 7, result: RESULT, cache_source: "none")
    { "id" => id, "requested_at" => "2026-10-05T10:30:00Z", "project_type" => "web_saas",
      "detail_level" => "medium", "output_format" => "phases_table", "prompt_version" => "v3",
      "cache_source" => cache_source, "confidence_pct" => result["confidence_pct"],
      "total_cost_eur" => result["total_cost_eur"], "total_duration_weeks" => result["total_duration_weeks"],
      "out_of_scope" => result["out_of_scope"], "description_excerpt" => "Portal de clientes para facturas" }
  end

  SYSTEM_PROMPT = "Eres un arquitecto sénior de estimación de software.

## Instrucciones generales
1. Basa la estimación solo en la descripción.".freeze

  def prompt_body(version: "v3")
    { "prompt_version" => version, "system_prompt" => SYSTEM_PROMPT,
      "examples" => [ { "title" => "Portal de reservas para un gimnasio", "description" => "Web donde los socios reservan clases." },
                    { "title" => "Plataforma de IA para todo el hospital", "description" => "Queremos una IA que mejore el hospital." } ] }
  end

  def metrics_body(cache_hit: false, cost: 0.000412)
    { "model" => "gpt-4o-mini", "provider" => "openai", "finish_reason" => "stop",
      "usage" => { "input_tokens" => 12_400, "output_tokens" => 860, "total_tokens" => 13_260 },
      "latency_ms" => 8450, "cache_hit" => cache_hit, "estimated_cost_usd" => cost, "request_cost_usd" => cost }
  end

  def stub_prompt_preview(status: 200)
    stub_request(:get, "#{API}/api/v1/prompts/estimation").with(query: hash_including({}))
      .to_return(status == 200 ? json_response(prompt_body) : { status: status, body: "boom" })
  end

  def json_response(body, status: 200)
    { status: status, body: body.to_json, headers: { "Content-Type" => "application/json" } }
  end
end

class ActiveSupport::TestCase
  include ApiHelpers

  setup do
    Rails.configuration.x.estimator_api_url = API
    stub_prompt_preview
  end
end
