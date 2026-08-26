from __future__ import annotations

from typing import Any, cast

import pytest

from lib.creative_context import (
    ContextReference,
    CreativeContextResolutionError,
    SelectedResource,
    resolve_context_references,
    resolve_creation_context,
)
from server.agent_runtime.sdk_tools import build_shotwise_tool_list
from server.agent_runtime.sdk_tools.creative_context import resolve_context_references_tool

pytestmark = pytest.mark.unit


def _project(generation_mode: str = "storyboard") -> dict[str, object]:
    return {
        "id": "project-1",
        "content_mode": "drama",
        "generation_mode": generation_mode,
        "grid_storyboard": False,
        "characters": {"char-1": {"id": "char-1", "name": "林黛玉", "gender": "female"}},
        "episodes": {"episode-1": {"id": "episode-1", "shots": {"shot-1": {"id": "shot-1", "title": "雨夜"}}}},
    }


def test_context_references_resolve_current_shot_video_and_character_to_ids():
    resolved = cast(
        dict[str, Any],
        resolve_context_references(
            project_id="project-1",
            project=_project(),
            context_references=[ContextReference("当前镜头"), ContextReference("这个视频"), ContextReference("她")],
            selected_resources=[SelectedResource("shot-1", "shot"), SelectedResource("video-1", "video")],
            board_items=[{"resource_id": "char-1", "item_type": "character", "resource_type": "image"}],
        ),
    )

    assert resolved["project_id"] == "project-1"
    assert resolved["episode_id"] == "episode-1"
    assert resolved["shot_id"] == "shot-1"
    assert {item["id"] for item in resolved["selected_resources"]} == {"shot-1", "video-1", "char-1"}
    assert resolved["disambiguated"] is True


def test_context_references_reject_ambiguous_pronoun_without_plan_or_run():
    project = _project()
    project["characters"] = {
        "char-1": {"id": "char-1", "name": "林黛玉", "gender": "female"},
        "char-2": {"id": "char-2", "name": "薛宝钗", "gender": "female"},
    }

    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_context_references(project_id="project-1", project=project, context_references=[ContextReference("她")])

    assert error.value.code == "ambiguous_context_reference"
    candidates = cast(list[dict[str, Any]], error.value.details["candidates"])
    assert {item["id"] for item in candidates} == {"char-1", "char-2"}


def test_gated_context_reuses_reference_resolution_and_still_requires_plan():
    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            context_references=[ContextReference("当前镜头")],
            selected_resources=[SelectedResource("shot-1", "shot")],
            creative_board_id="board-1",
        )

    assert error.value.code == "creation_plan_required"


def test_sdk_adapter_returns_structured_ids_without_creation_side_effects():
    result = cast(
        dict[str, Any],
        resolve_context_references_tool(
            project_id="project-1",
            project=_project(),
            references=[{"text": "当前镜头"}, {"text": "这个视频"}],
            selected_resources=[SelectedResource("shot-1", "shot"), SelectedResource("video-1", "video")],
        ),
    )

    assert result["project_id"] == "project-1"
    assert result["episode_id"] == "episode-1"
    assert result["shot_id"] == "shot-1"
    assert "video-1" in result["selected_media_asset_ids"]


def test_context_sdk_tool_is_registered_for_both_agent_adapters():
    tools = build_shotwise_tool_list(project_name="project-1", projects_root=__import__("pathlib").Path("."))
    assert any(getattr(item, "name", "") == "resolve_context_references" for item in tools)


def _plan(skill_id: str = "novel-to-drama", generation_mode: str = "storyboard", **extra: object) -> dict[str, object]:
    return {
        "id": "plan-1",
        "project_id": "project-1",
        "skill_id": skill_id,
        "status": "previewed",
        "previewed": True,
        "project_snapshot": {
            "project_id": "project-1",
            "content_mode": "drama",
            "generation_mode": generation_mode,
            "grid_storyboard": False,
        },
        "compatibility_report": {"compatible": True},
        "resource_ids": ["doc-1"],
        **extra,
    }


def test_context_resolves_explicit_ids_and_available_skills():
    context = resolve_creation_context(
        project_id="project-1",
        project=_project(),
        creative_board_id="board-1",
        episode_id="episode-1",
        shot_id="shot-1",
        selected_resources=[SelectedResource("doc-1", "document")],
        current_skill_id="novel-to-drama",
        creation_plan_id="plan-1",
        creation_plan=_plan(),
    )

    assert context["disambiguated"] is True
    assert context["selected_resources"] == [{"id": "doc-1", "resource_type": "document"}]
    assert context["selected_media_asset_ids"] == []
    available_skills = cast(list[dict[str, Any]], context["available_skills"])
    assert any(skill["id"] == "novel-to-drama" for skill in available_skills)
    assert context["requires_creation_plan_preview"] is True


def test_context_rejects_duplicate_resources_without_creating_anything():
    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            selected_resources=[SelectedResource("asset-1", "image"), SelectedResource("asset-1", "video")],
        )

    assert error.value.code == "ambiguous_duplicate_resource"


def test_context_requires_creation_plan_and_board_ids():
    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            selected_resources=[SelectedResource("doc-1", "document")],
        )
    assert error.value.code == "creative_board_id_required"

    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            creative_board_id="board-1",
            selected_resources=[SelectedResource("doc-1", "document")],
        )
    assert error.value.code == "creation_plan_required"


def test_context_rejects_incompatible_skill_and_workflow_without_plan():
    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            selected_resources=[SelectedResource("asset-1", "image")],
            current_skill_id="reference-image-video",
            workflow_run_id="run-1",
        )

    assert error.value.code == "workflow_run_requires_creation_plan"

    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            selected_resources=[SelectedResource("doc-1", "document")],
            current_skill_id="reference-image-video",
            creative_board_id="board-1",
            creation_plan_id="plan-1",
            creation_plan=_plan("reference-image-video"),
        )

    assert error.value.code == "creation_skill_incompatible"
    assert error.value.details["requires_new_project"] is True


def test_context_rejects_generation_mode_changes_after_preview():
    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project("reference_video"),
            creative_board_id="board-1",
            selected_resources=[SelectedResource("doc-1", "document")],
            current_skill_id="novel-to-drama",
            creation_plan_id="plan-1",
            creation_plan=_plan(generation_mode="storyboard"),
        )
    assert error.value.code == "generation_mode_changed"


def test_context_enforces_confirmation_quality_and_approval_gates():
    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            creative_board_id="board-1",
            selected_resources=[SelectedResource("doc-1", "document")],
            creation_plan_id="plan-1",
            creation_plan=_plan(estimated_cost=1),
        )
    assert error.value.code == "confirmation_required"

    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            creative_board_id="board-1",
            selected_resources=[SelectedResource("doc-1", "document")],
            creation_plan_id="plan-1",
            creation_plan=_plan(quality_gate={"required": True, "passed": False}),
            confirmed=True,
        )
    assert error.value.code == "quality_gate_failed"

    with pytest.raises(CreativeContextResolutionError) as error:
        resolve_creation_context(
            project_id="project-1",
            project=_project(),
            creative_board_id="board-1",
            selected_resources=[SelectedResource("doc-1", "document")],
            creation_plan_id="plan-1",
            creation_plan=_plan(review_points=["review"]),
            confirmed=True,
        )
    assert error.value.code == "approval_required"
