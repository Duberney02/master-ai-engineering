from app.context.examples import ESTIMATION_EXAMPLES


def test_has_at_least_two_examples():
    assert len(ESTIMATION_EXAMPLES) >= 2


def test_each_example_has_required_keys():
    for i, ex in enumerate(ESTIMATION_EXAMPLES):
        assert "meeting_summary" in ex, f"Example {i} missing meeting_summary"
        assert "estimation" in ex, f"Example {i} missing estimation"


def test_examples_have_substantive_content():
    for i, ex in enumerate(ESTIMATION_EXAMPLES):
        assert len(ex["meeting_summary"]) > 80, f"Example {i} meeting_summary too short"
        assert len(ex["estimation"]) > 200, f"Example {i} estimation too short"
        assert "##" in ex["estimation"], f"Example {i} estimation missing markdown headers"
        text = ex["estimation"].lower()
        assert "hora" in text or "hour" in text, f"Example {i} estimation missing hour references"
