from dataclasses import FrozenInstanceError

import pytest

from lib.creation_plan import CreationPlan, CreationPlanError, ProjectContextSnapshot

pytestmark = pytest.mark.unit


def _project(**overrides: object) -> dict[str, object]:
    return {
        "content_mode": "drama",
        "generation_mode": "storyboard",
        "grid_storyboard": False,
        **overrides,
    }


def test_snapshot_reads_generation_mode_from_project_and_is_immutable() -> None:
    snapshot = ProjectContextSnapshot.from_project("project-1", _project())

    assert snapshot.generation_mode == "storyboard"
    with pytest.raises(FrozenInstanceError):
        snapshot.generation_mode = "reference_video"  # type: ignore[misc]


def test_plan_does_not_accept_a_generation_mode_override() -> None:
    context = ProjectContextSnapshot.from_project("project-1", _project(generation_mode="reference_video"))

    plan = CreationPlan.compile(
        plan_id="plan-1",
        skill_id="official.story-to-video",
        workflow_revision="2026-08-22.1",
        project_context=context,
        skill_inputs={"style": {"name": "cinematic"}},
    )

    assert plan.project_context.generation_mode == "reference_video"
    assert "generation_mode" not in plan.to_dict()
    assert plan.to_dict()["project_context"]["generation_mode"] == "reference_video"  # type: ignore[index]


def test_incompatible_generation_mode_is_recorded_without_mutating_project_context() -> None:
    context = ProjectContextSnapshot.from_project("project-1", _project())
    plan = CreationPlan.compile(
        plan_id="plan-1",
        skill_id="official.reference-only",
        workflow_revision="2026-08-22.1",
        project_context=context,
        skill_inputs={},
        supported_generation_modes={"reference_video"},
    )

    assert not plan.is_compatible
    assert plan.compatibility.reasons == ("generation_mode_not_supported",)
    with pytest.raises(CreationPlanError, match="generation_mode_not_supported"):
        plan.require_compatible()


def test_plan_fingerprint_is_deterministic_and_nested_inputs_are_immutable() -> None:
    context = ProjectContextSnapshot.from_project("project-1", _project())
    first = CreationPlan.compile(
        plan_id="plan-1",
        skill_id="official.story-to-video",
        workflow_revision="2026-08-22.1",
        project_context=context,
        skill_inputs={"b": [1, 2], "a": {"enabled": True}},
    )
    second = CreationPlan.compile(
        plan_id="plan-1",
        skill_id="official.story-to-video",
        workflow_revision="2026-08-22.1",
        project_context=context,
        skill_inputs={"a": {"enabled": True}, "b": [1, 2]},
    )

    assert first.fingerprint == second.fingerprint
    with pytest.raises(TypeError):
        first.skill_inputs["a"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    "override",
    ["generation_mode_override", "content_mode_override", "grid_storyboard_override"],
)
def test_plan_rejects_every_project_mode_override(override: str) -> None:
    context = ProjectContextSnapshot.from_project("project-1", _project())

    with pytest.raises(CreationPlanError, match="mode overrides"):
        CreationPlan.compile(
            plan_id="plan-override",
            skill_id="official.story-to-video",
            workflow_revision="revision-1",
            project_context=context,
            skill_inputs={override: "forbidden"},
        )
