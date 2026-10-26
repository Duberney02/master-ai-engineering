module AiSettingsHelper
  CACHE_KEY = "ai:primary_model".freeze
  CACHE_TTL = 15.seconds

  # Modelo primario vigente para el indicador de la barra. Se cachea unos segundos (a lo sumo una llamada HTTP cada
  # 15 s) y es pura decoración: si el servicio no responde, devuelve nil y la barra no muestra nada. Un servicio caído
  # nunca debe impedir ni retrasar el renderizado de una página; el fallo también se cachea para no reintentar en cada una.
  def current_primary_model
    value = Rails.cache.fetch(CACHE_KEY, expires_in: CACHE_TTL) { fetch_primary_model || false }
    value || nil
  rescue StandardError
    nil
  end

  private

  def fetch_primary_model
    config = Rails.configuration.x
    EstimatorAi::ConfigClient.new(open_timeout: config.estimator_badge_timeout, read_timeout: config.estimator_badge_timeout)
      .models.dig("models", "primary_model", "effective")
  rescue EstimatorAi::Error
    nil
  end
end
