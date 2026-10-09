require "test_helper"

class EstimationFormAttachmentsTest < ActiveSupport::TestCase
  def form(**overrides)
    EstimationForm.new({ description: "Portal de clientes para consultar facturas." }.merge(overrides))
  end

  def file(name, size: 10)
    Rack::Test::UploadedFile.new(StringIO.new("x" * size), "application/octet-stream", original_filename: name)
  end

  test "valid PDF and Word attachments are kept in order" do
    subject = form
    files = [ file("requisitos.pdf"), file("ALCANCE.DOCX") ]

    assert subject.load_attachments(files)
    assert_equal files, subject.attachments
    assert subject.errors.empty?
  end

  test "empty values from browsers without a chosen file are ignored" do
    subject = form

    assert subject.load_attachments([ "" ])
    assert subject.load_attachments(nil)
    assert_empty subject.attachments
  end

  test "other file types are rejected" do
    subject = form

    refute subject.load_attachments([ file("notas.txt") ])
    assert_equal [ EstimationForm::ATTACHMENT_TYPE_MESSAGE ], subject.errors.map(&:message)
    assert_empty subject.attachments
  end

  test "attachments over 10 MB are rejected" do
    subject = form

    refute subject.load_attachments([ file("grande.pdf", size: EstimationForm::MAX_ATTACHMENT_BYTES + 1) ])
    assert_equal [ EstimationForm::ATTACHMENT_SIZE_MESSAGE ], subject.errors.map(&:message)
  end

  test "more than five attachments are rejected" do
    subject = form

    refute subject.load_attachments(Array.new(6) { |n| file("#{n}.pdf") })
    assert_equal [ EstimationForm::ATTACHMENT_COUNT_MESSAGE ], subject.errors.map(&:message)
  end

  test "a short message is valid with attachments but not without them" do
    short = form(description: "Revisa")
    refute short.valid?

    with_files = form(description: "Revisa")
    with_files.load_attachments([ file("req.pdf") ])
    assert with_files.valid?

    too_long = form(description: "x" * 80_001)
    too_long.load_attachments([ file("req.pdf") ])
    refute too_long.valid?
  end

  test "session_fields carries the transcript and the options" do
    assert_equal(
      { "transcript" => "Portal de clientes para consultar facturas.", "project_type" => "mobile_app",
        "detail_level" => "medium", "output_format" => "phases_table", "prompt_version" => "v3" },
      form.session_fields
    )
  end
end
