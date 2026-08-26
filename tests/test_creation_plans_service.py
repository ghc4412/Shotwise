from __future__ import annotations

import pytest

from server.services.creation_plans import compile_project_creation_plan

pytestmark = pytest.mark.unit


def test_service_adapter_compiles_from_project_owned_modes() -> None:
    project = {
        "content_mode": "drama",
        "generation_mode": "reference_video",
        "grid_storyboard": False,
    }

    plan = compile_project_creation_plan(
        plan_id="plan-1",
        skill_id="official.reference-video",
        workflow_revision="revision-1",
        project_id="project-1",
        project=project,
        skill_inputs={"duration": 5},
        supported_generation_modes={"reference_video"},
    )

    assert plan.is_compatible
    assert plan.project_context.generation_mode == "reference_video"
    assert plan.project_context.grid_storyboard is False


def test_service_adapter_records_incompatibility_without_fallback() -> None:
    project = {
        "content_mode": "drama",
        "generation_mode": "storyboard",
        "grid_storyboard": True,
    }

    plan = compile_project_creation_plan(
        plan_id="plan-1",
        skill_id="official.reference-video",
        workflow_revision="revision-1",
        project_id="project-1",
        project=project,
        skill_inputs={},
        supported_generation_modes={"reference_video"},
    )

    assert not plan.is_compatible
    assert plan.compatibility.reasons == ("generation_mode_not_supported",)
    assert plan.project_context.generation_mode == "storyboard"
