from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.db import get_async_session
from server.auth import CurrentUserInfo, get_current_user
from server.routers import jianying_assembly
from server.services import jianying_assembly_export as service
from server.services.media_assembly import AssemblyPlanConflictError, AssemblyPlanNotFoundError

pytestmark = pytest.mark.unit


def _client(monkeypatch: pytest.MonkeyPatch, session: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(jianying_assembly.router, prefix="/api/v1")
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="user-1", sub="test", role="user")
    return TestClient(app)


def _bundle(tmp_path: Path) -> service.JianyingExportBundle:
    temp_dir = tmp_path / "bundle"
    temp_dir.mkdir()
    archive = temp_dir / "shotwise-plan-plan-1-r3.zip"
    archive.write_bytes(b"draft-zip")
    return service.JianyingExportBundle(archive, revision_number=3, temp_dir=temp_dir)


def test_export_route_returns_zip_and_passes_authenticated_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = AsyncMock()
    bundle = _bundle(tmp_path)
    export = AsyncMock(return_value=bundle)
    monkeypatch.setattr(service, "export_current_revision", export)
    client = _client(monkeypatch, session)

    response = client.get("/api/v1/assembly-plans/plan-1/jianying-draft")

    assert response.status_code == 200
    assert response.content == b"draft-zip"
    assert response.headers["content-type"].startswith("application/zip")
    assert "shotwise-plan-plan-1-r3.zip" in response.headers["content-disposition"]
    export.assert_awaited_once_with(session, "plan-1", user_id="user-1")
    assert not bundle.temp_dir.exists()


def test_export_route_maps_owner_scope_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "export_current_revision",
        AsyncMock(side_effect=AssemblyPlanNotFoundError("plan-1")),
    )
    response = _client(monkeypatch, session).get("/api/v1/assembly-plans/plan-1/jianying-draft")
    assert response.status_code == 404
    assert response.json()["detail"] == "assembly_plan_not_found"


def test_export_route_maps_revision_and_source_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(
        service,
        "export_current_revision",
        AsyncMock(side_effect=AssemblyPlanConflictError("current_revision_missing", status="draft")),
    )
    response = _client(monkeypatch, session).get("/api/v1/assembly-plans/plan-1/jianying-draft")
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "current_revision_missing", "status": "draft"}

    monkeypatch.setattr(
        service,
        "export_current_revision",
        AsyncMock(
            side_effect=service.JianyingExportError(
                "source_fingerprint_conflict",
                "media source has changed",
                status_code=409,
            )
        ),
    )
    response = _client(monkeypatch, session).get("/api/v1/assembly-plans/plan-1/jianying-draft")
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "source_fingerprint_conflict",
        "message": "media source has changed",
    }
