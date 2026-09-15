from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.db import get_async_session
from server.auth import CurrentUserInfo, get_current_user
from server.routers import media_rendering
from server.services import media_assembly
from server.services import media_rendering as service

pytestmark = pytest.mark.unit


def _client(
    monkeypatch: pytest.MonkeyPatch,
    session,
    *,
    preview_background: AsyncMock | None = None,
    final_background: AsyncMock | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(media_rendering.router, prefix="/api/v1")
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="user-1", sub="test", role="admin")
    if preview_background is None:
        preview_background = AsyncMock()
    if final_background is None:
        final_background = AsyncMock()
    monkeypatch.setattr(service, "run_preview_job_background", preview_background)
    monkeypatch.setattr(service, "run_final_job_background", final_background)
    return TestClient(app)


def test_create_preview_route_queues_background_job(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    create_preview_job = AsyncMock(return_value={"id": "job-1", "status": "queued"})
    preview_background = AsyncMock()
    monkeypatch.setattr(service, "create_preview_job", create_preview_job)
    client = _client(monkeypatch, session, preview_background=preview_background)
    response = client.post("/api/v1/assembly-plans/plan-1/preview-renders", json={})
    assert response.status_code == 202
    assert response.json()["id"] == "job-1"
    session.commit.assert_awaited_once()
    create_preview_job.assert_awaited_once()
    preview_background.assert_awaited_once_with("job-1", user_id="user-1")


def test_create_preview_route_maps_conflict_and_missing_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "create_preview_job",
        AsyncMock(side_effect=service.RenderJobConflictError("preview_requires_confirmed_plan", status="draft")),
    )
    client = _client(monkeypatch, session)
    response = client.post("/api/v1/assembly-plans/plan-1/preview-renders", json={})
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "preview_requires_confirmed_plan", "status": "draft"}

    monkeypatch.setattr(
        service,
        "create_preview_job",
        AsyncMock(side_effect=media_assembly.AssemblyPlanNotFoundError("plan-1")),
    )
    response = client.post("/api/v1/assembly-plans/plan-1/preview-renders", json={})
    assert response.status_code == 404


def test_create_final_route_queues_authenticated_final_job(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    create_final_job = AsyncMock(return_value={"id": "final-job-1", "kind": "final", "status": "queued"})
    final_background = AsyncMock()
    monkeypatch.setattr(service, "create_final_job", create_final_job)
    client = _client(monkeypatch, session, final_background=final_background)

    response = client.post(
        "/api/v1/assembly-plans/plan-1/final-renders",
        json={"revision_number": 2, "max_attempts": 5},
    )

    assert response.status_code == 202
    assert response.json() == {"id": "final-job-1", "kind": "final", "status": "queued"}
    session.commit.assert_awaited_once()
    create_final_job.assert_awaited_once_with(
        session,
        "plan-1",
        user_id="user-1",
        revision_number=2,
        max_attempts=5,
    )
    final_background.assert_awaited_once_with("final-job-1", user_id="user-1")


def test_create_final_route_maps_confirmation_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    create_final_job = AsyncMock(
        side_effect=service.RenderJobConflictError("render_confirmation_required", status="preview_ready")
    )
    final_background = AsyncMock()
    monkeypatch.setattr(service, "create_final_job", create_final_job)
    client = _client(monkeypatch, session, final_background=final_background)

    response = client.post("/api/v1/assembly-plans/plan-1/final-renders", json={"revision_number": 2})

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "render_confirmation_required", "status": "preview_ready"}
    final_background.assert_not_awaited()


def test_list_final_route_scopes_service_call_to_final_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    fake_service = AsyncMock(return_value=[{"id": "final-job-1", "kind": "final"}])
    monkeypatch.setattr(service, "list_render_jobs", fake_service)
    client = _client(monkeypatch, session)

    response = client.get("/api/v1/assembly-plans/plan-1/final-renders")

    assert response.status_code == 200
    assert response.json() == {"items": [{"id": "final-job-1", "kind": "final"}]}
    fake_service.assert_awaited_once_with(session, "plan-1", user_id="user-1", kind="final")


def test_retry_final_route_requeues_final_job_and_starts_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    retry_final_job = AsyncMock(return_value={"id": "final-job-2", "kind": "final", "status": "queued"})
    final_background = AsyncMock()
    monkeypatch.setattr(service, "retry_final_job", retry_final_job)
    client = _client(monkeypatch, session, final_background=final_background)

    response = client.post("/api/v1/render-jobs/final-job-1/final-retry")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    retry_final_job.assert_awaited_once_with(session, "final-job-1", user_id="user-1")
    session.commit.assert_awaited_once()
    final_background.assert_awaited_once_with("final-job-2", user_id="user-1")


def test_retry_final_route_maps_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    retry_final_job = AsyncMock(
        side_effect=service.RenderJobConflictError("final_retry_requires_failed_job", status="succeeded")
    )
    final_background = AsyncMock()
    monkeypatch.setattr(service, "retry_final_job", retry_final_job)
    client = _client(monkeypatch, session, final_background=final_background)

    response = client.post("/api/v1/render-jobs/final-job-1/final-retry")

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "final_retry_requires_failed_job", "status": "succeeded"}
    final_background.assert_not_awaited()


def test_final_review_returns_not_ready_until_final_artifact_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "review_final_artifact",
        AsyncMock(side_effect=service.FinalRenderNotReadyError("plan-1")),
    )
    client = _client(monkeypatch, session)
    response = client.get("/api/v1/assembly-plans/plan-1/final-review")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_ready"


def test_final_review_route_returns_deterministic_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "review_final_artifact",
        AsyncMock(
            return_value={
                "status": "ready",
                "revision_number": 2,
                "checks": {
                    "duration": {"seconds": 8.0},
                    "audio_stream": {"present": True},
                    "black_frames": {"detected": False, "segments": []},
                    "frames": [
                        {"position": "first"},
                        {"position": "middle"},
                        {"position": "last"},
                    ],
                },
            }
        ),
    )
    client = _client(monkeypatch, session)
    response = client.get("/api/v1/assembly-plans/plan-1/final-review")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert [frame["position"] for frame in body["checks"]["frames"]] == ["first", "middle", "last"]


def test_final_review_confirmation_uses_authenticated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    confirm_final_review = AsyncMock(return_value={"id": "snapshot-1", "confirmed_by": "user-1"})
    monkeypatch.setattr(service, "confirm_final_review", confirm_final_review)
    client = _client(monkeypatch, session)

    response = client.post("/api/v1/render-artifacts/artifact-1/review-confirm", json={"user_id": "attacker"})

    assert response.status_code == 200
    assert response.json() == {"id": "snapshot-1", "confirmed_by": "user-1"}
    confirm_final_review.assert_awaited_once_with(session, "artifact-1", user_id="user-1")


def test_final_review_confirmation_maps_review_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "confirm_final_review",
        AsyncMock(side_effect=service.RenderReviewConflictError("review_blocked", status="blocked")),
    )
    client = _client(monkeypatch, session)

    response = client.post("/api/v1/render-artifacts/artifact-1/review-confirm")

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "review_blocked", "status": "blocked"}


def test_final_review_confirmation_maps_missing_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "confirm_final_review",
        AsyncMock(side_effect=service.RenderArtifactNotFoundError("artifact-1")),
    )
    client = _client(monkeypatch, session)

    response = client.post("/api/v1/render-artifacts/artifact-1/review-confirm")

    assert response.status_code == 404
    assert response.json()["detail"] == "render_resource_not_found"


def test_subtitle_export_returns_utf8_srt_or_vtt(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    export_subtitles = AsyncMock(
        return_value={
            "content": "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            "media_type": "application/x-subrip; charset=utf-8",
            "filename": "subtitles.srt",
        }
    )
    monkeypatch.setattr(service, "export_subtitles", export_subtitles)
    client = _client(monkeypatch, session)
    response = client.get("/api/v1/assembly-plans/plan-1/subtitles?format=srt")
    assert response.status_code == 200
    assert response.text.startswith("1\n00:00:00,000")
    assert "subtitles.srt" in response.headers["content-disposition"]
    export_subtitles.assert_awaited_once_with(session, "plan-1", format="srt", user_id="user-1")


def test_subtitle_export_rejects_invalid_revision_data(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "export_subtitles",
        AsyncMock(side_effect=service.SubtitleExportError("subtitle configuration is invalid")),
    )
    client = _client(monkeypatch, session)
    response = client.get("/api/v1/assembly-plans/plan-1/subtitles?format=vtt")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_subtitles"


def test_review_frame_route_is_user_scoped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session = AsyncMock()
    frame = tmp_path / "middle.jpg"
    frame.write_bytes(b"jpeg")
    get_final_review_frame_file = AsyncMock(return_value=({"mime_type": "image/jpeg"}, frame))
    monkeypatch.setattr(service, "get_final_review_frame_file", get_final_review_frame_file)
    client = _client(monkeypatch, session)
    response = client.get("/api/v1/render-artifacts/artifact-1/review-frames/middle")
    assert response.status_code == 200
    assert response.content == b"jpeg"
    get_final_review_frame_file.assert_awaited_once_with(session, "artifact-1", position="middle", user_id="user-1")


def test_artifact_route_returns_file_and_preserves_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session = AsyncMock()
    artifact = tmp_path / "preview.mp4"
    artifact.write_bytes(b"preview")
    get_render_artifact_file = AsyncMock(return_value=({"mime_type": "video/mp4"}, artifact))
    monkeypatch.setattr(service, "get_render_artifact_file", get_render_artifact_file)
    client = _client(monkeypatch, session)
    response = client.get("/api/v1/render-artifacts/artifact-1")
    assert response.status_code == 200
    assert response.content == b"preview"
    assert response.headers["content-type"].startswith("video/mp4")


def test_final_job_artifact_route_returns_final_mp4(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session = AsyncMock()
    artifact = tmp_path / "final-job-1.mp4"
    artifact.write_bytes(b"final")
    monkeypatch.setattr(
        service,
        "get_render_job",
        AsyncMock(return_value={"id": "final-job-1", "kind": "final", "artifact": {"id": "artifact-1"}}),
    )
    get_render_artifact_file = AsyncMock(return_value=({"mime_type": "video/mp4"}, artifact))
    monkeypatch.setattr(service, "get_render_artifact_file", get_render_artifact_file)
    client = _client(monkeypatch, session)

    response = client.get("/api/v1/render-jobs/final-job-1/artifact")

    assert response.status_code == 200
    assert response.content == b"final"
    assert response.headers["content-type"].startswith("video/mp4")
    get_render_artifact_file.assert_awaited_once_with(session, "artifact-1", user_id="user-1")
