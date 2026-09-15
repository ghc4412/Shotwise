from __future__ import annotations

from unittest.mock import ANY, AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.db import get_async_session
from server.auth import CurrentUserInfo, get_current_user
from server.routers import publishing
from server.services import publishing as service

pytestmark = pytest.mark.unit


def _client(monkeypatch: pytest.MonkeyPatch, session: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(publishing.router, prefix="/api/v1")
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(
        id="authenticated-user", sub="test", role="user"
    )
    return TestClient(app)


def test_list_route_passes_authenticated_user_and_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    listing = AsyncMock(return_value={"items": [], "total": 0, "limit": 5, "offset": 10})
    monkeypatch.setattr(service, "list_publish_jobs", listing)
    client = _client(monkeypatch, session)

    response = client.get("/api/v1/publish-jobs?limit=5&offset=10")

    assert response.status_code == 200
    assert response.json()["total"] == 0
    listing.assert_awaited_once_with(ANY, user_id="authenticated-user", limit=5, offset=10)


def test_create_route_uses_authenticated_user_and_does_not_accept_confirmation_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    fake_service = AsyncMock(return_value={"id": "publish-1", "status": "queued"})
    monkeypatch.setattr(service, "create_publish_job", fake_service)
    client = _client(monkeypatch, session)

    response = client.post(
        "/api/v1/render-artifacts/artifact-1/publish",
        json={
            "review_snapshot_id": "review-1",
            "platform": "generic",
            "idempotency_key": "request-1",
            "confirmed_by": "attacker",
            "confirmed_at": "2099-01-01T00:00:00Z",
            "status": "succeeded",
        },
    )

    assert response.status_code == 202
    assert response.json() == {"id": "publish-1", "status": "queued"}
    fake_service.assert_awaited_once_with(
        ANY,
        "artifact-1",
        review_snapshot_id="review-1",
        platform="generic",
        idempotency_key="request-1",
        destination={},
        max_attempts=3,
        user_id="authenticated-user",
    )
    session.commit.assert_awaited_once()


def test_create_route_maps_binding_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "create_publish_job",
        AsyncMock(side_effect=service.PublishConflictError("review_confirmation_required", status="ready")),
    )
    client = _client(monkeypatch, session)
    response = client.post(
        "/api/v1/render-artifacts/artifact-1/publish",
        json={"review_snapshot_id": "review-1", "platform": "generic", "idempotency_key": "request-1"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "review_confirmation_required", "status": "ready"}


def test_retry_route_maps_not_found_and_passes_authenticated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    retry = AsyncMock(return_value={"id": "publish-1", "status": "queued"})
    monkeypatch.setattr(service, "retry_publish_job", retry)
    client = _client(monkeypatch, session)
    response = client.post("/api/v1/publish-jobs/publish-1/retry")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    retry.assert_awaited_once_with(ANY, "publish-1", user_id="authenticated-user")

    monkeypatch.setattr(
        service, "retry_publish_job", AsyncMock(side_effect=service.PublishJobNotFoundError("publish-1"))
    )
    response = client.post("/api/v1/publish-jobs/publish-1/retry")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/publish-jobs/publish-1/poll",
        "/api/v1/publish-jobs/publish-1/retract",
    ],
)
def test_unconnected_adapter_is_reported_as_service_unavailable(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    session = AsyncMock()
    operation = AsyncMock(side_effect=service.PublishAdapterUnavailableError("platform_adapter_not_connected"))
    target = "poll_publish_job" if path.endswith("/poll") else "retract_publish_job"
    monkeypatch.setattr(service, target, operation)
    client = _client(monkeypatch, session)

    response = client.post(path)

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "platform_adapter_not_connected"}
    operation.assert_awaited_once_with(ANY, "publish-1", user_id="authenticated-user", adapter=None)
    session.commit.assert_not_awaited()


def test_poll_route_maps_conflict_and_passes_authenticated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    poll = AsyncMock(return_value={"id": "publish-1", "status": "processing"})
    monkeypatch.setattr(service, "poll_publish_job", poll)
    client = _client(monkeypatch, session)

    response = client.post("/api/v1/publish-jobs/publish-1/poll")

    assert response.status_code == 202
    assert response.json()["status"] == "processing"
    poll.assert_awaited_once_with(ANY, "publish-1", user_id="authenticated-user", adapter=None)
    session.commit.assert_awaited_once()

    monkeypatch.setattr(
        service,
        "poll_publish_job",
        AsyncMock(side_effect=service.PublishConflictError("poll_requires_submitted", status="published")),
    )
    response = client.post("/api/v1/publish-jobs/publish-1/poll")
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "poll_requires_submitted", "status": "published"}


def test_cancel_route_commits_emits_event_and_passes_authenticated_user(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    result = {"id": "publish-1", "project_name": "demo", "status": "canceled"}
    cancel = AsyncMock(return_value=result)
    emit_mock = Mock()
    monkeypatch.setattr(service, "cancel_publish_job", cancel)
    monkeypatch.setattr("server.routers.publishing.emit_publish_job_event", emit_mock)
    client = _client(monkeypatch, session)

    response = client.post("/api/v1/publish-jobs/publish-1/cancel")

    assert response.status_code == 202
    assert response.json() == result
    cancel.assert_awaited_once_with(ANY, "publish-1", user_id="authenticated-user")
    session.commit.assert_awaited_once()
    emit_mock.assert_called_once_with("demo", "publish-1", source="webui")


def test_cancel_route_maps_not_found_and_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    client = _client(monkeypatch, session)
    monkeypatch.setattr(
        service,
        "cancel_publish_job",
        AsyncMock(side_effect=service.PublishJobNotFoundError("publish-1")),
    )
    assert client.post("/api/v1/publish-jobs/publish-1/cancel").status_code == 404

    monkeypatch.setattr(
        service,
        "cancel_publish_job",
        AsyncMock(side_effect=service.PublishConflictError("cancel_requires_active", status="published")),
    )
    response = client.post("/api/v1/publish-jobs/publish-1/cancel")
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "cancel_requires_active", "status": "published"}
