from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest

from lib.media_assembly.rendering import file_fingerprint
from server.services import jianying_assembly_export as service
from server.services.media_assembly import AssemblyPlanNotFoundError

pytestmark = pytest.mark.unit


def _plan(*, revision_number: int = 3, source_fingerprint: str = "source-3") -> SimpleNamespace:
    return SimpleNamespace(
        id="plan-1",
        project_name="demo",
        current_revision_number=revision_number,
        current_source_fingerprint=source_fingerprint,
        status="draft",
    )


def _revision(
    *,
    project_root: Path,
    revision_number: int = 3,
    source_fingerprint: str = "source-3",
    source_snapshot: dict[str, object] | None = None,
    timeline: list[dict[str, object]] | None = None,
    audio: dict[str, object] | None = None,
    subtitle: dict[str, object] | None = None,
    packaging: dict[str, object] | None = None,
) -> SimpleNamespace:
    del project_root
    return SimpleNamespace(
        id="revision-3",
        version_number=revision_number,
        source_fingerprint=source_fingerprint,
        source_snapshot_json=json.dumps(source_snapshot or {"items": []}),
        timeline_json=json.dumps(timeline or [{"source_ref": "clips/one.mp4", "duration_seconds": 1}]),
        audio_json=json.dumps(audio or {"tracks": []}),
        subtitle_json=json.dumps(subtitle or {"cues": []}),
        packaging_json=json.dumps(packaging or {}),
    )


def _snapshot_for(*paths: Path, project_root: Path) -> dict[str, object]:
    return {
        "items": [
            {
                "source": {"path": path.relative_to(project_root).as_posix()},
                "file_fingerprint": {"sha256": file_fingerprint(path)},
            }
            for path in paths
        ]
    }


def test_build_export_contains_editable_zip_with_only_relative_media_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    video = project_root / "clips" / "one.mp4"
    audio = project_root / "audio" / "voice.wav"
    cover = project_root / "images" / "cover.png"
    for path, content in ((video, b"video"), (audio, b"audio"), (cover, b"cover")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    revision = _revision(
        project_root=project_root,
        source_snapshot=_snapshot_for(video, audio, cover, project_root=project_root),
        audio={"tracks": [{"source_ref": "audio/voice.wav", "kind": "voice", "start_seconds": 0}]},
        subtitle={"cues": [{"start_seconds": 0, "end_seconds": 1, "text": "Hello"}]},
        packaging={"cover": {"source_ref": "images/cover.png", "duration_seconds": 2}},
    )

    bundle = service._build_export(
        cast(service.AssemblyPlan, _plan()),
        cast(service.AssemblyPlanRevision, revision),
        project_root=project_root,
    )
    try:
        with zipfile.ZipFile(bundle.path) as archive:
            names = set(archive.namelist())
            assert names == {
                "README.txt",
                "manifest.json",
                "timeline.json",
                "subtitles.srt",
                "subtitles.vtt",
                "media/001-clip.mp4",
                "media/audio-001.wav",
                "media/cover.png",
            }
            manifest = json.loads(archive.read("manifest.json"))
            timeline = json.loads(archive.read("timeline.json"))
            srt = archive.read("subtitles.srt").decode("utf-8")
            vtt = archive.read("subtitles.vtt").decode("utf-8")

        assert manifest["revision_number"] == 3
        assert manifest["subtitle"] == {"cue_count": 1, "srt": "subtitles.srt", "vtt": "subtitles.vtt"}
        assert timeline[0]["source_ref"] == "media/001-clip.mp4"
        assert timeline[0]["media_path"] == "media/001-clip.mp4"
        assert manifest["audio"]["tracks"][0]["source_ref"] == "media/audio-001.wav"
        assert manifest["packaging"]["cover"]["source_ref"] == "media/cover.png"
        assert all(not Path(name).is_absolute() for name in manifest["assets"][0].values() if isinstance(name, str))
        assert "Hello" in srt
        assert "WEBVTT" in vtt
    finally:
        bundle.cleanup()


def test_build_export_rejects_changed_source_fingerprint(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    video = project_root / "clips" / "one.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"before")
    snapshot = _snapshot_for(video, project_root=project_root)
    video.write_bytes(b"after")

    with pytest.raises(service.JianyingExportError) as exc_info:
        service._build_export(
            cast(service.AssemblyPlan, _plan()),
            cast(
                service.AssemblyPlanRevision,
                _revision(project_root=project_root, source_snapshot=snapshot),
            ),
            project_root=project_root,
        )

    assert exc_info.value.code == "source_fingerprint_conflict"
    assert exc_info.value.status_code == 409


def test_build_export_rejects_missing_media_source(tmp_path: Path) -> None:
    project_root = tmp_path / "project"

    with pytest.raises(service.JianyingExportError) as exc_info:
        service._build_export(
            cast(service.AssemblyPlan, _plan()),
            cast(service.AssemblyPlanRevision, _revision(project_root=project_root)),
            project_root=project_root,
        )

    assert exc_info.value.code == "source_file_missing"
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_export_current_revision_scopes_repository_lookup_to_authenticated_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []
    plan = _plan()
    revision = _revision(project_root=tmp_path)
    bundle = SimpleNamespace()

    class FakeRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def get_owned(self, plan_id: str, *, user_id: str) -> SimpleNamespace:
            calls.append((plan_id, user_id))
            return plan

        async def get_current_revision(self, _plan: SimpleNamespace) -> SimpleNamespace:
            return revision

    def build_export(actual_plan: object, actual_revision: object, *, project_root: Path) -> object:
        del actual_plan, actual_revision, project_root
        return bundle

    monkeypatch.setattr(service, "AssemblyPlanRepository", FakeRepository)
    monkeypatch.setattr(service, "_project_root", lambda _project_name: tmp_path)
    monkeypatch.setattr(service, "_build_export", build_export)

    result = await service.export_current_revision(AsyncMock(), "plan-1", user_id="owner-7")

    assert result is bundle
    assert calls == [("plan-1", "owner-7")]


@pytest.mark.asyncio
async def test_export_current_revision_returns_not_found_without_owner_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def get_owned(self, _plan_id: str, *, user_id: str) -> None:
            assert user_id == "other-user"
            return None

    monkeypatch.setattr(service, "AssemblyPlanRepository", FakeRepository)

    with pytest.raises(AssemblyPlanNotFoundError):
        await service.export_current_revision(AsyncMock(), "plan-1", user_id="other-user")
