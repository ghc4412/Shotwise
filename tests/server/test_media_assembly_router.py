from __future__ import annotations

from unittest.mock import ANY, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.db import get_async_session
from server.auth import CurrentUserInfo, get_current_user
from server.routers import media_assembly
from tests.auth_deps import AUTH_DEPENDENCIES

pytestmark = pytest.mark.unit


def _client(session: AsyncMock | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(media_assembly.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="user-1", sub="test", role="admin")
    app.dependency_overrides[get_async_session] = lambda: session if session is not None else AsyncMock()
    return TestClient(app)


def _valid_body() -> dict:
    from tests.lib.test_media_assembly_plan import _document

    return {"name": "Episode assembly", "episode_number": 1, **_document()}


def test_create_route_returns_plan_and_passes_authenticated_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_service = AsyncMock(return_value={"id": "plan-1", "status": "draft"})
    monkeypatch.setattr(media_assembly.service, "create_plan", fake_service)
    client = _client()
    response = client.post("/api/v1/projects/demo/assembly-plans", json=_valid_body())
    assert response.status_code == 201
    assert response.json() == {"id": "plan-1", "status": "draft"}
    assert fake_service.await_args is not None
    assert fake_service.await_args.kwargs["user_id"] == "user-1"
    assert fake_service.await_args.kwargs["project_name"] == "demo"


def test_create_route_maps_domain_validation_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    validation_error = media_assembly.AssemblyPlanValidationError(
        [{"path": "timeline", "code": "not_empty", "message": "timeline must contain at least one item"}]
    )
    fake_service = AsyncMock(side_effect=validation_error)
    monkeypatch.setattr(media_assembly.service, "create_plan", fake_service)
    client = _client()
    body = _valid_body()
    body["timeline"] = []
    response = client.post("/api/v1/projects/demo/assembly-plans", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_assembly_plan"
    fake_service.assert_awaited_once()


def test_status_route_maps_domain_conflict_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        media_assembly.service,
        "transition_plan",
        AsyncMock(side_effect=media_assembly.service.AssemblyPlanConflictError("preview_required", status="confirmed")),
    )
    client = _client()
    response = client.post("/api/v1/assembly-plans/plan-1/status", json={"status": "render_pending"})
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "preview_required", "status": "confirmed"}


def test_status_route_cannot_set_preview_ready_without_preview_task(monkeypatch: pytest.MonkeyPatch) -> None:
    transition_plan = AsyncMock(
        side_effect=media_assembly.service.AssemblyPlanConflictError(
            "preview_task_required",
            status="preview_pending",
        )
    )
    monkeypatch.setattr(media_assembly.service, "transition_plan", transition_plan)
    client = _client()
    response = client.post("/api/v1/assembly-plans/plan-1/status", json={"status": "preview_ready"})
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "preview_task_required", "status": "preview_pending"}
    transition_plan.assert_awaited_once_with(
        ANY,
        "plan-1",
        user_id="user-1",
        target_status="preview_ready",
    )


def test_preview_confirm_route_uses_authenticated_user_not_body_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_service = AsyncMock(
        return_value={
            "id": "plan-1",
            "status": "preview_ready",
            "preview_confirmed_by": "user-1",
            "preview_confirmed_at": "2026-09-13T12:00:00+00:00",
        }
    )
    monkeypatch.setattr(media_assembly.service, "confirm_preview", fake_service)
    client = _client()

    response = client.post(
        "/api/v1/assembly-plans/plan-1/preview-confirm",
        json={"revision_number": 2, "confirmed_by": "attacker"},
    )

    assert response.status_code == 200
    assert response.json()["preview_confirmed_by"] == "user-1"
    fake_service.assert_awaited_once_with(ANY, "plan-1", user_id="user-1", revision_number=2)


def test_preview_confirm_route_maps_revision_conflict_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        media_assembly.service,
        "confirm_preview",
        AsyncMock(
            side_effect=media_assembly.service.AssemblyPlanConflictError("revision_conflict", status="preview_ready")
        ),
    )
    client = _client()

    response = client.post("/api/v1/assembly-plans/plan-1/preview-confirm", json={"revision_number": 1})

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "revision_conflict", "status": "preview_ready"}


def test_render_confirm_route_uses_authenticated_user_not_body_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_service = AsyncMock(
        return_value={
            "id": "plan-1",
            "status": "render_pending",
            "render_confirmed_by": "user-1",
            "render_confirmed_at": "2026-09-13T12:00:00+00:00",
        }
    )
    monkeypatch.setattr(media_assembly.service, "confirm_render", fake_service)
    client = _client()

    response = client.post(
        "/api/v1/assembly-plans/plan-1/render-confirm",
        json={"revision_number": 2, "confirmed_by": "attacker"},
    )

    assert response.status_code == 200
    assert response.json()["render_confirmed_by"] == "user-1"
    fake_service.assert_awaited_once_with(ANY, "plan-1", user_id="user-1", revision_number=2)


def test_render_confirm_route_maps_confirmation_conflict_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        media_assembly.service,
        "confirm_render",
        AsyncMock(
            side_effect=media_assembly.service.AssemblyPlanConflictError(
                "preview_confirmation_required", status="preview_ready"
            )
        ),
    )
    client = _client()

    response = client.post("/api/v1/assembly-plans/plan-1/render-confirm", json={"revision_number": 1})

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "preview_confirmation_required", "status": "preview_ready"}


@pytest.mark.parametrize(
    ("method", "path", "body", "service_name", "expected_status"),
    [
        (
            "post",
            "/api/v1/projects/demo/assembly-plans",
            {"name": "Episode assembly", "source_snapshot": {}, "timeline": [{"kind": "shot"}]},
            "create_plan",
            201,
        ),
        (
            "post",
            "/api/v1/assembly-plans/plan-1/revisions",
            {"source_snapshot": {}, "timeline": [{"kind": "shot"}]},
            "create_revision",
            200,
        ),
        ("post", "/api/v1/assembly-plans/plan-1/status", {"status": "confirmed"}, "transition_plan", 200),
        (
            "post",
            "/api/v1/assembly-plans/plan-1/preview-confirm",
            {"revision_number": 1},
            "confirm_preview",
            200,
        ),
        (
            "post",
            "/api/v1/assembly-plans/plan-1/render-confirm",
            {"revision_number": 1},
            "confirm_render",
            200,
        ),
        ("post", "/api/v1/assembly-plans/plan-1/stale-check", {"source_snapshot": {}}, "check_stale", 200),
    ],
)
def test_write_routes_commit_the_session(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict,
    service_name: str,
    expected_status: int,
) -> None:
    monkeypatch.setattr(media_assembly.service, service_name, AsyncMock(return_value={"id": "plan-1"}))
    session = AsyncMock()
    client = _client(session)

    response = getattr(client, method)(path, json=body)

    assert response.status_code == expected_status
    session.commit.assert_awaited_once()
