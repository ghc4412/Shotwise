from __future__ import annotations

from pathlib import Path

import pytest

from lib.episode_duration_plan import EpisodeDurationRevisionConflict
from lib.project_manager import ProjectManager


def _make_manager(tmp_path: Path) -> ProjectManager:
    manager = ProjectManager(tmp_path / "projects")
    manager.create_project("demo", content_mode="narration")
    manager.create_project_metadata("demo", title="Demo", content_mode="narration")
    manager.save_script(
        "demo",
        {
            "episode": 1,
            "title": "Episode 1",
            "content_mode": "narration",
            "novel": {"title": "Demo", "chapter": "1"},
            "segments": [
                {
                    "segment_id": "E1S01",
                    "duration_seconds": 4,
                    "generated_assets": {},
                },
                {
                    "segment_id": "E1S02",
                    "duration_seconds": 6,
                    "duration_locked": True,
                    "generated_assets": {},
                },
                {
                    "segment_id": "E1S03",
                    "duration_seconds": 8,
                    "generated_assets": {"video_clip": "videos/E1S03.mp4"},
                },
            ],
            "metadata": {},
        },
        "episode_1.json",
        validate=False,
    )
    return manager


@pytest.mark.unit
def test_save_episode_duration_plan_uses_script_metadata_without_mutating_shots(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    before = manager.load_episode_duration_state("demo", 1)

    result = manager.save_episode_duration_plan(
        "demo",
        1,
        expected_revision=before["revision"],
        target_seconds=24,
        strategy="proportional",
        manual_allocations={"E1S01": 10},
    )

    script = manager.load_script("demo", "episode_1.json")
    assert script["metadata"]["episode_duration_plan"] == {
        "target_seconds": 24,
        "strategy": "proportional",
        "manual_allocations": {"E1S01": 10},
    }
    assert [item["duration_seconds"] for item in script["segments"]] == [4, 6, 8]
    assert result["revision"] != before["revision"]


@pytest.mark.unit
def test_load_episode_duration_plan_reads_legacy_project_target(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    manager.update_project("demo", lambda project: project.update({"target_duration": 60}))

    assert manager.load_episode_duration_plan("demo", "episode_1.json") == {
        "target_seconds": 60,
        "strategy": "equal",
        "manual_allocations": {},
    }


@pytest.mark.unit
def test_preview_is_read_only_and_apply_updates_only_adjustable_items(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    before = manager.load_episode_duration_state("demo", 1)

    preview = manager.preview_episode_duration_plan(
        "demo",
        1,
        target_seconds=24,
        supported_durations=(4, 6, 8, 10),
    )

    assert preview["revision"] == before["revision"]
    assert preview["changes"] == [
        {
            "resource_id": "E1S01",
            "from_seconds": 4,
            "to_seconds": 10,
            "clamp_reason": None,
        }
    ]
    assert manager.load_episode_duration_state("demo", 1) == before

    applied = manager.apply_episode_duration_plan(
        "demo",
        1,
        expected_revision=preview["revision"],
        target_seconds=24,
        supported_durations=(4, 6, 8, 10),
    )

    assert applied["applied"] == {"E1S01": 10}
    script = manager.load_script("demo", "episode_1.json")
    assert [item["duration_seconds"] for item in script["segments"]] == [10, 6, 8]


@pytest.mark.unit
def test_lock_toggle_is_duration_only_and_rejects_stale_revision(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    revision = manager.load_episode_duration_state("demo", 1)["revision"]

    locked = manager.set_episode_duration_lock("demo", 1, "E1S01", locked=True, expected_revision=revision)
    assert locked["locked"] is True
    item = manager.load_script("demo", "episode_1.json")["segments"][0]
    assert item["duration_locked"] is True
    assert "locked" not in item

    with pytest.raises(EpisodeDurationRevisionConflict):
        manager.set_episode_duration_lock("demo", 1, "E1S01", locked=False, expected_revision=revision)
