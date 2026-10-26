# Chunking Lab (Sesión 7): compara estrategias de chunking sobre el corpus de presupuestos con
# POST /embeddings/compare y guarda cada ejecución para poder revisarla sin volver a pagar las de pago.
#
# Síncrono a propósito (no hay infraestructura de trabajos en el cliente): la selección por defecto (gratuitas) responde
# en segundos; las de pago son opt-in, se avisan en el formulario y tienen un tiempo de espera propio y mayor. Solo
# transporte: el cálculo es del servicio.
module Rag
  class ChunkingComparisonsController < ApplicationController
    def index
      @comparisons = Rag::ChunkingComparison.order(created_at: :desc).limit(20)
      @comparisons.load
    rescue ActiveRecord::ActiveRecordError => error
      Rails.logger.error("chunking_history_unavailable error_type=#{error.class}")
      @comparisons = []
      flash.now[:alert] = "El historial no está disponible en este momento."
    end

    def new
      @selected_strategies = Rag::Strategy.defaults
      @queries = []
      @top_k = 3
    end

    def create
      read_form
      return render_form_error("Selecciona al menos una estrategia.", :unprocessable_content) if @selected_strategies.empty?

      budgets = EstimatorAi::BudgetCorpus.budgets
      started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
      payload = embeddings_client.compare_chunking(
        budgets: budgets, queries: @queries, strategies: @selected_strategies, top_k: @top_k
      )
      duration_ms = ((Process.clock_gettime(Process::CLOCK_MONOTONIC) - started) * 1000).round

      @comparison = Rag::ChunkingComparison.new(
        strategies: @selected_strategies, queries: @queries, top_k: @top_k, corpus_label: EstimatorAi::BudgetCorpus::LABEL,
        corpus_count: budgets.size, response_payload: payload, duration_ms: duration_ms
      )
      save_and_show
    rescue EstimatorAi::InvalidRequest => error
      render_form_error("Petición inválida: #{error.message}", :unprocessable_content)
    rescue EstimatorAi::RequestTimeout
      render_form_error(timeout_message, :gateway_timeout)
    rescue EstimatorAi::ConnectionFailed, EstimatorAi::ServiceUnavailable => error
      render_form_error(unavailable_message(error), :service_unavailable)
    rescue EstimatorAi::Error => error
      render_form_error("Error del servicio IA: #{error.message}", :bad_gateway)
    end

    def show
      @comparison = Rag::ChunkingComparison.find(params[:id])
      @response = @comparison.to_response
    end

    private

    def embeddings_client
      # Solo esta llamada usa el tiempo de espera ampliado; el global (300 s) sigue en el resto de flujos.
      EstimatorAi::EmbeddingsClient.new(read_timeout: Rails.configuration.x.estimator_compare_timeout)
    end

    def read_form
      @selected_strategies = Array(params[:strategies]).map(&:to_s).select { |name| Rag::Strategy::ALL_NAMES.include?(name) }.uniq
      @queries = (Array(params[:queries]) + params[:custom_queries].to_s.lines).map { |query| query.to_s.strip }.compact_blank.uniq
      @top_k = params[:top_k].to_i.clamp(1, 10)
    end

    # La comparación ya se calculó (y, si usó estrategias de pago, se pagó): si el historial no puede guardarla, se
    # muestra igualmente en lugar de perderla.
    def save_and_show
      @comparison.save!
      redirect_to rag_chunking_comparison_path(@comparison)
    rescue ActiveRecord::ActiveRecordError => error
      Rails.logger.error("chunking_history_save_failed error_type=#{error.class}")
      flash.now[:alert] = "La comparación se calculó, pero no se pudo guardar en el historial."
      @response = @comparison.to_response
      render :show
    end

    def render_form_error(message, status)
      flash.now[:alert] = message
      render :new, status: status
    end

    def timeout_message
      seconds = Rails.configuration.x.estimator_compare_timeout.to_i
      "El servicio IA no respondió en #{seconds} s. Las estrategias de pago pueden tardar varios minutos: prueba con menos estrategias."
    end

    # El 503 de la API nombra la variable de la clave ausente (OPENAI_API_KEY / ANTHROPIC_API_KEY).
    def unavailable_message(error)
      if error.is_a?(EstimatorAi::ServiceUnavailable)
        "El servicio IA no puede ejecutar esa comparación: #{error.message}"
      else
        error.message
      end
    end
  end
end
