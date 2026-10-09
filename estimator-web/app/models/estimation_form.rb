# Formulario de estimación: valida los campos antes de llamar a la API, carga la descripción
# desde un archivo .txt opcional (que sustituye al texto escrito) y valida los adjuntos PDF/Word
# cuyo texto la API añade a la transcripción.
class EstimationForm
  include ActiveModel::Model
  include ActiveModel::Attributes

  MIN_DESCRIPTION = 20
  MAX_DESCRIPTION = 80_000
  # 80 000 caracteres ocupan como mucho ~320 KB en UTF-8.
  MAX_UPLOAD_BYTES = 400_000

  # Adjuntos PDF/Word de la conversación: los mismos límites que aplica la API.
  MAX_ATTACHMENTS = 5
  MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
  ATTACHMENT_EXTENSIONS = %w[.pdf .docx].freeze
  ATTACHMENT_TYPE_MESSAGE = "Los adjuntos deben ser PDF (.pdf) o Word (.docx).".freeze
  ATTACHMENT_SIZE_MESSAGE = "Cada adjunto puede pesar como máximo #{MAX_ATTACHMENT_BYTES / (1024 * 1024)} MB.".freeze
  ATTACHMENT_COUNT_MESSAGE = "Se admiten como máximo #{MAX_ATTACHMENTS} adjuntos.".freeze

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

  def attachments
    @attachments ||= []
  end

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

  # Valida y guarda los adjuntos elegidos (el formulario envía un valor vacío cuando no hay ninguno).
  # Añade un error y devuelve false si alguno no es PDF/Word, pesa demasiado o hay demasiados.
  def load_attachments(files)
    @attachments = []
    chosen = Array(files).reject(&:blank?)
    return true if chosen.empty?
    return upload_error(ATTACHMENT_COUNT_MESSAGE) if chosen.size > MAX_ATTACHMENTS

    unless chosen.all? { |file| ATTACHMENT_EXTENSIONS.include?(File.extname(file.original_filename.to_s).downcase) }
      return upload_error(ATTACHMENT_TYPE_MESSAGE)
    end
    return upload_error(ATTACHMENT_SIZE_MESSAGE) if chosen.any? { |file| file.size > MAX_ATTACHMENT_BYTES }

    @attachments = chosen
    true
  end

  def api_attributes
    attributes.slice("description", "project_type", "detail_level", "output_format")
  end

  # Campos de `POST /sessions/{id}/estimate` (la transcripción va como `transcript`).
  def session_fields
    {
      "transcript" => description, "project_type" => project_type, "detail_level" => detail_level,
      "output_format" => output_format, "prompt_version" => prompt_version
    }
  end

  private

  # Con adjuntos el mensaje puede ser corto: la API valida la longitud de la transcripción más los adjuntos.
  def description_length
    min = attachments.empty? ? MIN_DESCRIPTION : 0
    errors.add(:description, DESCRIPTION_MESSAGE) unless description.length.between?(min, MAX_DESCRIPTION)
  end

  def upload_error(message)
    errors.add(:base, message)
    false
  end
end
