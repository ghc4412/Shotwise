"""HTTP integration coverage for Agent memory ownership and import boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.db.base import Base
from lib.db.models.user import User
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import memories

pytestmark = pytest.mark.integration


class _ProjectManager:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_project_path(self, name: str) -> Path:
        if name == "missing":
            raise FileNotFoundError(name)
        if name in {"../escape", "bad/name", "bad name", ""}:
            raise ValueError(name)
        return self.root / name


@pytest.fixture
async def memory_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(id="user-a", username="user-a-memory-router"),
                User(id="user-b", username="user-b-memory-router"),
            ]
        )
        await session.commit()

    monkeypatch.setattr(memories, "async_session_factory", factory)
    monkeypatch.setattr(memories, "get_project_manager", lambda: _ProjectManager(tmp_path))
    current_user = {"value": CurrentUserInfo(id="user-a", sub="user-a")}

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(memories.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: current_user["value"]
    register_error_handlers(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, current_user
    await engine.dispose()


async def test_memories_are_isolated_across_users_and_projects(memory_api) -> None:
    client, current_user = memory_api
    created = await client.post(
        "/api/v1/projects/demo/memories",
        json={"category": "style", "content": "Use a restrained palette."},
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    assert (await client.get("/api/v1/projects/demo/memories")).json()["items"][0]["id"] == memory_id
    assert (await client.get("/api/v1/projects/other/memories")).json()["items"] == []

    current_user["value"] = CurrentUserInfo(id="user-b", sub="user-b")
    assert (await client.get("/api/v1/projects/demo/memories")).json()["items"] == []
    assert (await client.patch(f"/api/v1/memories/{memory_id}", json={"content": "leak"})).status_code == 404
    assert (await client.delete(f"/api/v1/memories/{memory_id}")).status_code == 404


@pytest.mark.parametrize(
    ("project_name", "status"),
    [("missing", 404), ("bad%20name", 400)],
)
async def test_project_routes_validate_project_name_and_existence(memory_api, project_name: str, status: int) -> None:
    client, _current_user = memory_api
    response = await client.get(f"/api/v1/projects/{project_name}/memories")
    assert response.status_code == status


async def test_explicit_import_maps_project_entries_to_target_and_ignores_source(memory_api) -> None:
    client, _current_user = memory_api
    response = await client.post(
        "/api/v1/memories/import?project_name=target",
        json={
            "user_memories": [{"category": "preference", "content": "Prefer concise prompts."}],
            "project_memories": [{"project_name": "source", "category": "world", "content": "The story is coastal."}],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"imported": 2, "skipped": 0}
    assert (await client.get("/api/v1/memories/user")).json()["items"][0]["content"] == "Prefer concise prompts."
    target = (await client.get("/api/v1/projects/target/memories")).json()["items"]
    assert [(item["project_name"], item["content"]) for item in target] == [("target", "The story is coastal.")]
    assert (await client.get("/api/v1/projects/source/memories")).json()["items"] == []


async def test_project_archive_import_ignores_user_entries_and_source_project(memory_api) -> None:
    client, _current_user = memory_api
    response = await client.post(
        "/api/v1/projects/target/memories/import",
        json={
            "user_memories": [{"category": "preference", "content": "Must not be imported."}],
            "project_memories": [
                {"project_name": "source", "category": "world", "content": "Target-only archive fact."}
            ],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"imported": 1, "skipped": 0}
    assert (await client.get("/api/v1/memories/user")).json()["items"] == []
    target = (await client.get("/api/v1/projects/target/memories")).json()["items"]
    assert target[0]["project_name"] == "target"
    assert (await client.get("/api/v1/projects/source/memories")).json()["items"] == []


async def test_candidates_can_only_be_accepted_by_the_owner(memory_api) -> None:
    client, current_user = memory_api
    created = await client.post(
        "/api/v1/memory-candidates",
        json={"scope": "project", "project_name": "demo", "category": "style", "content": "Use warm light."},
    )
    assert created.status_code == 201
    candidate_id = created.json()["id"]

    current_user["value"] = CurrentUserInfo(id="user-b", sub="user-b")
    assert (await client.post(f"/api/v1/memory-candidates/{candidate_id}/accept")).status_code == 404
    assert (await client.get("/api/v1/memory-candidates")).json()["items"] == []

    current_user["value"] = CurrentUserInfo(id="user-a", sub="user-a")
    accepted = await client.post(f"/api/v1/memory-candidates/{candidate_id}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert len((await client.get("/api/v1/projects/demo/memories")).json()["items"]) == 1
