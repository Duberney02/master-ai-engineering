from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import build_system_prompt


def test_prompt_contains_role():
    prompt = build_system_prompt()
    assert "Senior Software Estimation Architect" in prompt


def test_prompt_contains_all_example_summaries():
    prompt = build_system_prompt()
    for ex in ESTIMATION_EXAMPLES:
        assert ex["meeting_summary"][:60] in prompt


def test_prompt_contains_all_example_estimations():
    prompt = build_system_prompt()
    for ex in ESTIMATION_EXAMPLES:
        assert ex["estimation"][:60] in prompt


def test_prompt_contains_output_format_markers():
    # The output template uses Spanish headers (output language is Spanish)
    prompt = build_system_prompt()
    assert "Estimación:" in prompt
    assert "Supuestos" in prompt
    assert "Riesgos" in prompt
    assert "Preguntas abiertas" in prompt


def test_prompt_instructs_assumptions_over_invention():
    # Instructions are in English
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "assumption" in lower


def test_prompt_is_substantial():
    prompt = build_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 800
