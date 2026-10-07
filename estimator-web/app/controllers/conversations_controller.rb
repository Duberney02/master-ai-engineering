# «Nueva conversación»: descarta la sesión actual y abre otra en la API.
class ConversationsController < ApplicationController
  include ConversationSession

  def create
    begin
      start_conversation(EstimatorApi.new)
    rescue EstimatorApi::Error
      # Sin API no se puede abrir la sesión ahora: el estado queda limpio y el siguiente envío la crea.
      reset_conversation
    end
    redirect_to root_path
  end
end
