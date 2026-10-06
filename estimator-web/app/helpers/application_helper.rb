module ApplicationHelper
  LABELS = {
    "mobile_app" => "App móvil", "web_saas" => "SaaS web", "internal_tool" => "Herramienta interna",
    "data_pipeline" => "Pipeline de datos",
    "summary" => "Resumen", "medium" => "Medio", "detailed" => "Detallado",
    "phases_table" => "Tabla de fases", "line_items" => "Partidas", "narrative" => "Narrativa"
  }.freeze

  CACHE_SOURCES = { "none" => "Generada", "exact" => "Caché exacta", "semantic" => "Caché semántica" }.freeze
  OUT_OF_SCOPE_PREFIX = "Out of scope:".freeze

  def label_for(value)
    LABELS.fetch(value.to_s, value.to_s)
  end

  def options_for_labels(values)
    values.map { |value| [ label_for(value), value ] }
  end

  def cache_source_label(source)
    CACHE_SOURCES.fetch(source.to_s, "Generada")
  end

  def format_cost(value)
    "#{number_with_precision(value, precision: 2, delimiter: ".", separator: ",")} EUR"
  end

  def format_weeks(value)
    "#{number_with_precision(value, precision: 1, strip_insignificant_zeros: true, separator: ",")} semanas"
  end

  def format_usd(value)
    value.nil? ? "Sin tarifa" : "#{number_with_precision(value, precision: 6, separator: ",")} USD"
  end

  def format_time(iso)
    Time.iso8601(iso.to_s).utc.strftime("%d/%m/%Y %H:%M UTC")
  rescue ArgumentError
    iso.to_s
  end

  def out_of_scope_reason(summary)
    summary.to_s.delete_prefix(OUT_OF_SCOPE_PREFIX).strip
  end
end
