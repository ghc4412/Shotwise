"""供应商泳道健康度：连续瞬态失败熔断泳道，半开探针恢复，闭合期逐次降并发。

一条泳道 = 一个 ``(provider_id, media_type)``。状态纯内存、不落库：进程重启即清零，
与单 lease 单活 worker 的部署形态一致（多进程各自熔断，互不可见）。

与 ``CapacityTable`` 正交：容量表是用户配置的并发**上限**，本表是在其之上的**健康折减**。
折减只收紧不放开——``capacity()`` 的返回值永远不超过传入的上限；只要上限本身 ≥ 1，
折减结果也永远 ≥ 1（``OPEN`` 除外）。熔断只推迟认领，不改变「该泳道是否支持该媒体类型」
这一配置事实——那是容量表 ``0`` 的语义，两者由调用方分开处理。

状态机：

- ``CLOSED``：正常。有效并发 = ``上限 - 连续瞬态失败数``，下限 1；任一成功即复原满血。
- ``OPEN``：连续瞬态失败达到阈值。有效并发 0，泳道进 claim 黑名单，任务留在 ``queued``。
- ``HALF_OPEN``：冷却到期。有效并发压到 1——放一个真实任务当探针：成功 → ``CLOSED``，
  失败 → 重新 ``OPEN`` 且冷却翻倍（封顶 ``max_open_seconds``），避免持续故障时反复试探。
"""

from __future__ import annotations

import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("环境变量 %s 的取值非法（%r），回退默认值 %d", name, raw, default)
        return default
    return max(minimum, value)


def _read_float_env(name: str, default: float, minimum: float = 0.1) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("环境变量 %s 的取值非法（%r），回退默认值 %s", name, raw, default)
        return default
    if not math.isfinite(value):
        logger.warning("环境变量 %s 的取值非有限数（%r），回退默认值 %s", name, raw, default)
        return default
    return max(minimum, value)


class LaneHealthState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class HealthSettings:
    """熔断参数。三项都可由环境变量覆盖，调参不需要数据库迁移。"""

    failure_threshold: int = 3
    open_seconds: float = 60.0
    max_open_seconds: float = 600.0

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold 必须 >= 1")
        if self.open_seconds <= 0:
            raise ValueError("open_seconds 必须 > 0")
        if self.max_open_seconds < self.open_seconds:
            raise ValueError("max_open_seconds 不得小于 open_seconds")

    @classmethod
    def from_env(cls) -> HealthSettings:
        open_seconds = _read_float_env("PROVIDER_HEALTH_OPEN_SECONDS", 60.0)
        # 环境变量可能把封顶值配到小于首轮冷却——取大者而不是抛错，构造期失败会让 worker 起不来。
        max_open_seconds = max(_read_float_env("PROVIDER_HEALTH_MAX_OPEN_SECONDS", 600.0), open_seconds)
        return cls(
            failure_threshold=_read_int_env("PROVIDER_HEALTH_FAILURE_THRESHOLD", 3, minimum=1),
            open_seconds=open_seconds,
            max_open_seconds=max_open_seconds,
        )


@dataclass
class _Lane:
    """单条泳道的健康账。``open_until`` 为 None 表示从未熔断。"""

    consecutive_failures: int = 0
    open_until: float | None = None
    open_rounds: int = 0


class ProviderHealthTable:
    """``(provider_id, media_type)`` → 健康状态。

    被动纯内存数据结构：不写 DB、不解析 provider、不决定任务终态。调用方负责把
    ``capacity()`` 的结果当作并发上限用，把 ``blocked_providers()`` 的结果并进 claim 黑名单。
    """

    def __init__(
        self,
        settings: HealthSettings | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings or HealthSettings()
        self._clock = clock
        self._lanes: dict[tuple[str, str], _Lane] = {}

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def state(self, provider_id: str, media_type: str) -> LaneHealthState:
        """当前状态。``OPEN`` 冷却到期后自动读作 ``HALF_OPEN``（不落写，纯函数）。"""
        lane = self._lanes.get((provider_id, media_type))
        if lane is None or lane.open_until is None:
            return LaneHealthState.CLOSED
        return LaneHealthState.OPEN if self._clock() < lane.open_until else LaneHealthState.HALF_OPEN

    def capacity(self, provider_id: str, media_type: str, base_capacity: int) -> int:
        """健康折减后的有效并发上限。

        ``base_capacity <= 0`` 原样返回：「该泳道不支持该媒体类型」由容量表定义，健康表不越权
        把 0 改成 1（否则不支持的泳道会拿到一个探针槽，任务从 fail-fast 变成真发上游）。
        """
        if base_capacity <= 0:
            return base_capacity
        match self.state(provider_id, media_type):
            case LaneHealthState.OPEN:
                return 0
            case LaneHealthState.HALF_OPEN:
                return 1
            case _:
                # 无账目 = 从未失败过，满血通过；有账目但未达阈值才逐次收紧。
                lane = self._lanes.get((provider_id, media_type))
                failures = 0 if lane is None else lane.consecutive_failures
                return max(1, base_capacity - failures)

    def blocked_providers(self, media_type: str) -> set[str]:
        """``media_type`` 上熔断打开（``OPEN``）的 provider 集合——黑名单源，与占用无关。

        ``HALF_OPEN`` 不入内：它要放一个探针任务，把整个 provider 排掉就永远探不出来。
        """
        return {
            provider
            for provider, media in self._lanes
            if media == media_type and self.state(provider, media) is LaneHealthState.OPEN
        }

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """非满血泳道的只读快照，键为 ``"provider:media"``（诊断 / 测试用）。"""
        now = self._clock()
        out: dict[str, dict[str, Any]] = {}
        for (provider, media), lane in self._lanes.items():
            state = self.state(provider, media)
            remaining = 0.0 if lane.open_until is None else max(0.0, lane.open_until - now)
            out[f"{provider}:{media}"] = {
                "state": state.value,
                "consecutive_failures": lane.consecutive_failures,
                "open_rounds": lane.open_rounds,
                "open_seconds_remaining": remaining,
            }
        return out

    # ------------------------------------------------------------------
    # 记账
    # ------------------------------------------------------------------

    def record_success(self, provider_id: str, media_type: str) -> None:
        """任一成功（含半开探针）都把泳道恢复满血：连续失败清零、熔断轮次清零。"""
        if self._lanes.pop((provider_id, media_type), None) is not None:
            logger.info("供应商泳道恢复满血 provider=%s media=%s", provider_id, media_type)

    def record_failure(self, provider_id: str, media_type: str, *, transient: bool) -> bool:
        """记一次失败，返回本次是否触发 / 维持了熔断（供调用方打点）。

        ``transient=False``（能力不支持、参数非法、本地资产缺失……）不计健康账：这些失败与
        上游可用性无关，计进去只会让泳道被无关错误熔断。
        """
        if not transient:
            return False
        lane = self._lanes.setdefault((provider_id, media_type), _Lane())
        now = self._clock()
        if self.state(provider_id, media_type) is LaneHealthState.HALF_OPEN:
            self._trip(lane, now)
            logger.warning(
                "供应商泳道半开探针失败，重新熔断 provider=%s media=%s 冷却=%.1fs 轮次=%d",
                provider_id,
                media_type,
                lane.open_until - now if lane.open_until is not None else 0.0,
                lane.open_rounds,
            )
            return True
        lane.consecutive_failures += 1
        if lane.consecutive_failures < self._settings.failure_threshold:
            return False
        self._trip(lane, now)
        logger.warning(
            "供应商泳道连续瞬态失败熔断 provider=%s media=%s 冷却=%.1fs 轮次=%d",
            provider_id,
            media_type,
            lane.open_until - now if lane.open_until is not None else 0.0,
            lane.open_rounds,
        )
        return True

    def _trip(self, lane: _Lane, now: float) -> None:
        """打开熔断：冷却按 2 的幂次翻倍，封顶 ``max_open_seconds``。"""
        lane.open_rounds += 1
        delay = min(self._settings.open_seconds * 2 ** (lane.open_rounds - 1), self._settings.max_open_seconds)
        lane.open_until = now + delay
        lane.consecutive_failures = 0
