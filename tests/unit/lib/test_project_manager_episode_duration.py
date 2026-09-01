from __future__ import annotations

from pathlib import Path

import pytest

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
            "segments": [],
            "metadata": {},
        },
        "episode_1.json",
        validate=False,
    )
    return manager


@pytest.mark.unit
def test_save_episode_duration_plan_uses_script_metadata_without_mutating_shots(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)

    manager.save_episode_duration_plan(
        "demo",
        "episode_1.json",
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
    assert script["segments"] == []


@pytest.mark.unit
def test_load_episode_duration_plan_reads_legacy_project_target(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    manager.update_project("demo", lambda project: project.update({"target_duration": 60}))

    assert manager.load_episode_duration_plan("demo", "episode_1.json") == {
        "target_seconds": 60,
        "strategy": "equal",
        "manual_allocations": {},
    }
