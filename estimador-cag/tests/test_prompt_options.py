from app.context.examples import ESTIMATION_EXAMPLES, ESTIMATION_EXAMPLES_CATALOG
from app.services.prompts import EXTRACTION_SYSTEM_PROMPT, build_system_prompt


def test_default_prompt_includes_exactly_two_examples_in_markdown():
    prompt = build_system_prompt()
    assert prompt.count("### Historical Example") == 2
    assert "## Historical Reference Examples" in prompt
    for ex in ESTIMATION_EXAMPLES[:2]:
        assert ex["estimation"] in prompt
    assert ESTIMATION_EXAMPLES[2]["meeting_summary"] not in prompt


def test_num_examples_controls_how_many_are_injected():
    for n in (1, 3, 5):
        assert build_system_prompt(num_examples=n).count("### Historical Example") == n


def test_use_examples_false_removes_the_whole_examples_section():
    prompt = build_system_prompt(use_examples=False, num_examples=5)
    assert "Historical Reference Examples" not in prompt
    assert "Historical Example" not in prompt
    for ex in ESTIMATION_EXAMPLES:
        assert ex["meeting_summary"][:60] not in prompt
    assert "No historical examples are provided" in prompt


def test_zero_examples_behaves_like_disabled():
    assert build_system_prompt(num_examples=0) == build_system_prompt(use_examples=False)


def test_json_and_narrative_formats_are_injected_and_keep_markdown_output_spec():
    js = build_system_prompt(example_format="json", num_examples=2)
    assert '"desglose_de_tareas"' in js and "never JSON" in js
    assert "### Historical Example" not in js
    nar = build_system_prompt(example_format="narrative", num_examples=2)
    assert "Proyecto histórico 1:" in nar and "Proyecto histórico 2:" in nar
    for prompt in (js, nar):
        assert "| # | Área | Tarea | Horas |" in prompt  # el formato de salida no cambia


def test_inline_cleaning_block_is_only_present_when_requested():
    assert "Transcript Preparation" not in build_system_prompt()
    cleaned = build_system_prompt(inline_cleaning=True)
    assert "Transcript Preparation" in cleaned
    # Las instrucciones sobre supuestos y requisitos explícitos se conservan.
    assert "Do not invent requirements" in cleaned
    assert "assumptions" in cleaned.lower()


def test_mandatory_output_sections_are_kept_in_every_variant():
    variants = [
        build_system_prompt(),
        build_system_prompt(use_examples=False),
        build_system_prompt(inline_cleaning=True, example_format="json", num_examples=5),
    ]
    for prompt in variants:
        for heading in (
            "### Supuestos",
            "### Requisitos identificados",
            "### Desglose de tareas",
            "### Resumen",
            "### Riesgos e incertidumbres",
            "### Preguntas abiertas",
        ):
            assert heading in prompt


def test_extraction_prompt_forbids_inventing_and_estimating():
    assert "Do not invent" in EXTRACTION_SYSTEM_PROMPT
    assert "Do NOT estimate" in EXTRACTION_SYSTEM_PROMPT
    assert "Requisitos funcionales" in EXTRACTION_SYSTEM_PROMPT


def test_all_five_examples_can_be_injected():
    prompt = build_system_prompt(num_examples=5)
    for ex in ESTIMATION_EXAMPLES_CATALOG:
        assert ex.title in prompt
