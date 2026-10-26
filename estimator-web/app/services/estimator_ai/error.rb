# Raíz de la taxonomía de errores de la capa HTTP del servicio IA.
#
# Cada error lleva un mensaje en español apto para el usuario: nunca el cuerpo crudo de la respuesta, una traza ni la
# URL interna del servicio. Los controllers capturan estos tipos (jamás Faraday) y los traducen a avisos.
#
#   Error
#   ├── ConnectionFailed            el servicio no responde
#   │   └── RequestTimeout          …o tardó más del tiempo de espera
#   ├── InvalidRequest              400/413/415/422: la petición no es válida
#   ├── GuardrailViolation          400 de los guardrails de entrada (mensaje redactado por la API)
#   ├── NotFound                    404
#   │   └── SessionExpired          la API perdió la sesión de conversación
#   ├── ServiceUnavailable          503
#   ├── ServerError                 otros 5xx
#   └── InvalidResponse             respuesta que no cumple el contrato
module EstimatorAi
  class Error < StandardError
    attr_reader :status

    def initialize(message = nil, status: nil)
      super(message)
      @status = status
    end
  end
end
