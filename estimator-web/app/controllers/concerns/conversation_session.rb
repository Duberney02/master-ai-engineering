# Conversación con memoria: guarda en la sesión de Rails el `session_id` de la API y los metadatos del
# proyecto que ésta devuelve, para mostrarlos en la barra lateral de todas las pantallas.
#
# La API guarda las sesiones solo en memoria (se pierden al reiniciarla), así que un 404 de sesión
# se trata como «conversación caducada»: se abre otra y se avisa al usuario.
#
# La cookie de sesión de Rails admite ~4 KB: los metadatos se compactan antes de guardarlos.
module ConversationSession
  extend ActiveSupport::Concern

  EMPTY_METADATA = {
    "project_name" => nil, "assumed_team_size" => nil, "mentioned_technologies" => [], "agreed_scope" => nil
  }.freeze
  METADATA_LIMITS = { name: 80, technologies: 10, technology: 40, scope: 300 }.freeze

  private

  def conversation_metadata
    session[:project_metadata] || EMPTY_METADATA
  end

  # `session_id` vigente; si aún no hay conversación la abre en la API.
  def ensure_conversation(api)
    session[:conversation_id].presence || start_conversation(api)
  end

  # Abre otra conversación vacía en la API y descarta los metadatos de la anterior.
  def start_conversation(api)
    reset_conversation
    session[:conversation_id] = api.create_session
  end

  def reset_conversation
    session.delete(:conversation_id)
    session.delete(:project_metadata)
  end

  def remember_metadata(metadata)
    limits = METADATA_LIMITS
    session[:project_metadata] = {
      "project_name" => metadata["project_name"]&.to_s&.first(limits[:name]),
      "assumed_team_size" => metadata["assumed_team_size"],
      "mentioned_technologies" => Array(metadata["mentioned_technologies"]).first(limits[:technologies]).map { |item| item.to_s.first(limits[:technology]) },
      "agreed_scope" => metadata["agreed_scope"]&.to_s&.first(limits[:scope])
    }
  end
end
