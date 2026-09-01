"""Adapters from episode duration plans to provider-ready task requests.

The adapter keeps planning separate from script persistence.  It turns an immutable
episode plan into requests for adjustable items only; locked or already-generated
items remain outside the plan's task-request output and are never mutated here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from lib.episode_duration_plan import (
    DurationPlanningStrategy,
    EpisodeDurationPlan,
    EpisodeDurationPlanner,
    ShotDurationInput,
)


@dataclass(frozen=True, slots=True)
class EpisodeDurationTaskRequest:
    """A provider-agnostic duration request for one adjustable task."""

    resource_id: str
    allocated_seconds: int
    requested_seconds: int
    clamp_reason: str | None = None

    def as_task_payload(self) -> dict[str, int]:
        """Return task fields while retaining the legacy execution field."""
        return {
            "requested_seconds": self.requested_seconds,
            "duration_seconds": self.requested_seconds,
        }


class EpisodeDurationTaskAdapter:
    """Deep adapter that hides planning and provider-duration clamping from callers.

    The interface accepts stable shot views and returns an immutable plan plus a
    request list.  It never edits the input mappings or the persisted script.
    Unknown provider capabilities are intentionally not represented by this adapter:
    callers must supply the resolved supported durations before asking for requests.
    """

    def __init__(self, planner: EpisodeDurationPlanner | None = None) -> None:
        self._planner = planner or EpisodeDurationPlanner()

    def plan_requests(
        self,
        *,
        target_seconds: int,
        shots: Iterable[ShotDurationInput],
        strategy: DurationPlanningStrategy = DurationPlanningStrategy.EQUAL,
        manual_allocations: Mapping[str, int] | None = None,
        source_revision: str | None = None,
    ) -> tuple[EpisodeDurationPlan, tuple[EpisodeDurationTaskRequest, ...]]:
        """Build a plan and requests for only unlocked, ungenerated shots."""
        shot_list = tuple(shots)
        plan = self._planner.build_plan(
            target_seconds=target_seconds,
            shots=shot_list,
            strategy=strategy,
            manual_allocations=manual_allocations,
            source_revision=source_revision,
        )
        requests = tuple(
            EpisodeDurationTaskRequest(
                resource_id=allocation.shot_id,
                allocated_seconds=allocation.allocated_seconds,
                requested_seconds=allocation.requested_seconds,
                clamp_reason=allocation.clamp_reason,
            )
            for allocation in plan.allocations
            if not allocation.locked
            and not allocation.generated
            and allocation.allocated_seconds is not None
            and allocation.requested_seconds is not None
        )
        return plan, requests

    def plan_item_requests(
        self,
        *,
        target_seconds: int,
        items: Iterable[Mapping[str, Any]],
        id_field: str,
        supported_durations: Iterable[int],
        strategy: DurationPlanningStrategy = DurationPlanningStrategy.EQUAL,
        manual_allocations: Mapping[str, int] | None = None,
        source_revision: str | None = None,
    ) -> tuple[EpisodeDurationPlan, tuple[EpisodeDurationTaskRequest, ...]]:
        """Build requests from script-like mappings without changing those mappings."""
        supported = tuple(supported_durations)
        shots = tuple(
            ShotDurationInput(
                shot_id=str(item.get(id_field) or ""),
                current_seconds=_current_duration(item),
                supported_durations=supported,
                locked=item.get("duration_locked") is True or item.get("locked") is True,
                generated=_has_generated_video(item),
            )
            for item in items
        )
        return self.plan_requests(
            target_seconds=target_seconds,
            shots=shots,
            strategy=strategy,
            manual_allocations=manual_allocations,
            source_revision=source_revision,
        )


def _current_duration(item: Mapping[str, Any]) -> int | None:
    value = item.get("duration_seconds")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _has_generated_video(item: Mapping[str, Any]) -> bool:
    assets = item.get("generated_assets")
    if not isinstance(assets, Mapping):
        return False
    return bool(assets.get("video_clip") or assets.get("video_uri") or assets.get("status") == "completed")


__all__ = ["EpisodeDurationTaskAdapter", "EpisodeDurationTaskRequest"]
