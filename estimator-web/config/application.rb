require_relative "boot"

require "rails"
require "active_model/railtie"
require "action_controller/railtie"
require "action_view/railtie"
require "rails/test_unit/railtie"

Bundler.require(*Rails.groups)

module EstimatorWeb
  class Application < Rails::Application
    config.load_defaults 8.1

    config.autoload_lib(ignore: %w[assets tasks])

    config.generators.system_tests = nil

    # API del estimador. La URL es interna (red de Compose) y nunca se muestra al usuario.
    config.x.estimator_api_url = ENV.fetch("ESTIMATOR_API_URL", "http://localhost:8000")
    config.x.estimator_open_timeout = Float(ENV.fetch("ESTIMATOR_OPEN_TIMEOUT", "5"))
    # Una transcripción larga puede tardar minutos en estimarse.
    config.x.estimator_read_timeout = Float(ENV.fetch("ESTIMATOR_READ_TIMEOUT", "300"))
  end
end
