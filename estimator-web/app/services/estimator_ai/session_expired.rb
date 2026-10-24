module EstimatorAi
  # La API ya no conoce la sesión (reinicio del servicio o caducidad): hay que abrir otra conversación.
  class SessionExpired < NotFound
    def initialize
      super(BaseClient::SESSION_EXPIRED_MESSAGE, status: 404)
    end
  end
end
