"""Route-level tests for server-owned draft promotion origins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import CurrentUserInfo, get_current_user
from server.draft_promotion import Draft, DraftPromotionService, DraftTarget, OfficialScript, canonical_fingerprint
from server.error_handlers import register_error_handlers
from server.routers import draft_promotions
from tests.auth_deps import AUTH_DEPENDENCIES


@dataclass
class _FakePromotionService:
    created: list[dict[str, Any]]

    def create(self, **kwargs: Any) -> Draft:
        self.created.append(kwargs)
        return Draft(
            id=f"draft-{len(self.created)}",
            target=kwargs["target"],
            content=kwargs["content"],
            origin=kwargs["origin"],
            actor_id=kwargs["actor_id"],
            base_content={},
            base_revision=0,
            base_fingerprint="empty",
        )


@pytest.fixture
def promotion_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _FakePromotionService]:
    service = _FakePromotionService(created=[])
    monkeypatch.setattr(draft_promotions, "_service", lambda: (object(), service))

    app = FastAPI()
    register_error_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="user-1", sub="test-user", role="admin")
    app.include_router(draft_promotions.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    return TestClient(app), service


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "expected_origin"),
    [
        ("draft-promotions", "agent"),
        ("draft-promotions/upload", "upload"),
        ("draft-promotions/online-ai", "online_ai"),
    ],
)
def test_create_routes_assign_server_owned_origin(
    promotion_client: tuple[TestClient, _FakePromotionService], path: str, expected_origin: str
) -> None:
    client, service = promotion_client

    response = client.post(
        f"/api/v1/projects/demo/{path}",
        json={
            "script_file": "scripts/episode_1.json",
            "content": {"title": "draft"},
            "origin": "forged-by-client",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["origin"] == expected_origin
    assert service.created[-1]["origin"] == expected_origin
    assert service.created[-1]["target"] == DraftTarget(project_name="demo", script_file="scripts/episode_1.json")


class _FakePromotionRepository:
    def __init__(self, draft: Draft) -> None:
        self.draft = draft

    def load_draft(self, draft_id: str, *, actor_id: str | None = None) -> Draft | None:
        if self.draft.id != draft_id or (actor_id is not None and self.draft.actor_id != actor_id):
            return None
        return self.draft

    def list_all(self, project_name: str, *, actor_id: str | None = None) -> list[Draft]:
        if self.draft.target.project_name != project_name:
            return []
        if actor_id is not None and self.draft.actor_id != actor_id:
            return []
        return [self.draft]

    def list_drafts(self, target: DraftTarget, *, actor_id: str | None = None) -> list[Draft]:
        if self.draft.target != target:
            return []
        if actor_id is not None and self.draft.actor_id != actor_id:
            return []
        return [self.draft]

    def read_official(self, target: DraftTarget) -> OfficialScript:
        content: dict[str, Any] = {}
        return OfficialScript(content=content, revision=0, fingerprint=canonical_fingerprint(content))

    def save_draft(self, draft: Draft) -> None:
        self.draft = draft

    def promote_atomically(self, *args: Any, **kwargs: Any) -> OfficialScript:
        raise AssertionError("cross-user requests must not promote a draft")


def _cross_user_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[str]]:
    draft = Draft(
        id="draft-1",
        target=DraftTarget(project_name="demo", script_file="scripts/episode_1.json"),
        content={"title": "private"},
        origin="agent",
        actor_id="user-2",
        base_content={},
        base_revision=0,
        base_fingerprint=canonical_fingerprint({}),
    )
    repository = _FakePromotionRepository(draft)
    calls: list[str] = []
    service = DraftPromotionService(repository, validator=lambda _content: calls.append("validate") or ())
    monkeypatch.setattr(draft_promotions, "_service", lambda: (repository, service))

    app = FastAPI()
    register_error_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="user-1", sub="test-user", role="admin")
    app.include_router(draft_promotions.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    return TestClient(app), calls


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "draft-promotions/draft-1", {}),
        ("patch", "draft-promotions/draft-1", {"json": {"content": {"title": "changed"}}}),
        ("post", "draft-promotions/draft-1/abandon", {}),
        ("post", "draft-promotions/draft-1/prepare", {}),
        ("post", "draft-promotions/draft-1/confirm", {"json": {"confirmation_token": "token"}}),
    ],
)
def test_single_draft_routes_hide_other_users_drafts(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    client, calls = _cross_user_client(monkeypatch)

    response = getattr(client, method)(f"/api/v1/projects/demo/{path}", **kwargs)

    assert response.status_code == 404, response.text
    assert calls == []


@pytest.mark.unit
def test_list_draft_routes_only_return_current_users_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    client, calls = _cross_user_client(monkeypatch)

    assert client.get("/api/v1/projects/demo/draft-promotions").json() == {"drafts": []}
    assert client.get(
        "/api/v1/projects/demo/draft-promotions",
        params={"script_file": "scripts/episode_1.json"},
    ).json() == {"drafts": []}
    assert calls == []
