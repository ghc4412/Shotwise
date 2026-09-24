"""供应商泳道健康度表：状态机、折减、半开探针与退避封顶。"""

from __future__ import annotations

from typing import Any

import pytest

from lib.provider_health import (
    HealthSettings,
    LaneHealthState,
    ProviderHealthTable,
    _read_float_env,
    _read_int_env,
)


class _FakeClock:
    """可推进的单调时钟替身——熔断冷却全部按它记账，测试不睡真实时间。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _table(
    *,
    failure_threshold: int = 3,
    open_seconds: float = 60.0,
    max_open_seconds: float = 600.0,
) -> tuple[ProviderHealthTable, _FakeClock]:
    clock = _FakeClock()
    settings = HealthSettings(
        failure_threshold=failure_threshold,
        open_seconds=open_seconds,
        max_open_seconds=max_open_seconds,
    )
    return ProviderHealthTable(settings, clock=clock), clock


def _trip(table: ProviderHealthTable, provider: str, media: str, *, times: int = 3) -> None:
    for _ in range(times):
        table.record_failure(provider, media, transient=True)


class TestReadEnv:
    """env 解析：坏值回退默认而不是让 worker 起不来。"""

    @pytest.mark.unit
    def test_int_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SHOTWISE_HEALTH_INT", raising=False)
        assert _read_int_env("SHOTWISE_HEALTH_INT", 3) == 3

    @pytest.mark.unit
    def test_int_default_when_not_a_number(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHOTWISE_HEALTH_INT", "abc")
        assert _read_int_env("SHOTWISE_HEALTH_INT", 3) == 3

    @pytest.mark.unit
    def test_int_clamped_to_minimum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHOTWISE_HEALTH_INT", "0")
        assert _read_int_env("SHOTWISE_HEALTH_INT", 3, minimum=1) == 1

    @pytest.mark.unit
    def test_float_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SHOTWISE_HEALTH_FLOAT", raising=False)
        assert _read_float_env("SHOTWISE_HEALTH_FLOAT", 1.5) == 1.5

    @pytest.mark.unit
    def test_float_default_when_not_a_number(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHOTWISE_HEALTH_FLOAT", "soon")
        assert _read_float_env("SHOTWISE_HEALTH_FLOAT", 1.5) == 1.5

    @pytest.mark.unit
    def test_float_default_when_not_finite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHOTWISE_HEALTH_FLOAT", "inf")
        assert _read_float_env("SHOTWISE_HEALTH_FLOAT", 1.5) == 1.5


class TestHealthSettings:
    @pytest.mark.unit
    def test_from_env_overrides_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVIDER_HEALTH_FAILURE_THRESHOLD", "5")
        monkeypatch.setenv("PROVIDER_HEALTH_OPEN_SECONDS", "2.5")
        monkeypatch.setenv("PROVIDER_HEALTH_MAX_OPEN_SECONDS", "30")
        settings = HealthSettings.from_env()
        assert settings.failure_threshold == 5
        assert settings.open_seconds == 2.5
        assert settings.max_open_seconds == 30.0

    @pytest.mark.unit
    def test_from_env_takes_larger_cap_when_cap_below_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """封顶值配到小于首轮冷却时取大者——构造期抛错会让 worker 起不来。"""
        monkeypatch.setenv("PROVIDER_HEALTH_OPEN_SECONDS", "120")
        monkeypatch.setenv("PROVIDER_HEALTH_MAX_OPEN_SECONDS", "10")
        settings = HealthSettings.from_env()
        assert settings.max_open_seconds == 120.0

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("threshold", "open_seconds", "max_open_seconds"),
        [
            (0, 60.0, 600.0),
            (3, 0.0, 600.0),
            (3, 60.0, 10.0),
        ],
    )
    def test_rejects_incoherent_settings(self, threshold: int, open_seconds: float, max_open_seconds: float) -> None:
        with pytest.raises(ValueError):
            HealthSettings(
                failure_threshold=threshold,
                open_seconds=open_seconds,
                max_open_seconds=max_open_seconds,
            )


class TestCapacityReduction:
    """折减：未熔断时按连续失败数收紧，但永远只收紧不放开。"""

    @pytest.mark.unit
    def test_unknown_lane_is_closed_at_full_capacity(self) -> None:
        table, _ = _table()
        assert table.state("ark", "video") is LaneHealthState.CLOSED
        assert table.capacity("ark", "video", 4) == 4
        assert table.blocked_providers("video") == set()

    @pytest.mark.unit
    def test_failures_below_threshold_reduce_capacity_without_tripping(self) -> None:
        table, _ = _table(failure_threshold=3)
        _trip(table, "ark", "video", times=1)
        assert table.state("ark", "video") is LaneHealthState.CLOSED
        assert table.capacity("ark", "video", 4) == 3
        assert table.blocked_providers("video") == set()

        _trip(table, "ark", "video", times=1)
        assert table.capacity("ark", "video", 4) == 2
        assert table.blocked_providers("video") == set()

    @pytest.mark.unit
    def test_capacity_never_drops_below_one_while_closed(self) -> None:
        table, _ = _table(failure_threshold=10)
        _trip(table, "ark", "video", times=8)
        assert table.state("ark", "video") is LaneHealthState.CLOSED
        assert table.capacity("ark", "video", 2) == 1

    @pytest.mark.unit
    def test_capacity_never_exceeds_configured_ceiling(self) -> None:
        """折减只收紧：连续失败不该把上限放大。"""
        table, _ = _table(failure_threshold=3)
        assert table.capacity("ark", "video", 1) == 1
        _trip(table, "ark", "video", times=1)
        assert table.capacity("ark", "video", 1) == 1

    @pytest.mark.unit
    @pytest.mark.parametrize("base", [0, -1])
    def test_non_positive_base_is_returned_untouched(self, base: int) -> None:
        """「不支持该 lane」由容量表定义，健康表不越权把它抬进探针槽。"""
        table, _ = _table(failure_threshold=1)
        _trip(table, "dead", "video", times=1)
        assert table.capacity("dead", "video", base) == base
        assert table.state("dead", "video") is LaneHealthState.OPEN


class TestCircuitBreaker:
    @pytest.mark.unit
    def test_threshold_trips_open_and_blocks_claims(self) -> None:
        table, _ = _table(failure_threshold=3, open_seconds=60.0)
        _trip(table, "ark", "video", times=3)
        assert table.state("ark", "video") is LaneHealthState.OPEN
        assert table.capacity("ark", "video", 5) == 0
        assert table.blocked_providers("video") == {"ark"}
        # 别的媒体泳道不受影响：熔断是 per-lane 的。
        assert table.blocked_providers("image") == set()

    @pytest.mark.unit
    def test_expired_cooldown_reads_as_half_open_with_single_probe_slot(self) -> None:
        table, clock = _table(failure_threshold=1, open_seconds=30.0)
        _trip(table, "ark", "video", times=1)
        assert table.state("ark", "video") is LaneHealthState.OPEN

        clock.advance(30.0)
        assert table.state("ark", "video") is LaneHealthState.HALF_OPEN
        assert table.capacity("ark", "video", 5) == 1
        # 半开不进黑名单：排掉整个 provider 就永远探不出来。
        assert table.blocked_providers("video") == set()

    @pytest.mark.unit
    def test_state_and_capacity_do_not_write(self) -> None:
        """``state`` / ``capacity`` 是纯查询——重复读不改账目，冷却全靠时钟推进。"""
        table, clock = _table(failure_threshold=1, open_seconds=30.0)
        _trip(table, "ark", "video", times=1)
        before = table.snapshot()
        for _ in range(3):
            table.state("ark", "video")
            table.capacity("ark", "video", 4)
        # 时钟没动，重复查询不该改变任何字段
        assert table.snapshot() == before

        clock.advance(30.0)
        assert table.state("ark", "video") is LaneHealthState.HALF_OPEN
        after = table.snapshot()
        # 只有派生字段（状态、剩余秒数）随时钟变，账目本身（失败数、熔断轮次）纹丝不动
        assert after["ark:video"]["open_rounds"] == before["ark:video"]["open_rounds"]
        assert after["ark:video"]["consecutive_failures"] == before["ark:video"]["consecutive_failures"]

    @pytest.mark.unit
    def test_probe_success_restores_full_capacity(self) -> None:
        table, clock = _table(failure_threshold=2, open_seconds=30.0)
        _trip(table, "ark", "video", times=2)
        clock.advance(30.0)
        assert table.state("ark", "video") is LaneHealthState.HALF_OPEN

        table.record_success("ark", "video")
        assert table.state("ark", "video") is LaneHealthState.CLOSED
        assert table.capacity("ark", "video", 5) == 5
        assert table.snapshot() == {}

    @pytest.mark.unit
    def test_success_clears_partial_failure_streak(self) -> None:
        """闭合期的一次成功把连续失败清零——偶发抖动不该累积成熔断。"""
        table, _ = _table(failure_threshold=3)
        _trip(table, "ark", "video", times=2)
        assert table.capacity("ark", "video", 5) == 3

        table.record_success("ark", "video")
        assert table.capacity("ark", "video", 5) == 5

    @pytest.mark.unit
    def test_probe_failure_reopens_with_doubled_cooldown(self) -> None:
        table, clock = _table(failure_threshold=2, open_seconds=10.0, max_open_seconds=600.0)
        _trip(table, "ark", "video", times=2)
        clock.advance(10.0)
        assert table.state("ark", "video") is LaneHealthState.HALF_OPEN

        assert table.record_failure("ark", "video", transient=True) is True
        assert table.state("ark", "video") is LaneHealthState.OPEN
        assert table.snapshot()["ark:video"]["open_seconds_remaining"] == pytest.approx(20.0)
        assert table.snapshot()["ark:video"]["open_rounds"] == 2

    @pytest.mark.unit
    def test_cooldown_backoff_is_capped(self) -> None:
        table, clock = _table(failure_threshold=1, open_seconds=10.0, max_open_seconds=30.0)
        _trip(table, "ark", "video", times=1)
        assert table.snapshot()["ark:video"]["open_seconds_remaining"] == pytest.approx(10.0)

        clock.advance(10.0)
        table.record_failure("ark", "video", transient=True)
        assert table.snapshot()["ark:video"]["open_seconds_remaining"] == pytest.approx(20.0)

        clock.advance(20.0)
        table.record_failure("ark", "video", transient=True)
        # 40s 的下一轮被 30s 封顶收住——持续故障时不会把泳道永久关死。
        assert table.snapshot()["ark:video"]["open_seconds_remaining"] == pytest.approx(30.0)
        assert table.snapshot()["ark:video"]["open_rounds"] == 3

    @pytest.mark.unit
    def test_non_transient_failures_are_not_counted(self) -> None:
        """能力不支持 / 参数非法与上游可用性无关，计进去只会让泳道被无关错误熔断。"""
        table, _ = _table(failure_threshold=1)
        for _ in range(10):
            assert table.record_failure("ark", "video", transient=False) is False
        assert table.state("ark", "video") is LaneHealthState.CLOSED
        assert table.capacity("ark", "video", 4) == 4
        assert table.snapshot() == {}

    @pytest.mark.unit
    def test_record_failure_reports_whether_lane_tripped(self) -> None:
        table, _ = _table(failure_threshold=2)
        assert table.record_failure("ark", "video", transient=True) is False
        assert table.record_failure("ark", "video", transient=True) is True

    @pytest.mark.unit
    def test_lanes_are_isolated_per_provider_and_media(self) -> None:
        table, _ = _table(failure_threshold=1)
        _trip(table, "ark", "video", times=1)
        assert table.blocked_providers("video") == {"ark"}
        assert table.blocked_providers("image") == set()
        assert table.state("other", "video") is LaneHealthState.CLOSED


class TestSnapshot:
    @pytest.mark.unit
    def test_reports_only_lanes_with_history(self) -> None:
        table, _ = _table(failure_threshold=3)
        assert table.snapshot() == {}

        _trip(table, "ark", "video", times=1)
        snapshot: dict[str, dict[str, Any]] = table.snapshot()
        assert set(snapshot) == {"ark:video"}
        entry = snapshot["ark:video"]
        assert entry["state"] == "closed"
        assert entry["consecutive_failures"] == 1
        assert entry["open_rounds"] == 0
        assert entry["open_seconds_remaining"] == 0.0

    @pytest.mark.unit
    def test_remaining_seconds_counts_down_and_floors_at_zero(self) -> None:
        table, clock = _table(failure_threshold=1, open_seconds=30.0)
        _trip(table, "ark", "video", times=1)
        assert table.snapshot()["ark:video"]["open_seconds_remaining"] == pytest.approx(30.0)

        clock.advance(45.0)
        assert table.snapshot()["ark:video"]["open_seconds_remaining"] == 0.0
        assert table.snapshot()["ark:video"]["state"] == "half_open"
