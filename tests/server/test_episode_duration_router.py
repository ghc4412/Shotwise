from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.project_manager import ProjectManager
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import episode_duration as router_mod
from tests.auth_deps import AUTH_DEPENDENCIES


def _client(monkeypatch, tmp_path: Path) -> tuple[TestClient, ProjectManager]:
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
                {"segment_id": "S1", "duration_seconds": 4, "generated_assets": {}},
                {
                    "segment_id": "S2",
                    "duration_seconds": 6,
                    "duration_locked": True,
                    "generated_assets": {},
                },
                {
                    "segment_id": "S3",
                    "duration_seconds": 8,
                    "generated_assets": {"video_clip": "videos/S3.mp4"},
                },
            ],
            "metadata": {},
        },
        "episode_1.json",
        validate=False,
    )
    monkeypatch.setattr(router_mod, "get_project_manager", lambda: manager)

    async def durations(_project_name: str, _manager: ProjectManager) -> tuple[int, ...]:
        return (4, 6, 8, 10)

    monkeypatch.setattr(router_mod, "_supported_durations", durations)
    app = FastAPI()
    register_error_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(router_mod.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    return TestClient(app), manager


@pytest.mark.unit
def test_duration_plan_save_preview_apply_and_lock(tmp_path: Path, monkeypatch) -> None:
    client, manager = _client(monkeypatch, tmp_path)
    base = "/api/v1/projects/demo/episodes/1/duration-plan"

    with client:
        initial = client.get(base)
        assert initial.status_code == 200
        revision = initial.json()["revision"]

        saved = client.put(
            base,
            json={"expected_revision": revision, "target_seconds": 24, "strategy": "equal"},
        )
        assert saved.status_code == 200
        assert saved.json()["plan"]["target_seconds"] == 24
        assert [item["duration_seconds"] for item in manager.load_script("demo", "episode_1.json")["segments"]] == [
            4,
            6,
            8,
        ]

        preview = client.post(f"{base}/preview", json={"target_seconds": 24, "strategy": "equal"})
        assert preview.status_code == 200
        assert preview.json()["changes"] == [
            {"resource_id": "S1", "from_seconds": 4, "to_seconds": 10, "clamp_reason": None}
        ]

        applied = client.post(
            f"{base}/apply",
            json={
                "expected_revision": preview.json()["revision"],
                "target_seconds": 24,
                "strategy": "equal",
            },
        )
        assert applied.status_code == 200
        assert applied.json()["applied"] == {"S1": 10}

        locked = client.patch(
            f"{base}/items/S1/lock",
            json={"locked": True, "expected_revision": applied.json()["revision"]},
        )
        assert locked.status_code == 200
        assert locked.json()["locked"] is True


@pytest.mark.unit
def test_duration_plan_reports_missing_episode_and_stale_revision(tmp_path: Path, monkeypatch) -> None:
    client, _manager = _client(monkeypatch, tmp_path)
    base = "/api/v1/projects/demo/episodes/1/duration-plan"

    with client:
        assert client.get("/api/v1/projects/demo/episodes/99/duration-plan").status_code == 404
        stale = client.put(
            base,
            json={"expected_revision": "stale", "target_seconds": 20, "strategy": "equal"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "episode_duration_revision_conflict"
