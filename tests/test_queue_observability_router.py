"""队列可观测性只读路由的 HTTP 集成测试。

``GET /api/v1/queue/observability`` 与 ``GET /api/v1/tasks/{task_id}/queue-position``
走真实 router + 内存 SQLite；worker 经 ``app.state.generation_worker`` 注入，缺省时省掉
泳道与 ETA 容量分母。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.db import get_async_session
from lib.db.base import Base
from lib.db.models.task import Task
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import queue_observability

pytestmark = pytest.mark.integration

_BASE = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)


class _StubWorker:
    """只暴露 ``observability_snapshot()``，模拟 GenerationWorker 的读面。"""

    def __init__(self, lanes: dict[str, Any], health: dict[str, Any] | None = None) -> None:
        self._snapshot = {"lanes": lanes, "health": health or {}}

    def observability_snapshot(self) -> dict[str, Any]:
        return self._snapshot


def _task_row(
    task_id: str,
    *,
    queued_at: datetime,
    media_type: str = "image",
    status: str = "queued",
    provider_id: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> Task:
    return Task(
        task_id=task_id,
        project_name="demo",
        task_type="gen_image",
        media_type=media_type,
        resource_id=task_id,
        status=status,
        provider_id=provider_id,
        queued_at=queued_at,
        started_at=started_at,
        finished_at=finished_at,
        updated_at=queued_at,
    )


@pytest.fixture
async def queue_api() -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI, async_sessionmaker]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="test", sub="test", role="admin")
    app.dependency_overrides[get_async_session] = session_dependency
    app.include_router(queue_observability.router, prefix="/api/v1")
    register_error_handlers(app)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app, factory
    await engine.dispose()


async def _seed(factory: async_sessionmaker, *rows: Task) -> None:
    async with factory() as session:
        session.add_all(list(rows))
        await session.commit()


class TestQueueObservabilityEndpoint:
    async def test_snapshot_without_worker_omits_lanes_and_eta(self, queue_api):
        client, _app, _factory = queue_api
        resp = await client.get("/api/v1/queue/observability")

        assert resp.status_code == 200
        body = resp.json()
        assert body["lanes"] == {}
        assert body["health"] == {}
        assert body["eta"] == {}
        assert body["counts"]["total"] == 0
        assert body["alerts"] == []

    async def test_snapshot_reports_backlog_lanes_eta_and_alerts(self, queue_api):
        client, app, factory = queue_api
        await _seed(
            factory,
            _task_row("q1", queued_at=_BASE, provider_id="ark"),
            _task_row("q2", queued_at=_BASE + timedelta(seconds=1), provider_id="ark"),
            _task_row(
                "r1",
                queued_at=_BASE,
                status="running",
                provider_id="gemini",
            ),
            # 提供一条已完成样本，ETA 的均值分母才非空（服务时长 30s）。
            _task_row(
                "done",
                queued_at=_BASE,
                status="succeeded",
                provider_id="ark",
                started_at=_BASE,
                finished_at=_BASE + timedelta(seconds=30),
            ),
        )
        app.state.generation_worker = _StubWorker(
            lanes={
                "ark:image": {
                    "capacity": 4,
                    "effective_capacity": 2,
                    "occupied": 0,
                    "inflight": 0,
                    "pending": 0,
                    "utilization": 0.0,
                    "health": "closed",
                }
            },
            health={"ark": {"state": "closed"}},
        )

        resp = await client.get("/api/v1/queue/observability")
        assert resp.status_code == 200
        body = resp.json()

        assert body["counts"]["queued"] == 2
        assert body["counts"]["running"] == 1
        assert body["queued_by_provider"]["ark"] == 2
        assert body["oldest_queued_age_seconds"] is not None
        assert body["lanes"]["ark:image"]["effective_capacity"] == 2
        assert body["health"] == {"ark": {"state": "closed"}}
        assert body["eta"]["image"]["effective_capacity"] == 2
        assert body["eta"]["image"]["avg_service_seconds"] == 30.0
        assert body["eta"]["image"]["eta_seconds"] == 30.0

    async def test_snapshot_filters_by_project(self, queue_api):
        client, _app, factory = queue_api
        other = _task_row("other", queued_at=_BASE)
        other.project_name = "other-project"
        await _seed(factory, _task_row("mine", queued_at=_BASE), other)

        resp = await client.get("/api/v1/queue/observability", params={"project_name": "demo"})
        assert resp.status_code == 200
        assert resp.json()["counts"]["total"] == 1


class TestQueuePositionEndpoint:
    async def test_returns_position_for_queued_task(self, queue_api):
        client, _app, factory = queue_api
        await _seed(
            factory,
            _task_row("a", queued_at=_BASE),
            _task_row("b", queued_at=_BASE + timedelta(seconds=1)),
            _task_row("c", queued_at=_BASE + timedelta(seconds=2)),
        )

        resp = await client.get("/api/v1/tasks/b/queue-position")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == "b"
        assert body["status"] == "queued"
        assert body["position"] == 1
        assert body["lane_queued"] == 3

    async def test_position_is_null_for_running_task(self, queue_api):
        client, _app, factory = queue_api
        await _seed(factory, _task_row("r1", queued_at=_BASE, status="running"))

        resp = await client.get("/api/v1/tasks/r1/queue-position")
        assert resp.status_code == 200
        body = resp.json()
        assert body["position"] is None
        assert body["lane_queued"] == 0

    async def test_returns_404_for_missing_task(self, queue_api):
        client, _app, _factory = queue_api
        resp = await client.get("/api/v1/tasks/ghost/queue-position")
        assert resp.status_code == 404
