from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import generate
from tests.auth_deps import AUTH_DEPENDENCIES


class _FakeQueue:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_task(self, **kwargs):
        self.calls.append(kwargs)
        return {"task_id": "task-1", "deduped": False}


class _FakePM:
    def __init__(self, project_path: Path, project: dict, script: dict) -> None:
        self.project_path = project_path
        self.project = project
        self.script = script

    def load_project(self, project_name: str) -> dict:
        return self.project

    def get_project_path(self, project_name: str) -> Path:
        return self.project_path

    def load_script(self, project_name: str, filename: str) -> dict:
        return self.script


class _FakeResolver:
    def __init__(self, session_factory) -> None:
        pass

    async def video_capabilities_for_project(self, project: dict, *, capability: str) -> dict:
        return {"supported_durations": [4, 6, 8]}


def _client(monkeypatch: pytest.MonkeyPatch, pm: _FakePM, queue: _FakeQueue) -> TestClient:
    monkeypatch.setattr(generate, "get_project_manager", lambda: pm)
    monkeypatch.setattr(generate, "get_generation_queue", lambda: queue)
    monkeypatch.setattr(generate, "ConfigResolver", _FakeResolver)
    monkeypatch.setattr(generate, "require_video_bucket_capability", _allow)
    monkeypatch.setattr(generate, "require_audio_switch_supported", _allow)
    app = FastAPI()
    register_error_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="default", sub="testuser", role="admin")
    app.include_router(generate.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    return TestClient(app)


async def _allow(project: dict, capability: str) -> None:
    return None


def _script(*, locked: bool = False, generated: bool = False) -> dict:
    assets = {"video_clip": "videos/existing.mp4"} if generated else {}
    return {
        "content_mode": "narration",
        "segments": [
            {
                "segment_id": "E1S01",
                "duration_seconds": 4,
                "novel_text": "one",
                "characters_in_segment": [],
                "scenes": [],
                "props": [],
                "image_prompt": "image",
                "video_prompt": "video",
                "duration_locked": locked,
                "generated_assets": assets,
            },
            {
                "segment_id": "E1S02",
                "duration_seconds": 4,
                "novel_text": "two",
                "characters_in_segment": [],
                "scenes": [],
                "props": [],
                "image_prompt": "image",
                "video_prompt": "video",
                "generated_assets": {},
            },
        ],
        "metadata": {
            "episode_duration_plan": {
                "target_seconds": 12,
                "strategy": "equal",
                "manual_allocations": {},
            }
        },
    }


@pytest.mark.unit
def test_generate_video_puts_planned_request_in_payload_without_mutating_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_path = tmp_path / "demo"
    storyboard = project_path / "storyboards" / "scene_E1S01.png"
    storyboard.parent.mkdir(parents=True)
    storyboard.write_bytes(b"png")
    project = {"generation_mode": "storyboard", "content_mode": "narration"}
    script = _script()
    queue = _FakeQueue()
    client = _client(monkeypatch, _FakePM(project_path, project, script), queue)

    response = client.post(
        "/api/v1/projects/demo/generate/video/E1S01",
        json={"prompt": "move", "script_file": "episode_1.json"},
    )

    assert response.status_code == 200, response.text
    payload = queue.calls[0]["payload"]
    assert payload["requested_seconds"] == 6
    assert payload["duration_seconds"] == 6
    assert script["segments"][0]["duration_seconds"] == 4


@pytest.mark.unit
@pytest.mark.parametrize("locked, generated", [(True, False), (False, True)])
def test_generate_video_does_not_apply_plan_to_locked_or_generated_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locked: bool, generated: bool
) -> None:
    project_path = tmp_path / "demo"
    storyboard = project_path / "storyboards" / "scene_E1S01.png"
    storyboard.parent.mkdir(parents=True)
    storyboard.write_bytes(b"png")
    queue = _FakeQueue()
    client = _client(
        monkeypatch,
        _FakePM(
            project_path,
            {"generation_mode": "storyboard", "content_mode": "narration"},
            _script(locked=locked, generated=generated),
        ),
        queue,
    )

    response = client.post(
        "/api/v1/projects/demo/generate/video/E1S01",
        json={"prompt": "move", "script_file": "episode_1.json"},
    )

    assert response.status_code == 200, response.text
    assert "requested_seconds" not in queue.calls[0]["payload"]
