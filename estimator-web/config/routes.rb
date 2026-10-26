Rails.application.routes.draw do
  # Sonda de salud para Docker/Compose: 200 si la aplicación arranca.
  get "up" => "rails/health#show", as: :rails_health_check

  # Inicio: un panel con una tarjeta por contexto (estimaciones, Chunking Lab, Ajustes).
  root "home#index"

  # Contexto «estimaciones»: el formulario vive en /estimations/new (antes era la raíz).
  get "estimations/new", to: "estimations#new", as: :new_estimation
  resources :estimations, only: %i[index show create]
  # «Nueva conversación»: abre otra sesión en la API y reinicia el estado.
  resource :conversation, only: :create

  # Contexto «RAG» (Sesión 7): comparación de estrategias de chunking con historial persistido.
  namespace :rag do
    resources :chunking_comparisons, only: %i[index new create show]
  end

  # Ajustes del servicio IA: modelos del LLM en tiempo de ejecución.
  resource :ai_settings, only: %i[show update]
end
