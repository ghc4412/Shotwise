"""队列可观测性只读读层。

把四个数据源拼成一份诊断快照：

- ``Task`` 表 —— 积压（按状态 / 媒体类型 / 供应商）、最老排队时长、任务排队名次；
- ``ApiCall`` 表 —— 按 ``(provider, call_type)`` 的完成耗时 p50 / p95；
- ``GenerationWorker`` 的内存泳道快照 —— 容量 / 有效并发 / 占用 / 健康态（可选注入）；
- ``WorkerLease`` 行 —— 进程级 worker 在线态，用来区分「泳道空闲」与「根本没有 worker」。

只读约束：不写库、不改调度决策、不 requeue（ADR 0007：孤儿任务不自动重排，image 不
resume）。查询自带在本模块内，不复用 ``TaskRepository`` / ``GenerationQueue`` 的写路径，
避免与状态机耦合。

告警只输出机器可读的 ``code`` + 数值/阈值，文案由调用方（前端）按 code 本地化——本模块
不落面向用户的自然语言字符串。分位数在 Python 侧按最近秩计算：SQLite 没有
``percentile_cont``，在 SQL 里算会让两套方言分叉，而这里只需要诊断精度。
"""

from __future__ import annotations

import logging
import math
import statistics
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.api_call import ApiCall
from lib.db.models.task import Task, WorkerLease
from lib.provider_health import _read_float_env, _read_int_env

logger = logging.getLogger(__name__)

# 活动状态口径与 TaskRepository.ACTIVE_TASK_STATUSES 一致（本模块独立读，不 import 仓库层）。
ACTIVE_STATUSES = ("queued", "running", "cancelling")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")

DEFAULT_LATENCY_WINDOW_SECONDS = 3600.0
DEFAULT_LATENCY_SAMPLE_LIMIT = 5000
DEFAULT_BACKLOG_ALERT_THRESHOLD = 50
DEFAULT_PENDING_ALERT_THRESHOLD = 10
# 进程级选主行的 name（GenerationWorker._run_loop 每轮续约的就是这一行）。
DEFAULT_WORKER_LEASE_NAME = "default"

# 告警严重度取值：info（格子满，属正常） < warning（需关注） < critical（队列卡住）。


def _as_utc(value: datetime | None) -> datetime | None:
    """把 SQLite 取回的 naive datetime 归一成 aware UTC。

    跨 session 回读时 SQLite 丢 tzinfo（与 ``UsageRepository._settle`` 同一现象），
    直接与 ``utc_now()`` 相减会抛 TypeError。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def worker_lease_state(
    session: AsyncSession,
    *,
    name: str = DEFAULT_WORKER_LEASE_NAME,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """读进程级选主行（``WorkerLease``）的在线态。

    口径与 ``TaskRepository.is_worker_online`` 一致：``lease_until`` 是 epoch 秒，缺行
    或已过期都算离线。本模块独立读该表，不经仓库层。

    快照需要这个跨进程信号，是因为 ``lanes`` 只反映**本进程**注入的 worker：泳道为空既
    可能是「空闲」，也可能是「这个进程根本没挂 worker」。少了这一位，两种情况会被读成
    同一种，诊断结论正好相反。
    """
    result = await session.execute(select(WorkerLease.lease_until).where(WorkerLease.name == name))
    row = result.first()
    if row is None:
        return {"name": name, "online": False, "lease_remaining_seconds": None}
    epoch = time.time() if now_epoch is None else now_epoch
    return {
        "name": name,
        "online": row[0] > epoch,
        "lease_remaining_seconds": round(float(row[0]) - epoch, 1),
    }


def percentile(sorted_values: Sequence[float], quantile: float) -> float:
    """最近秩（nearest-rank）分位数，``sorted_values`` 必须升序且非空。"""
    if not sorted_values:
        raise ValueError("percentile() 需要至少一个样本")
    rank = max(1, math.ceil(quantile * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def summarize_durations(durations: Sequence[int]) -> dict[str, float]:
    """把一组 ``duration_ms`` 收成 p50 / p95 / 均值；空样本返回全 0 计数。"""
    if not durations:
        return {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0, "avg_ms": 0.0}
    ordered = sorted(float(d) for d in durations)
    return {
        "samples": len(ordered),
        "p50_ms": round(percentile(ordered, 0.5), 1),
        "p95_ms": round(percentile(ordered, 0.95), 1),
        "avg_ms": round(statistics.fmean(ordered), 1),
    }


def estimate_eta_seconds(
    *,
    queued: int,
    avg_service_seconds: float | None,
    effective_capacity: int,
) -> float | None:
    """粗排期估计：``排队数 x 平均服务时长 / 有效并发``。

    样本不足、没有排队、或该媒体类型下所有泳道都被熔断（有效并发 0）时返回 None——
    宁可报「算不出」，也不给一个假装精确的数字。
    """
    if queued <= 0 or effective_capacity <= 0:
        return None
    if avg_service_seconds is None or avg_service_seconds <= 0:
        return None
    return round(queued * avg_service_seconds / effective_capacity, 1)


def _project_filter(column: Any, project_name: str | None) -> list[Any]:
    return [column == project_name] if project_name else []


async def _task_status_counts(session: AsyncSession, project_name: str | None) -> dict[str, int]:
    """按状态分组计数；缺失的状态补 0，形状与 ``/tasks/stats`` 一致。"""
    stmt = select(Task.status, func.count().label("cnt")).where(*_project_filter(Task.project_name, project_name))
    rows = (await session.execute(stmt.group_by(Task.status))).all()
    counts: dict[str, int] = dict.fromkeys((*ACTIVE_STATUSES, *TERMINAL_STATUSES), 0)
    total = 0
    for status, cnt in rows:
        if status in counts:
            counts[status] = cnt
        total += cnt
    counts["total"] = total
    return counts


async def _active_by_media(session: AsyncSession, project_name: str | None) -> dict[str, dict[str, int]]:
    """活动任务按媒体类型 × 状态分桶（只含活动状态，终态不进积压视图）。"""
    stmt = (
        select(Task.media_type, Task.status, func.count().label("cnt"))
        .where(Task.status.in_(ACTIVE_STATUSES), *_project_filter(Task.project_name, project_name))
        .group_by(Task.media_type, Task.status)
        .order_by(Task.media_type)
    )
    buckets: dict[str, dict[str, int]] = {}
    for media_type, status, cnt in (await session.execute(stmt)).all():
        buckets.setdefault(media_type, dict.fromkeys(ACTIVE_STATUSES, 0))[status] = cnt
    return buckets


async def _queued_by_provider(session: AsyncSession, project_name: str | None) -> dict[str, int]:
    """排队中的任务按 provider_id 分桶；未落 provider 的老数据显示为 ``"unknown"``。"""
    stmt = (
        select(Task.provider_id, func.count().label("cnt"))
        .where(Task.status == "queued", *_project_filter(Task.project_name, project_name))
        .group_by(Task.provider_id)
    )
    return {(provider_id or "unknown"): cnt for provider_id, cnt in (await session.execute(stmt)).all()}


async def _oldest_queued_at(session: AsyncSession, project_name: str | None) -> datetime | None:
    stmt = select(func.min(Task.queued_at)).where(
        Task.status == "queued", *_project_filter(Task.project_name, project_name)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _service_time_samples(
    session: AsyncSession,
    *,
    project_name: str | None,
    limit: int,
) -> dict[str, list[float]]:
    """最近完成的成功任务按媒体类型给一组服务时长（秒），用于 ETA 的均值。

    取 ``finished_at - started_at``（含重试与排队后的真实执行时长），而不是
    ``ApiCall.duration_ms``：后者是一次上游调用的耗时，不含重试与本地落盘。
    """
    stmt = (
        select(Task.media_type, Task.started_at, Task.finished_at)
        .where(
            Task.status == "succeeded",
            Task.started_at.is_not(None),
            Task.finished_at.is_not(None),
            *_project_filter(Task.project_name, project_name),
        )
        .order_by(Task.finished_at.desc())
        .limit(limit)
    )
    samples: dict[str, list[float]] = {}
    for media_type, started_at, finished_at in (await session.execute(stmt)).all():
        started = _as_utc(started_at)
        finished = _as_utc(finished_at)
        if started is None or finished is None:
            continue
        seconds = (finished - started).total_seconds()
        if seconds > 0:
            samples.setdefault(media_type, []).append(seconds)
    return samples


async def provider_latencies(
    session: AsyncSession,
    *,
    project_name: str | None = None,
    window_seconds: float | None = None,
    sample_limit: int | None = None,
    now: datetime | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """按 ``provider`` → ``call_type`` 汇总最近完成调用的 p50 / p95。

    只统计 ``status == 'success'`` 且有 ``duration_ms`` 的调用：失败调用的耗时长尾
    （超时被掐断）会把 p95 带偏，失败率另有 ``usage`` 端点负责。
    """
    resolved_window = (
        window_seconds
        if window_seconds is not None
        else _read_float_env("QUEUE_LATENCY_WINDOW_SECONDS", DEFAULT_LATENCY_WINDOW_SECONDS, minimum=60.0)
    )
    resolved_limit = (
        sample_limit
        if sample_limit is not None
        else _read_int_env("QUEUE_LATENCY_SAMPLE_LIMIT", DEFAULT_LATENCY_SAMPLE_LIMIT, minimum=1)
    )
    cutoff = (now or utc_now()) - timedelta(seconds=resolved_window)
    stmt = (
        select(ApiCall.provider, ApiCall.call_type, ApiCall.duration_ms)
        .where(
            ApiCall.status == "success",
            ApiCall.duration_ms.is_not(None),
            ApiCall.finished_at.is_not(None),
            ApiCall.finished_at >= cutoff,
            *_project_filter(ApiCall.project_name, project_name),
        )
        .order_by(ApiCall.finished_at.desc())
        .limit(resolved_limit)
    )
    grouped: dict[str, dict[str, list[int]]] = {}
    for provider, call_type, duration_ms in (await session.execute(stmt)).all():
        grouped.setdefault(provider or "unknown", {}).setdefault(call_type, []).append(duration_ms)
    return {
        provider: {call_type: summarize_durations(durations) for call_type, durations in call_types.items()}
        for provider, call_types in grouped.items()
    }


async def task_queue_position(session: AsyncSession, task_id: str) -> dict[str, Any] | None:
    """单个任务在同一媒体类型泳道里的排队名次；任务不存在返回 None。

    ``position`` 是 0 基名次，按 claim 的排序键 ``(queued_at, task_id)`` 计算，等价于
    ``claim_next`` 的 ``ORDER BY queued_at ASC``。依赖未就绪的任务也计入，因此它是
    等待时间的上界而非精确值。非 queued 状态的任务不排名次（``position`` 为 None），
    但仍给出所在泳道的排队规模。
    """
    task = (await session.execute(select(Task).where(Task.task_id == task_id))).scalar_one_or_none()
    if task is None:
        return None

    lane_queued = (
        await session.execute(
            select(func.count()).select_from(Task).where(Task.status == "queued", Task.media_type == task.media_type)
        )
    ).scalar_one()

    position: int | None = None
    if task.status == "queued":
        ahead = (
            select(func.count())
            .select_from(Task)
            .where(
                Task.status == "queued",
                Task.media_type == task.media_type,
                (Task.queued_at < task.queued_at)
                | ((Task.queued_at == task.queued_at) & (Task.task_id < task.task_id)),
            )
        )
        position = (await session.execute(ahead)).scalar_one()

    return {
        "task_id": task.task_id,
        "project_name": task.project_name,
        "status": task.status,
        "media_type": task.media_type,
        "provider_id": task.provider_id,
        "position": position,
        "lane_queued": lane_queued,
        "queued_at": task.queued_at.isoformat() if task.queued_at else None,
    }


def build_alerts(
    *,
    counts: dict[str, int],
    worker_online: bool,
    lanes: dict[str, dict[str, Any]],
    backlog_threshold: int,
    pending_threshold: int,
) -> list[dict[str, Any]]:
    """从积压计数与泳道快照派生告警条目（纯函数，无 I/O）。

    每条告警只有 ``code`` / ``severity`` / 数值字段：文案在前端按 code 本地化，后端不
    造自然语言。``provider_tripped`` 与 ``lane_saturated`` 都带泳道坐标，便于前端直接
    高亮对应格子。

    停滞拆成两种：``worker_offline``（没有进程持有选主行，活干不了，要重启/查服务）与
    ``queue_stalled``（worker 在线却没任务在跑，通常是泳道全熔断或容量为 0）。两者的
    处置动作不同，合成一个 code 会把运维引到错的方向。
    """
    alerts: list[dict[str, Any]] = []

    queued = counts.get("queued", 0)
    running = counts.get("running", 0)
    if queued >= backlog_threshold:
        alerts.append(
            {
                "code": "queue_backlog",
                "severity": "warning",
                "value": queued,
                "threshold": backlog_threshold,
            }
        )
    if queued + running > 0 and not worker_online:
        # 有活却没人持有选主行：重启空档与崩溃后残留的 running 都落在这里。
        alerts.append({"code": "worker_offline", "severity": "critical", "value": queued, "running": running})
    elif queued > 0 and running == 0:
        # worker 在线却一个都没在跑：所有泳道都被熔断、容量为 0，或依赖尚未就绪。
        alerts.append({"code": "queue_stalled", "severity": "critical", "value": queued})

    for lane_key in sorted(lanes):
        lane = lanes[lane_key]
        provider_id, _, media_type = lane_key.rpartition(":")
        health = lane.get("health")
        if health == "open":
            alerts.append(
                {
                    "code": "provider_tripped",
                    "severity": "warning",
                    "provider_id": provider_id,
                    "media_type": media_type,
                }
            )
        effective = int(lane.get("effective_capacity", 0))
        if effective > 0 and int(lane.get("occupied", 0)) >= effective:
            alerts.append(
                {
                    "code": "lane_saturated",
                    "severity": "info",
                    "provider_id": provider_id,
                    "media_type": media_type,
                    "value": int(lane.get("occupied", 0)),
                    "threshold": effective,
                }
            )
        pending = int(lane.get("pending", 0))
        if pending >= pending_threshold:
            # 视频通道的 sem 限流子任务：占着槽位却还没真正发起上游调用。
            alerts.append(
                {
                    "code": "pending_wait_high",
                    "severity": "warning",
                    "provider_id": provider_id,
                    "media_type": media_type,
                    "value": pending,
                    "threshold": pending_threshold,
                }
            )
    return alerts


def _eta_by_media(
    active_by_media: dict[str, dict[str, int]],
    service_samples: dict[str, list[float]],
    lanes: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """按媒体类型汇总 ETA：排队数、平均服务时长、该类型下全部泳道的有效并发之和。"""
    capacity_by_media: dict[str, int] = {}
    for lane_key, lane in lanes.items():
        media_type = lane_key.rpartition(":")[2]
        capacity_by_media[media_type] = capacity_by_media.get(media_type, 0) + int(lane.get("effective_capacity", 0))

    eta: dict[str, dict[str, Any]] = {}
    for media_type, buckets in active_by_media.items():
        queued = buckets.get("queued", 0)
        samples = service_samples.get(media_type, [])
        avg_seconds = round(statistics.fmean(samples), 1) if samples else None
        effective_capacity = capacity_by_media.get(media_type)
        # 没有泳道快照时（未注入 worker）容量未知，ETA 记 None 而不是假装 0 并发。
        eta[media_type] = {
            "queued": queued,
            "running": buckets.get("running", 0),
            "sample_count": len(samples),
            "avg_service_seconds": avg_seconds,
            "effective_capacity": effective_capacity,
            "eta_seconds": (
                estimate_eta_seconds(
                    queued=queued,
                    avg_service_seconds=avg_seconds,
                    effective_capacity=effective_capacity or 0,
                )
                if effective_capacity is not None
                else None
            ),
        }
    return eta


async def build_snapshot(
    session: AsyncSession,
    *,
    worker: Any | None = None,
    project_name: str | None = None,
    now: datetime | None = None,
    latency_window_seconds: float | None = None,
    latency_sample_limit: int | None = None,
    service_sample_limit: int = 500,
    backlog_alert_threshold: int | None = None,
    pending_alert_threshold: int | None = None,
) -> dict[str, Any]:
    """拼出完整诊断快照。

    ``worker`` 可省略：省掉泳道快照与 ETA 容量分母（``worker`` 块仍给出选主行在线态，
    并把 ``in_process`` 记为 False）。
    """
    resolved_now = now or utc_now()
    counts = await _task_status_counts(session, project_name)
    active_by_media = await _active_by_media(session, project_name)
    queued_by_provider = await _queued_by_provider(session, project_name)
    oldest_queued_at = await _oldest_queued_at(session, project_name)

    lanes: dict[str, dict[str, Any]] = {}
    health: dict[str, Any] = {}
    if worker is not None:
        worker_snapshot = worker.observability_snapshot()
        lanes = worker_snapshot.get("lanes", {})
        health = worker_snapshot.get("health", {})

    service_samples = await _service_time_samples(session, project_name=project_name, limit=service_sample_limit)
    resolved_backlog = (
        backlog_alert_threshold
        if backlog_alert_threshold is not None
        else _read_int_env("QUEUE_BACKLOG_ALERT_THRESHOLD", DEFAULT_BACKLOG_ALERT_THRESHOLD, minimum=1)
    )
    resolved_pending = (
        pending_alert_threshold
        if pending_alert_threshold is not None
        else _read_int_env("QUEUE_PENDING_ALERT_THRESHOLD", DEFAULT_PENDING_ALERT_THRESHOLD, minimum=1)
    )

    worker_state = await worker_lease_state(session, now_epoch=resolved_now.timestamp())
    # 「本进程挂没挂 worker」与「有没有进程持有选主行」是两件事，一起给出才不会误读空泳道。
    worker_state["in_process"] = worker is not None

    oldest = _as_utc(oldest_queued_at)
    return {
        "generated_at": resolved_now.isoformat(),
        "project_name": project_name,
        "worker": worker_state,
        "counts": counts,
        "active_by_media": active_by_media,
        "queued_by_provider": queued_by_provider,
        "oldest_queued_at": oldest.isoformat() if oldest else None,
        "oldest_queued_age_seconds": (
            round((resolved_now - oldest).total_seconds(), 1) if oldest is not None else None
        ),
        "eta": _eta_by_media(active_by_media, service_samples, lanes),
        "providers": await provider_latencies(
            session,
            project_name=project_name,
            window_seconds=latency_window_seconds,
            sample_limit=latency_sample_limit,
            now=resolved_now,
        ),
        "lanes": lanes,
        "health": health,
        "alerts": build_alerts(
            counts=counts,
            worker_online=bool(worker_state["online"]),
            lanes=lanes,
            backlog_threshold=resolved_backlog,
            pending_threshold=resolved_pending,
        ),
    }


def log_alerts(alerts: Sequence[dict[str, Any]], *, project_name: str | None = None) -> None:
    """把告警落进日志（结构化 code + 数值，供运维侧聚合）。"""
    if not alerts:
        return
    summary = ", ".join(
        f"{alert['code']}({alert.get('provider_id', '-')}:{alert.get('media_type', '-')})"
        if "provider_id" in alert
        else f"{alert['code']}={alert.get('value')}"
        for alert in alerts
    )
    logger.warning("队列告警 project=%s: %s", project_name or "-", summary)
