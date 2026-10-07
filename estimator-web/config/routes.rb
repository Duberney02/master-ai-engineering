Rails.application.routes.draw do
  # Sonda de salud para Docker/Compose: 200 si la aplicación arranca.
  get "up" => "rails/health#show", as: :rails_health_check

  root "estimations#new"
  resources :estimations, only: %i[index show create]
  # «Nueva conversación»: abre otra sesión en la API y reinicia el estado.
  resource :conversation, only: :create
end
