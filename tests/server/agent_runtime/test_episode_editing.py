"""Contract tests for the Phase 2A episode-editing MCP adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import server.agent_runtime.sdk_tools.episode_editing as episode_editing
from lib.db.base import Base
from lib.media_assembly.plan import AssemblyPlanValidationError
from server.agent_runtime.sdk_tools import (
    SHOTWISE_INTERNAL_MCP_TOOL_IDS,
    build_shotwise_tool_list,
)
from server.agent_runtime.sdk_tools._context import ToolContext


class _PM:
    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self.project = {
            "generation_mode": "storyboard",
            "content_mode": "drama",
            "episodes": [{"episode": 1, "script_file": "episode_1.json"}],
            "current_episode": 1,
        }
        self.script = {
            "content_mode": "drama",
            "scenes": [
                {
                    "scene_id": "E1S01",
                    "duration_seconds": 6,
                    "video_prompt": "wide shot of the village gate",
                    "generated_assets": {"status": "completed", "video_clip": "videos/E1S01.mp4"},
                },
                {
                    "scene_id": "E1S02",
                    "duration_seconds": 8,
                    "video_prompt": "close-up of the hero",
                    "generated_assets": {"status": "completed", "video_clip": "videos/E1S02.mp4"},
                },
            ],
        }

    def get_project_path(self, _name: str) -> Path:
        return self.project_path

    def load_project(self, _name: str) -> dict[str, Any]:
        return self.project

    def load_script(self, _name: str, _filename: str) -> dict[str, Any]:
        return self.script


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    project_path = tmp_path / "demo"
    (project_path / "videos").mkdir(parents=True)
    (project_path / "videos" / "E1S01.mp4").write_bytes(b"video-1")
    (project_path / "videos" / "E1S02.mp4").write_bytes(b"video-2")
    return ToolContext("demo", tmp_path, pm=_PM(project_path))  # type: ignore[arg-type]


@pytest.fixture
async def episode_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(episode_editing, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def _call(tool_factory: Any, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return await tool_factory(ctx).handler(args)


@pytest.mark.unit
async def test_manifest_returns_ordered_media_contract(ctx: ToolContext, monkeypatch: pytest.MonkeyPatch) -> None:
    async def probe(_path: Path) -> dict[str, Any]:
        return {
            "exists": True,
            "readable": True,
            "probe_available": True,
            "has_video_stream": True,
            "has_audio_stream": True,
            "duration_seconds": 6.0,
            "width": 1280,
            "height": 720,
        }

    monkeypatch.setattr(episode_editing, "_probe_media", probe)
    out = await _call(episode_editing.get_episode_media_manifest_tool, ctx, {"script": "episode_1.json"})

    assert out.get("is_error") is not True
    manifest = out["structured_content"]
    assert manifest["contract_version"] == "episode-media-manifest/v1"
    assert manifest["persistence"] == "read_only"
    assert [item["unit_id"] for item in manifest["items"]] == ["E1S01", "E1S02"]
    assert manifest["items"][0]["source"]["path"] == "videos/E1S01.mp4"
    assert manifest["items"][0]["media_probe"]["has_video_stream"] is True
    assert manifest["items"][0]["file_fingerprint"]["sha256"]


@pytest.mark.unit
async def test_plan_crud_defaults_to_duck_and_validation(
    ctx: ToolContext, episode_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def probe(_path: Path) -> dict[str, Any]:
        return {
            "exists": True,
            "readable": True,
            "probe_available": True,
            "has_video_stream": True,
            "has_audio_stream": True,
            "duration_seconds": 8.0,
            "width": 1280,
            "height": 720,
        }

    monkeypatch.setattr(episode_editing, "_probe_media", probe)
    created = await _call(
        episode_editing.create_timeline_plan_tool,
        ctx,
        {
            "script": "episode_1.json",
            "director_review": {"status": "approved", "finding_count": 0},
        },
    )
    assert created.get("is_error") is not True, created
    plan = created["structured_content"]
    assert plan["status"] == "draft"
    assert plan["persistence"] == "database"
    assert plan["audio"]["unit_audio_policy"] == "duck"
    assert [item["unit_id"] for item in plan["timeline_items"]] == ["E1S01", "E1S02"]

    plan_id = plan["plan_id"]
    updated = await _call(
        episode_editing.update_timeline_plan_tool,
        ctx,
        {"plan_id": plan_id, "patch": {"audio": {"unit_audio_policy": "mute"}}},
    )
    assert updated.get("is_error") is not True, updated
    assert updated["structured_content"]["audio"]["unit_audio_policy"] == "mute"
    assert updated["structured_content"]["revision"] == 2

    other_context = ToolContext("demo", ctx.projects_root, pm=ctx.pm, user_id=ctx.user_id)
    fetched = await _call(episode_editing.get_timeline_plan_tool, other_context, {"plan_id": plan_id})
    assert fetched["structured_content"]["plan_id"] == plan_id
    assert fetched["structured_content"]["persistence"] == "database"
    denied = await _call(
        episode_editing.get_timeline_plan_tool,
        ToolContext("demo", ctx.projects_root, pm=ctx.pm, user_id="other-user"),
        {"plan_id": plan_id},
    )
    assert denied.get("is_error") is True
    validated = await _call(episode_editing.validate_timeline_plan_tool, ctx, {"plan_id": plan_id})
    assert validated.get("is_error") is not True, validated
    assert validated["structured_content"]["status"] == "validated"
    assert validated["structured_content"]["validation"]["valid"] is True


@pytest.mark.unit
async def test_validation_reports_missing_review_and_duplicate_items(ctx: ToolContext, episode_db: Any) -> None:
    created = await _call(
        episode_editing.create_timeline_plan_tool,
        ctx,
        {
            "script": "episode_1.json",
            "timeline_items": [{"unit_id": "E1S01"}, {"unit_id": "E1S01"}],
        },
    )
    assert created.get("is_error") is not True, created
    plan_id = created["structured_content"]["plan_id"]

    out = await _call(episode_editing.validate_timeline_plan_tool, ctx, {"plan_id": plan_id})
    assert out.get("is_error") is not True
    validation = out["structured_content"]["validation"]
    assert validation["valid"] is False
    codes = {issue["code"] for issue in validation["issues"]}
    assert {"director_review_required", "duplicate_unit_id", "unit_not_in_manifest"} & codes
    assert out["structured_content"]["status"] == "draft"
    assert out["structured_content"]["persistence"] == "database"


@pytest.mark.unit
def test_phase_2a_tools_are_registered_as_internal_contract_tools(tmp_path: Path) -> None:
    names = {tool.name for tool in build_shotwise_tool_list(project_name="demo", projects_root=tmp_path)}
    assert set(SHOTWISE_INTERNAL_MCP_TOOL_IDS) <= names
    assert set(SHOTWISE_INTERNAL_MCP_TOOL_IDS) == {
        "get_episode_media_manifest",
        "create_timeline_plan",
        "get_timeline_plan",
        "update_timeline_plan",
        "validate_timeline_plan",
    }


@pytest.mark.unit
def test_contract_skill_is_internal_and_does_not_require_frontend_chip() -> None:
    skill = Path("agent_runtime_profile/.claude/skills/episode-editing/SKILL.md").read_text(encoding="utf-8")
    assert "user-invocable: false" in skill
    assert "create_timeline_plan" in skill
    assert "不调用 FFmpeg" in skill


@pytest.mark.unit
async def test_create_plan_accepts_legacy_agent_timeline_shape(
    ctx: ToolContext, episode_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def probe(_path: Path) -> dict[str, Any]:
        return {
            "exists": True,
            "readable": True,
            "probe_available": True,
            "has_video_stream": True,
            "has_audio_stream": True,
            "duration_seconds": 8.0,
            "width": 1280,
            "height": 720,
        }

    monkeypatch.setattr(episode_editing, "_probe_media", probe)
    created = await _call(
        episode_editing.create_timeline_plan_tool,
        ctx,
        {
            "script": "episode_1.json",
            "director_review": {"status": "approved", "finding_count": 0},
            "timeline_items": [
                {
                    "unit_id": "E1S01",
                    "order": 1,
                    "start_seconds": 0,
                    "end_seconds": 6,
                    "duration_seconds": 6,
                    "video_clip": "videos/E1S01.mp4",
                    "audio_policy": "duck",
                    "transition": "cut",
                },
                {
                    "unit_id": "E1S02",
                    "order": 2,
                    "start_seconds": 0,
                    "end_seconds": 8,
                    "duration_seconds": 8,
                    "video_clip": "videos/E1S02.mp4",
                    "audio_policy": "duck",
                    "transition": {"type": "cut"},
                },
            ],
        },
    )

    assert created.get("is_error") is not True, created
    plan = created["structured_content"]
    assert [item["unit_id"] for item in plan["timeline_items"]] == ["E1S01", "E1S02"]
    assert [item["order"] for item in plan["timeline_items"]] == [1, 2]
    assert all(item["transition_to_next"] == "cut" for item in plan["timeline_items"])


@pytest.mark.unit
async def test_create_plan_reports_structured_domain_validation_errors(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_create_plan(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssemblyPlanValidationError(
            [{"path": "timeline[0].order", "code": "non_contiguous_order", "message": "order must start at zero"}]
        )

    monkeypatch.setattr(episode_editing.assembly_service, "create_plan", fail_create_plan)
    out = await _call(
        episode_editing.create_timeline_plan_tool,
        ctx,
        {"script": "episode_1.json", "director_review": {"status": "approved"}},
    )

    assert out["is_error"] is True
    text = out["content"][0]["text"]
    assert "timeline[0].order: non_contiguous_order - order must start at zero" in text
