"""队列可观测性读层：纯函数 + 真实 SQLite 协作。

纯函数（分位数 / ETA / 告警派生）用 unit 打标；拼快照与两条读查询走 ``async_session``
真实建表断言，用 integration 打标。
"""

from datetime import UTC, datetime, timedelta

import pytest

from lib.db.models.api_call import ApiCall
from lib.db.models.task import Task
from lib.queue_observability import (
    build_alerts,
    build_snapshot,
    estimate_eta_seconds,
    percentile,
    provider_latencies,
    summarize_durations,
    task_queue_position,
)


def _task(
    task_id: str,
    *,
    queued_at: datetime,
    media_type: str = "image",
    status: str = "queued",
    project_name: str = "demo",
    provider_id: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> Task:
    return Task(
        task_id=task_id,
        project_name=project_name,
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


def _call(
    provider: str,
    call_type: str,
    duration_ms: int | None,
    finished_at: datetime,
    *,
    status: str = "success",
) -> ApiCall:
    return ApiCall(
        project_name="demo",
        call_type=call_type,
        model="demo-model",
        status=status,
        provider=provider,
        started_at=finished_at - timedelta(seconds=5),
        finished_at=finished_at,
        duration_ms=duration_ms,
    )


class _StubWorker:
    """只提供 observability_snapshot 的最小替身（读层只依赖这一个方法）。"""

    def __init__(self, lanes: dict, health: dict | None = None) -> None:
        self._snapshot = {"lanes": lanes, "health": health or {}}

    def observability_snapshot(self) -> dict:
        return self._snapshot


class TestPercentiles:
    @pytest.mark.unit
    def test_nearest_rank(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert percentile(values, 0.5) == 3.0
        assert percentile(values, 0.95) == 5.0
        assert percentile(values, 0.0) == 1.0, "quantile 0 也必须落在样本内（最近秩下限 1）"
        assert percentile([7.0], 0.5) == 7.0

    @pytest.mark.unit
    def test_empty_raises(self):
        with pytest.raises(ValueError):
            percentile([], 0.5)

    @pytest.mark.unit
    def test_summarize_durations(self):
        assert summarize_durations([]) == {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0, "avg_ms": 0.0}
        summary = summarize_durations([100, 200, 300])
        assert summary == {"samples": 3, "p50_ms": 200.0, "p95_ms": 300.0, "avg_ms": 200.0}


class TestEstimateEta:
    @pytest.mark.unit
    def test_returns_none_when_unknown(self):
        assert estimate_eta_seconds(queued=0, avg_service_seconds=10.0, effective_capacity=2) is None
        assert estimate_eta_seconds(queued=5, avg_service_seconds=None, effective_capacity=2) is None
        assert estimate_eta_seconds(queued=5, avg_service_seconds=0.0, effective_capacity=2) is None
        assert estimate_eta_seconds(queued=5, avg_service_seconds=10.0, effective_capacity=0) is None

    @pytest.mark.unit
    def test_scales_with_queue_and_capacity(self):
        assert estimate_eta_seconds(queued=8, avg_service_seconds=30.0, effective_capacity=4) == 60.0


class TestBuildAlerts:
    @pytest.mark.unit
    def test_backlog_and_stalled(self):
        alerts = build_alerts(
            counts={"queued": 60, "running": 0},
            lanes={},
            backlog_threshold=50,
            pending_threshold=10,
        )
        assert {alert["code"] for alert in alerts} == {"queue_backlog", "queue_stalled"}

    @pytest.mark.unit
    def test_quiet_when_healthy(self):
        lanes = {
            "ark:image": {
                "health": "closed",
                "effective_capacity": 4,
                "occupied": 1,
                "pending": 0,
            }
        }
        assert (
            build_alerts(counts={"queued": 3, "running": 2}, lanes=lanes, backlog_threshold=50, pending_threshold=10)
            == []
        )

    @pytest.mark.unit
    def test_lane_alerts_carry_coordinates(self):
        lanes = {
            "ark:video": {"health": "open", "effective_capacity": 0, "occupied": 0, "pending": 0},
            "gemini:image": {"health": "closed", "effective_capacity": 2, "occupied": 2, "pending": 12},
        }
        alerts = build_alerts(
            counts={"queued": 1, "running": 1}, lanes=lanes, backlog_threshold=50, pending_threshold=10
        )
        by_code = {alert["code"]: alert for alert in alerts}
        assert set(by_code) == {"provider_tripped", "lane_saturated", "pending_wait_high"}
        assert by_code["provider_tripped"]["provider_id"] == "ark"
        assert by_code["provider_tripped"]["media_type"] == "video"
        assert by_code["lane_saturated"]["value"] == 2
        assert by_code["lane_saturated"]["threshold"] == 2
        assert by_code["pending_wait_high"]["value"] == 12
        assert by_code["pending_wait_high"]["threshold"] == 10


class TestSnapshotReads:
    @pytest.mark.integration
    async def test_snapshot_reports_backlog_and_eta_without_worker(self, async_session):
        """未注入 worker 时容量未知：ETA 记 None，而不是假装 0 并发算出无限大。"""
        base = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
        async_session.add_all(
            [
                _task("q1", queued_at=base, provider_id="ark"),
                _task("q2", queued_at=base + timedelta(seconds=1), provider_id="ark"),
                _task(
                    "r1",
                    status="running",
                    queued_at=base,
                    started_at=base,
                    provider_id="gemini",
                ),
                _task(
                    "s1",
                    status="succeeded",
                    queued_at=base,
                    started_at=base,
                    finished_at=base + timedelta(seconds=40),
                ),
            ]
        )
        await async_session.commit()

        snapshot = await build_snapshot(
            async_session,
            project_name="demo",
            now=base + timedelta(seconds=100),
            backlog_alert_threshold=2,
        )

        assert snapshot["counts"] == {
            "queued": 2,
            "running": 1,
            "cancelling": 0,
            "succeeded": 1,
            "failed": 0,
            "cancelled": 0,
            "total": 4,
        }
        assert snapshot["oldest_queued_age_seconds"] == 100.0
        assert snapshot["queued_by_provider"] == {"ark": 2}
        assert snapshot["active_by_media"]["image"]["queued"] == 2

        image_eta = snapshot["eta"]["image"]
        assert image_eta["avg_service_seconds"] == 40.0
        assert image_eta["sample_count"] == 1
        assert image_eta["effective_capacity"] is None
        assert image_eta["eta_seconds"] is None
        assert snapshot["lanes"] == {}
        assert {alert["code"] for alert in snapshot["alerts"]} == {"queue_backlog"}

    @pytest.mark.integration
    async def test_snapshot_uses_worker_lanes_for_eta_and_health(self, async_session):
        """注入 worker 后：有效并发来自泳道快照，ETA = 排队数 x 平均服务时长 / 有效并发。"""
        base = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
        async_session.add_all(
            [_task(f"q{i}", queued_at=base + timedelta(seconds=i)) for i in range(4)]
            + [
                _task(
                    "s1",
                    status="succeeded",
                    queued_at=base,
                    started_at=base,
                    finished_at=base + timedelta(seconds=30),
                )
            ]
        )
        await async_session.commit()
        worker = _StubWorker(
            {
                "ark:image": {
                    "capacity": 2,
                    "effective_capacity": 2,
                    "occupied": 1,
                    "inflight": 1,
                    "pending": 0,
                    "utilization": 0.5,
                    "health": "closed",
                }
            },
            {"ark:image": {"state": "closed"}},
        )

        snapshot = await build_snapshot(
            async_session,
            worker=worker,
            project_name="demo",
            now=base + timedelta(seconds=120),
        )

        image_eta = snapshot["eta"]["image"]
        assert image_eta["effective_capacity"] == 2
        assert image_eta["avg_service_seconds"] == 30.0
        assert image_eta["eta_seconds"] == 60.0
        assert snapshot["lanes"]["ark:image"]["utilization"] == 0.5
        assert snapshot["health"] == {"ark:image": {"state": "closed"}}

    @pytest.mark.integration
    async def test_provider_latencies_filter_and_group(self, async_session):
        base = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
        now = base + timedelta(seconds=100)
        async_session.add_all(
            [
                _call("ark", "video", 100, base + timedelta(seconds=1)),
                _call("ark", "video", 300, base + timedelta(seconds=2)),
                _call("ark", "video", 500, base + timedelta(seconds=3)),
                _call("gemini", "image", 20, base + timedelta(seconds=4)),
                # 失败调用：耗时长尾会把 p95 带偏，必须排除
                _call("ark", "video", 9999, base + timedelta(seconds=5), status="failed"),
                # 无耗时（pending / 老数据）
                _call("ark", "video", None, base + timedelta(seconds=6)),
                # 超出时间窗
                _call("ark", "video", 7777, base - timedelta(hours=5)),
            ]
        )
        await async_session.commit()

        result = await provider_latencies(async_session, project_name="demo", window_seconds=3600, now=now)

        assert result["ark"]["video"] == {"samples": 3, "p50_ms": 300.0, "p95_ms": 500.0, "avg_ms": 300.0}
        assert result["gemini"]["image"]["samples"] == 1
        assert result["gemini"]["image"]["p50_ms"] == 20.0

    @pytest.mark.integration
    async def test_task_queue_position_ranks_within_lane(self, async_session):
        base = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
        async_session.add_all(
            [
                _task("a", queued_at=base),
                _task("b", queued_at=base + timedelta(seconds=1)),
                _task("c", queued_at=base + timedelta(seconds=2)),
                # 另一条泳道不参与本泳道名次
                _task("v1", media_type="video", queued_at=base),
            ]
        )
        await async_session.commit()

        first = await task_queue_position(async_session, "a")
        second = await task_queue_position(async_session, "b")
        assert first is not None and second is not None
        assert first["position"] == 0
        assert second["position"] == 1
        assert second["lane_queued"] == 3
        assert second["media_type"] == "image"

        assert await task_queue_position(async_session, "ghost") is None

    @pytest.mark.integration
    async def test_task_queue_position_none_when_not_queued(self, async_session):
        base = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
        async_session.add_all(
            [
                _task("r1", status="running", queued_at=base, started_at=base),
                _task("q1", queued_at=base + timedelta(seconds=1)),
            ]
        )
        await async_session.commit()

        running = await task_queue_position(async_session, "r1")
        assert running is not None
        assert running["position"] is None, "非 queued 状态不排名次"
        assert running["lane_queued"] == 1
