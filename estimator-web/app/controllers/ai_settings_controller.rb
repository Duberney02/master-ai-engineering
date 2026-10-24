# Ajustes del servicio IA: modelos del LLM en tiempo de ejecución. Lee y escribe GET/PUT /api/v1/config/models; el
# cambio aplica desde la siguiente solicitud, sin tocar `.env` ni reiniciar nada. Solo transporte: la validación y
# la persistencia de los overrides son del servicio.
class AiSettingsController < ApplicationController
  def show
    @catalog = load_catalog
  rescue EstimatorAi::Error => error
    @catalog = nil
    flash.now[:alert] = "No se pudo leer la configuración del servicio IA: #{error.message}"
    render :show, status: status_for(error)
  end

  def update
    changes = sanitized_changes
    return redirect_to(ai_settings_path, alert: "No hay ningún modelo que cambiar.") if changes.empty?

    config_client.update_models(changes)
    # El indicador de la barra cachea el primario unos segundos: se descarta para que el cambio se vea ya.
    Rails.cache.delete(AiSettingsHelper::CACHE_KEY)
    redirect_to ai_settings_path, notice: "Modelos actualizados. El cambio aplica desde la siguiente solicitud."
  rescue EstimatorAi::Error => error
    flash.now[:alert] = error.is_a?(EstimatorAi::InvalidRequest) ? "Cambio rechazado: #{error.message}" : error.message
    @catalog = reload_catalog
    render :show, status: status_for(error)
  end

  private

  def config_client
    @config_client ||= EstimatorAi::ConfigClient.new
  end

  def load_catalog
    Ai::Catalog.from_hash(config_client.models)
  end

  # Tras un rechazo se vuelve a leer lo vigente; si tampoco se puede, la pantalla se muestra sin formulario.
  def reload_catalog
    load_catalog
  rescue EstimatorAi::Error
    nil
  end

  # Cada guardado envía todos los knobs; un select vacío significa «usar el valor por defecto» (restablecer).
  def sanitized_changes
    submitted = params.fetch(:models, {}).permit(*Ai::ModelConfig::KEYS).to_h
    submitted.transform_values(&:presence)
  end

  def status_for(error)
    case error
    when EstimatorAi::InvalidRequest then :unprocessable_content
    when EstimatorAi::ConnectionFailed, EstimatorAi::ServiceUnavailable then :service_unavailable
    else :bad_gateway
    end
  end
end
