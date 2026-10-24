# «Nueva conversación»: descarta la sesión actual y abre otra en la API.
class ConversationsController < ApplicationController
  include ConversationSession

  def create
    begin
      start_conversation(EstimatorAi::SessionsClient.new)
    rescue EstimatorAi::Error
      # Sin API no se puede abrir la sesión ahora: el estado queda limpio y el siguiente envío la crea.
      reset_conversation
    end
    redirect_to new_estimation_path
  end
end
