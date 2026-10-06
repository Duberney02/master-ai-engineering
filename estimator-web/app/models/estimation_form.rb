# Formulario de estimación: valida los campos antes de llamar a la API y carga la descripción
# desde un archivo .txt opcional (que sustituye al texto escrito).
class EstimationForm
  include ActiveModel::Model
  include ActiveModel::Attributes

  MIN_DESCRIPTION = 20
  MAX_DESCRIPTION = 80_000
  # 80 000 caracteres ocupan como mucho ~320 KB en UTF-8.
  MAX_UPLOAD_BYTES = 400_000

  PROJECT_TYPES = %w[mobile_app web_saas internal_tool data_pipeline].freeze
  DETAIL_LEVELS = %w[summary medium detailed].freeze
  OUTPUT_FORMATS = %w[phases_table line_items narrative].freeze
  PROMPT_VERSIONS = %w[v3 v1 v2].freeze

  DESCRIPTION_MESSAGE = "La descripción debe tener entre #{MIN_DESCRIPTION} y #{MAX_DESCRIPTION} caracteres.".freeze

  attribute :description, :string, default: ""
  attribute :project_type, :string, default: PROJECT_TYPES.first
  attribute :detail_level, :string, default: "medium"
  attribute :output_format, :string, default: OUTPUT_FORMATS.first
  attribute :prompt_version, :string, default: PROMPT_VERSIONS.first

  validates :project_type, inclusion: { in: PROJECT_TYPES, message: "El tipo de proyecto no es válido." }
  validates :detail_level, inclusion: { in: DETAIL_LEVELS, message: "El nivel de detalle no es válido." }
  validates :output_format, inclusion: { in: OUTPUT_FORMATS, message: "El formato de salida no es válido." }
  validates :prompt_version, inclusion: { in: PROMPT_VERSIONS, message: "La versión del prompt no es válida." }
  validate :description_length

  def description=(value)
    super(value.to_s.strip)
  end

  # Sustituye la descripción por el contenido del archivo; añade un error y devuelve false si
  # el archivo no es un .txt UTF-8 de tamaño admitido.
  def load_upload(file)
    return true if file.blank?

    unless File.extname(file.original_filename.to_s).casecmp?(".txt")
      return upload_error("El archivo debe ser de texto plano (.txt).")
    end
    if file.size > MAX_UPLOAD_BYTES
      return upload_error("El archivo supera el máximo de #{MAX_UPLOAD_BYTES / 1000} KB.")
    end

    text = file.read.to_s.dup.force_encoding(Encoding::UTF_8)
    return upload_error("El archivo debe estar codificado en UTF-8.") unless text.valid_encoding?

    self.description = text.delete_prefix("﻿")
    true
  end

  def api_attributes
    attributes.slice("description", "project_type", "detail_level", "output_format")
  end

  private

  def description_length
    errors.add(:description, DESCRIPTION_MESSAGE) unless description.length.between?(MIN_DESCRIPTION, MAX_DESCRIPTION)
  end

  def upload_error(message)
    errors.add(:base, message)
    false
  end
end
