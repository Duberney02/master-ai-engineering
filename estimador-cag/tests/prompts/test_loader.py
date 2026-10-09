import pytest
from jinja2 import StrictUndefined, UndefinedError
from pydantic import ValidationError
from structlog.testing import capture_logs

from app.prompts import loader
from app.prompts.loader import (
    UnknownPromptVersionError,
    available_versions,
    prompt_hash,
    render_estimation_prompt,
)
from app.schemas import EstimationRequest
from tests.prompts.test_estimation_v1 import DESCRIPTION, make_request


def test_versions_are_discovered_from_disk():
    assert available_versions()[:2] == ["v1", "v2"]


@pytest.mark.parametrize("version", ["v99", "../v1", "v1/../v2", "V1", "", "latest"])
def test_unknown_or_malformed_version_is_rejected(version):
    with pytest.raises(UnknownPromptVersionError):
        render_estimation_prompt(make_request(), version=version)


def test_environment_is_strict_and_trims_blocks():
    env = loader._environment("v1")

    assert env.undefined is StrictUndefined
    assert env.trim_blocks and env.lstrip_blocks
    with pytest.raises(UndefinedError):  # falta `description`: error, no texto vacío
        env.get_template("user.j2").render(project_type="web_saas", reference_projects=None)


def test_render_logs_version_and_hash_without_content():
    request = make_request()
    with capture_logs() as logs:
        first = render_estimation_prompt(request, version="v2")
        render_estimation_prompt(request, version="v2")

    events = [e for e in logs if e["event"] == "prompt_rendered"]
    assert len(events) == 2
    assert events[0]["prompt_version"] == "v2"
    assert events[0]["prompt_hash"] == events[1]["prompt_hash"] == prompt_hash(*first)
    assert len(events[0]["prompt_hash"]) == 64
    assert all(DESCRIPTION not in str(value) for value in events[0].values())


def test_hash_changes_with_version():
    request = make_request()
    assert prompt_hash(*render_estimation_prompt(request, "v1")) != prompt_hash(
        *render_estimation_prompt(request, "v2")
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"description": "demasiado corta"},
        {"description": "x" * 80_001},
        {"project_type": "desktop_app"},
        {"detail_level": "extreme"},
        {"output_format": "json"},
        {"reference_projects": [{"name": "A", "description": "B", "actual_hours": 0}]},
        {"reference_projects": [{"name": "A", "description": "B", "actual_hours": 10}] * 6},
    ],
)
def test_request_validation(overrides):
    with pytest.raises(ValidationError):
        make_request(**overrides)


def test_reference_projects_are_optional():
    request = EstimationRequest(
        description=DESCRIPTION,
        project_type="data_pipeline",
        detail_level="summary",
        output_format="narrative",
    )
    assert request.reference_projects is None
