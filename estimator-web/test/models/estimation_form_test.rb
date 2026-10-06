require "test_helper"

class EstimationFormTest < ActiveSupport::TestCase
  def form(**overrides)
    EstimationForm.new({ description: "Portal de clientes para consultar facturas." }.merge(overrides))
  end

  def upload(content, name: "reunion.txt")
    Rack::Test::UploadedFile.new(StringIO.new(content), "text/plain", original_filename: name)
  end

  test "a valid form passes and exposes the API attributes" do
    assert form.valid?
    assert_equal %w[description detail_level output_format project_type], form.api_attributes.keys.sort
    refute form.api_attributes.key?("prompt_version")
  end

  test "description length limits are 20 and 80000" do
    [ 19, 80_001 ].each do |length|
      invalid = form(description: "x" * length)
      refute invalid.valid?, "#{length} caracteres debería ser inválido"
      assert_includes invalid.errors.map(&:message), "La descripción debe tener entre 20 y 80000 caracteres."
    end
    [ 20, 80_000 ].each { |length| assert form(description: "x" * length).valid?, "#{length} debería ser válido" }
  end

  test "the description is stripped before validating" do
    refute form(description: "   corta   ").valid?
    assert_equal "texto", form(description: "  texto  ").description
  end

  test "enums are validated" do
    %i[project_type detail_level output_format prompt_version].each do |attribute|
      refute form(attribute => "inventado").valid?, "#{attribute} debería validarse"
    end
  end

  test "a .txt upload replaces the description" do
    f = form(description: "se sustituye")
    assert f.load_upload(upload("Contenido de la transcripción de la reunión."))
    assert_equal "Contenido de la transcripción de la reunión.", f.description
    assert f.valid?
  end

  test "an upload strips the UTF-8 BOM and keeps accents" do
    f = form
    f.load_upload(upload("﻿Reunión: añadir facturación al portal de clientes"))
    assert_equal "Reunión: añadir facturación al portal de clientes", f.description
  end

  test "no upload keeps the typed description" do
    f = form
    assert f.load_upload(nil)
    assert_equal "Portal de clientes para consultar facturas.", f.description
  end

  test "non txt files are rejected" do
    f = form
    refute f.load_upload(upload("a" * 50, name: "reunion.pdf"))
    assert_includes f.errors.map(&:message), "El archivo debe ser de texto plano (.txt)."
    assert_equal "Portal de clientes para consultar facturas.", f.description
  end

  test "files that are not UTF-8 are rejected" do
    f = form
    refute f.load_upload(upload("Reunión de planificación".encode("ISO-8859-1")))
    assert_includes f.errors.map(&:message), "El archivo debe estar codificado en UTF-8."
  end

  test "files over 400 KB are rejected" do
    f = form
    refute f.load_upload(upload("a" * (EstimationForm::MAX_UPLOAD_BYTES + 1)))
    assert_includes f.errors.map(&:message), "El archivo supera el máximo de 400 KB."
  end

  test "the extension check is case insensitive" do
    assert form.load_upload(upload("a" * 50, name: "REUNION.TXT"))
  end
end
