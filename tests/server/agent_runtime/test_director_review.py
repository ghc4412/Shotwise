"""Behavioral tests for the read-only director review MCP tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

import server.agent_runtime.sdk_tools.director_review as director_review
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.director_review import inspect_director_review_tool


class _ReviewPM:
    def __init__(self, project_path: Path, project: dict[str, Any], scripts: dict[str, dict[str, Any]]) -> None:
        self.project_path = project_path
        self.project = project
        self.scripts = scripts

    def get_project_path(self, _project_name: str) -> Path:
        return self.project_path

    def load_project(self, _project_name: str) -> dict[str, Any]:
        return self.project

    def load_script(self, _project_name: str, filename: str) -> dict[str, Any]:
        return self.scripts[filename]


async def _call(tool_obj: Any, args: dict[str, Any]) -> dict[str, Any]:
    return await tool_obj.handler(args)


def _item(unit_id: str, *, clip: str | None = "videos/clip.mp4", duration: float = 6) -> dict[str, Any]:
    assets: dict[str, Any] = {"status": "completed"}
    if clip is not None:
        assets["video_clip"] = clip
    return {
        "segment_id": unit_id,
        "duration_seconds": duration,
        "video_prompt": "camera moves forward and character looks up",
        "generated_assets": assets,
        "references": [{"type": "character", "name": "hero"}],
    }


def _context(
    tmp_path: Path,
    *,
    script: dict[str, Any],
    project: dict[str, Any] | None = None,
    scripts: dict[str, dict[str, Any]] | None = None,
) -> ToolContext:
    project_path = tmp_path / "demo"
    project_path.mkdir()
    project = project or {
        "generation_mode": "storyboard",
        "episodes": [{"episode": 1, "script_file": "episode_1.json"}],
        "current_episode": 1,
    }
    return ToolContext(
        project_name="demo",
        projects_root=tmp_path,
        pm=_ReviewPM(project_path, project, scripts or {"episode_1.json": script}),  # type: ignore[arg-type]
    )


async def _fake_probe(_path: Path) -> dict[str, Any]:
    return {
        "exists": True,
        "readable": True,
        "probe_available": True,
        "has_video_stream": True,
        "has_audio_stream": False,
        "duration_seconds": 6.0,
        "width": 1280,
        "height": 720,
    }


@pytest.mark.unit
async def test_review_returns_frames_and_audio_is_info_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = {"content_mode": "narration", "segments": [_item("E1U01")]}
    ctx = _context(tmp_path, script=script)
    monkeypatch.setattr(director_review, "_probe_media", _fake_probe)

    async def fake_frame(_path: Path, _timestamp: float, _directory: Path, _name: str) -> bytes:
        return b"jpeg"

    monkeypatch.setattr(director_review, "_extract_frame", fake_frame)
    result = await _call(inspect_director_review_tool(ctx), {"script": "episode_1.json"})

    assert result.get("is_error") is not True
    structured = result["structured_content"]
    unit = structured["episodes"][0]["units"][0]
    assert unit["review_status"] == "keep"
    assert [frame["position"] for frame in unit["frames"]] == ["start", "middle", "end"]
    assert sum(part.get("type") == "image" for part in result["content"]) == 3
    audio = [finding for finding in structured["deterministic_findings"] if finding["code"] == "audio_missing_info"]
    assert len(audio) == 1
    assert audio[0]["severity"] == "info"
    assert audio[0]["action"] == "keep"


@pytest.mark.unit
async def test_review_supports_explicit_short_samples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = {"content_mode": "narration", "segments": [_item("E1U01", duration=10)]}
    ctx = _context(tmp_path, script=script)

    async def probe(_path: Path) -> dict[str, Any]:
        result = await _fake_probe(_path)
        result["duration_seconds"] = 10.0
        return result

    monkeypatch.setattr(director_review, "_probe_media", probe)
    timestamps: list[float] = []

    async def fake_frame(_path: Path, timestamp: float, _directory: Path, _name: str) -> bytes:
        timestamps.append(timestamp)
        return b"jpeg"

    monkeypatch.setattr(director_review, "_extract_frame", fake_frame)
    result = await _call(
        inspect_director_review_tool(ctx),
        {"script": "episode_1.json", "include_short_samples": True},
    )

    assert result.get("is_error") is not True
    frames = result["structured_content"]["episodes"][0]["units"][0]["frames"]
    assert [frame["position"] for frame in frames] == ["start", "middle", "end", "sample_25", "sample_75", "sample_end"]
    assert len(timestamps) == 6


@pytest.mark.unit
async def test_review_reports_duration_mismatch_and_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = {
        "content_mode": "narration",
        "segments": [_item("E1U01", duration=6), _item("E1U02", clip="videos/missing.mp4", duration=6)],
    }
    ctx = _context(tmp_path, script=script)

    async def probe(path: Path) -> dict[str, Any]:
        if path.name == "missing.mp4":
            return {"exists": False, "readable": False, "probe_available": True}
        result = await _fake_probe(path)
        result["duration_seconds"] = 8.0
        return result

    monkeypatch.setattr(director_review, "_probe_media", probe)
    result = await _call(inspect_director_review_tool(ctx), {"script": "episode_1.json", "include_frames": False})

    assert result.get("is_error") is not True
    findings = result["structured_content"]["deterministic_findings"]
    assert "duration_mismatch" in {finding["code"] for finding in findings}
    assert any(finding["code"] == "video_missing" and finding["unit_ids"] == ["E1U02"] for finding in findings)


@pytest.mark.unit
async def test_review_detects_sequence_issues_and_requested_missing_unit(tmp_path: Path) -> None:
    script = {
        "content_mode": "narration",
        "segments": [_item("E1U02", clip=None), _item("E1U01", clip=None)],
    }
    ctx = _context(tmp_path, script=script)
    result = await _call(
        inspect_director_review_tool(ctx),
        {"script": "episode_1.json", "scope": "units", "unit_ids": ["E1U01", "E1U03"], "include_frames": False},
    )

    assert result.get("is_error") is not True
    structured = result["structured_content"]
    assert [unit["unit_id"] for unit in structured["episodes"][0]["units"]] == ["E1U01", "E1U03"]
    codes = {finding["code"] for finding in structured["deterministic_findings"]}
    assert "video_missing" in codes
    assert "missing_unit" in codes


@pytest.mark.unit
async def test_review_rejects_path_escape_without_mutating_project(tmp_path: Path) -> None:
    script = {"content_mode": "narration", "segments": [_item("E1U01", clip="../outside.mp4")]}
    ctx = _context(tmp_path, script=script)
    pm = cast(_ReviewPM, ctx.pm)
    before = repr(pm.project), repr(pm.scripts["episode_1.json"])
    result = await _call(inspect_director_review_tool(ctx), {"script": "episode_1.json", "include_frames": False})

    assert result.get("is_error") is not True
    codes = {finding["code"] for finding in result["structured_content"]["deterministic_findings"]}
    assert {"video_unreadable", "video_missing"} <= codes
    assert (repr(pm.project), repr(pm.scripts["episode_1.json"])) == before


@pytest.mark.unit
async def test_review_marks_missing_ffprobe_for_manual_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = {"content_mode": "narration", "segments": [_item("E1U01")]}
    ctx = _context(tmp_path, script=script)
    (ctx.project_path / "videos").mkdir()
    (ctx.project_path / "videos" / "clip.mp4").write_bytes(b"not-a-video")
    monkeypatch.setattr(director_review.shutil, "which", lambda _name: None)

    result = await _call(inspect_director_review_tool(ctx), {"script": "episode_1.json", "include_frames": False})

    assert result.get("is_error") is not True
    unit = result["structured_content"]["episodes"][0]["units"][0]
    assert unit["review_status"] == "manual_review"
    finding = next(item for item in unit["deterministic_findings"] if item["code"] == "probe_unavailable")
    assert finding["action"] == "manual_review"


@pytest.mark.unit
async def test_review_project_scope_reviews_all_scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = {"content_mode": "narration", "segments": [_item("E1U01", clip=None)]}
    second = {"content_mode": "narration", "segments": [_item("E2U01", clip=None)]}
    project = {
        "generation_mode": "storyboard",
        "episodes": [
            {"episode": 1, "script_file": "episode_1.json"},
            {"episode": 2, "script_file": "episode_2.json"},
        ],
    }
    ctx = _context(tmp_path, script=first, project=project, scripts={"episode_1.json": first, "episode_2.json": second})
    monkeypatch.setattr(director_review, "_probe_media", _fake_probe)

    result = await _call(inspect_director_review_tool(ctx), {"scope": "project", "include_frames": False})

    assert result.get("is_error") is not True
    structured = result["structured_content"]
    assert structured["summary"]["episode_count"] == 2
    assert [episode["script"] for episode in structured["episodes"]] == ["episode_1.json", "episode_2.json"]
