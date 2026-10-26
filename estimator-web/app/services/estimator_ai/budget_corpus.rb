module EstimatorAi
  # Corpus estático que viaja con el cliente: los 15 presupuestos de ejemplo del estimador más tres casos límite
  # (monolito obeso, tareas mínimas, descripciones de varias frases) y las consultas de referencia. Los presupuestos
  # se envían tal cual en el cuerpo de la comparación; FastAPI los valida con Pydantic.
  #
  # Son datos de referencia (no código ni semillas de base de datos), en lib/estimator_ai/data/. Si el corpus del
  # estimador evoluciona (`estimador-cag/data/`), hay que volver a copiar los tres archivos.
  class BudgetCorpus
    LABEL = "budgets_sample + budgets_stress_cases".freeze
    DATA_DIR = Rails.root.join("lib", "estimator_ai", "data")
    BUDGET_FILES = %w[budgets_sample.json budgets_stress_cases.json].freeze

    def self.budgets
      @budgets ||= BUDGET_FILES.flat_map { |name| JSON.parse(File.read(DATA_DIR.join(name))) }.freeze
    end

    def self.sample_queries
      @sample_queries ||= JSON.parse(File.read(DATA_DIR.join("test_queries.json"))).freeze
    end
  end
end
