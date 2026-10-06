class EstimationsController < ApplicationController
  rescue_from EstimatorApi::Error, with: :render_api_error

  def new
    @form = EstimationForm.new
    load_sidebar(@form.api_attributes, @form.prompt_version)
  end

  def create
    @form = EstimationForm.new(form_params)
    @form.load_upload(params.dig(:estimation_form, :upload))
    return render_form_errors unless @form.errors.empty? && @form.valid?

    response = api.create_estimation(@form.api_attributes, prompt_version: @form.prompt_version)
    if (id = response["estimation_id"])
      redirect_to estimation_path(id)
    else
      # Historial desactivado o no disponible: se muestra el resultado sin enlace permanente.
      @estimation = response.merge("description" => @form.description, "options" => @form.api_attributes)
      load_sidebar(@form.api_attributes, @form.prompt_version, response["metrics"])
      render :show
    end
  rescue EstimatorApi::Error => error
    @form.errors.add(:base, error.message)
    render_form_errors
  end

  def index
    default = EstimationForm.new
    load_sidebar(default.api_attributes, default.prompt_version)
    @estimations = api.list_estimations(limit: 10)
  rescue EstimatorApi::Error => error
    @estimations = []
    @error = error.message
  end

  def show
    @estimation = api.find_estimation(params[:id])
    load_sidebar(@estimation["options"] || {}, @estimation["prompt_version"], @estimation["metrics"])
  end

  private

  def form_params
    params.fetch(:estimation_form, {}).permit(:description, :project_type, :detail_level, :output_format, :prompt_version)
  end

  def api
    @api ||= EstimatorApi.new
  end

  # Barra lateral (como la de Streamlit): prompt de sistema, ejemplos few-shot y métricas de la llamada.
  # Es informativa: si la API no puede renderizar el prompt, la página sigue funcionando.
  def load_sidebar(options, prompt_version, metrics = nil)
    preview = begin
      api.prompt_preview(
        prompt_version: prompt_version, project_type: options["project_type"],
        detail_level: options["detail_level"], output_format: options["output_format"]
      )
    rescue EstimatorApi::Error
      nil
    end
    @sidebar = { preview: preview, metrics: metrics, prompt_version: prompt_version }
  end

  def render_form_errors
    load_sidebar(@form.api_attributes, @form.prompt_version)
    render :new, status: :unprocessable_content
  end

  def render_api_error(error)
    @error = error.message
    render :error, status: (error.status == 404 ? :not_found : :bad_gateway)
  end
end
