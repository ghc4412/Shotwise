"""HTTP contract tests for durable generation batches."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.db import get_async_session
from lib.db.base import Base
from lib.db.models.task import Task
from lib.db.models.user import User
from lib.generation_queue import GenerationQueue
from server.auth import CurrentUserInfo, get_current_user
from server.routers import batches

pytestmark = pytest.mark.integration


@pytest.fixture
async def batch_api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(id="owner", username="owner"),
                User(id="other", username="other"),
            ]
        )
        await session.commit()

    queue = GenerationQueue(session_factory=factory)
    user = {"value": CurrentUserInfo(id="owner", sub="owner")}

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(batches.router, prefix="/api/v1")
    app.dependency_overrides[get_async_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: user["value"]
    app.dependency_overrides[batches.get_batch_queue] = lambda: queue
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, factory, queue, user
    await engine.dispose()


def _body() -> dict[str, Any]:
    return {
        "items": [
            {
                "item_id": "first",
                "task": {
                    "task_type": "storyboard",
                    "media_type": "image",
                    "resource_id": "first",
                    "payload": {"prompt": "prompt for first"},
                    "script_file": "episode_1.json",
                    "provider_id": "test-provider",
                },
            },
            {
                "item_id": "second",
                "task": {
                    "task_type": "storyboard",
                    "media_type": "image",
                    "resource_id": "second",
                    "payload": {"prompt": "prompt for second"},
                    "script_file": "episode_1.json",
                    "provider_id": "test-provider",
                },
            },
        ]
    }


async def test_create_get_and_scope_batch_to_current_user_and_project(batch_api) -> None:
    client, factory, _queue, user = batch_api
    response = await client.post("/api/v1/projects/demo/batches", json=_body())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "running"
    assert [task["status"] for task in body["tasks"]] == ["queued", "queued"]
    batch_id = body["batch_id"]

    assert (await client.get(f"/api/v1/projects/demo/batches/{batch_id}")).status_code == 200
    assert (await client.get(f"/api/v1/projects/other/batches/{batch_id}")).status_code == 404
    user["value"] = CurrentUserInfo(id="other", sub="other")
    assert (await client.get(f"/api/v1/projects/demo/batches/{batch_id}")).status_code == 404

    async with factory() as session:
        owners = set((await session.execute(select(Task.user_id))).scalars().all())
    assert owners == {"owner"}


async def test_create_rejects_client_supplied_user_id(batch_api) -> None:
    client, _factory, _queue, _user = batch_api
    body = _body()
    body["items"][0]["task"]["user_id"] = "other"

    response = await client.post("/api/v1/projects/demo/batches", json=body)

    assert response.status_code == 422


async def test_cancel_skips_terminal_tasks_and_reports_partial_success(batch_api) -> None:
    client, _factory, queue, _user = batch_api
    created = (await client.post("/api/v1/projects/demo/batches", json=_body())).json()
    first_task_id = created["tasks"][0]["task_id"]
    running = await queue.claim_next_task("image")
    assert running is not None
    assert running["task_id"] == first_task_id
    await queue.mark_task_succeeded(first_task_id, {"file_path": "out.png"})

    response = await client.post(f"/api/v1/projects/demo/batches/{created['batch_id']}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partially_succeeded"
    assert [task["status"] for task in body["tasks"]] == ["succeeded", "cancelled"]
    assert body["cancel_requested"] is True


async def test_retry_failed_replaces_only_failed_item(batch_api) -> None:
    client, _factory, queue, _user = batch_api
    created = (await client.post("/api/v1/projects/demo/batches", json=_body())).json()
    old_ids = [task["task_id"] for task in created["tasks"]]
    running = await queue.claim_next_task("image")
    assert running is not None
    await queue.mark_task_failed(running["task_id"], "provider failed")

    response = await client.post(f"/api/v1/projects/demo/batches/{created['batch_id']}/retry-failed")

    assert response.status_code == 200
    new_ids = [task["task_id"] for task in response.json()["tasks"]]
    assert new_ids[0] != old_ids[0]
    assert new_ids[1] == old_ids[1]
