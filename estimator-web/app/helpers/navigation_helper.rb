module NavigationHelper
  # Sección de la barra de navegación a la que pertenece la pantalla actual.
  def current_section
    case controller_path
    when "home" then :home
    when "estimations", "conversations" then action_name == "new" ? :new_estimation : :history
    when "ai_settings" then :settings
    else controller_path.start_with?("rag/") ? :rag : nil
    end
  end

  # Enlace de la barra: marca la sección activa con `aria-current` y la clase `active`.
  def nav_link(label, path, section)
    active = current_section == section
    link_to label, path, class: ("active" if active), "aria-current": ("page" if active)
  end
end
