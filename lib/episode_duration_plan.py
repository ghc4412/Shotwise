"""Episode-level duration planning without mutating persisted shot durations.

The planner deliberately separates a creative episode target from provider-ready task
requests.  Callers may preview a plan and apply it only after explicit confirmation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DurationPlanningStrategy(StrEnum):
    """Supported allocation strategies for unlocked, ungenerated shots."""

    EQUAL = "equal"
    PROPORTIONAL = "proportional"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class EpisodeDurationPlanConfig:
    """Persistable episode planning settings, separate from shot durations."""

    target_seconds: int
    strategy: DurationPlanningStrategy = DurationPlanningStrategy.EQUAL
    manual_allocations: Mapping[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_seconds": self.target_seconds,
            "strategy": self.strategy.value,
            "manual_allocations": dict(self.manual_allocations),
        }


def read_episode_duration_plan(
    project: Mapping[str, Any] | None,
    script: Mapping[str, Any] | None,
) -> EpisodeDurationPlanConfig | None:
    """Read the compatible planning representation without changing either input.

    The canonical representation lives in ``script.metadata.episode_duration_plan``.
    ``episode_target_duration`` and the existing ad-only ``project.target_duration``
    are accepted as compatibility fallbacks so older projects do not need a migration.
    Malformed optional planning data is ignored and leaves the existing generation
    duration path in charge.
    """

    project = project or {}
    script = script or {}
    metadata = script.get("metadata")
    raw_plan = metadata.get("episode_duration_plan") if isinstance(metadata, Mapping) else None
    if not isinstance(raw_plan, Mapping):
        raw_plan = None

    if raw_plan is None:
        raw_plan = _find_legacy_plan(project, script, metadata)

    if raw_plan is None:
        return None
    return _coerce_plan_config(raw_plan)


def _find_legacy_plan(
    project: Mapping[str, Any], script: Mapping[str, Any], metadata: Mapping[str, Any] | None
) -> Mapping[str, Any] | None:
    """Find non-migrating compatibility fields used by existing project data."""

    episode = script.get("episode")
    plans = project.get("episode_duration_plans")
    if isinstance(plans, Mapping) and episode is not None:
        candidate = plans.get(str(episode))
        if isinstance(candidate, Mapping):
            return candidate

    for entry in project.get("episodes") or ():
        if not isinstance(entry, Mapping) or entry.get("episode") != episode:
            continue
        if "episode_duration_plan" in entry and isinstance(entry["episode_duration_plan"], Mapping):
            return entry["episode_duration_plan"]
        if "episode_target_duration" in entry:
            return {"target_seconds": entry["episode_target_duration"]}

    if "episode_target_duration" in script:
        return {"target_seconds": script["episode_target_duration"]}
    if isinstance(metadata, Mapping) and "episode_target_duration" in metadata:
        return {"target_seconds": metadata["episode_target_duration"]}
    if "episode_target_duration" in project:
        return {"target_seconds": project["episode_target_duration"]}
    if "target_duration" in project:
        return {"target_seconds": project["target_duration"]}
    return None


def _coerce_plan_config(raw: Mapping[str, Any]) -> EpisodeDurationPlanConfig | None:
    target = raw.get("target_seconds", raw.get("episode_target_duration"))
    if not isinstance(target, int) or isinstance(target, bool) or target <= 0:
        return None

    raw_strategy = raw.get("strategy", DurationPlanningStrategy.EQUAL.value)
    try:
        strategy = DurationPlanningStrategy(raw_strategy)
    except (TypeError, ValueError):
        return None

    raw_manual = raw.get("manual_allocations", {})
    if raw_manual is None:
        raw_manual = {}
    if not isinstance(raw_manual, Mapping):
        return None
    manual: dict[str, int] = {}
    for shot_id, value in raw_manual.items():
        if not isinstance(shot_id, str) or not shot_id:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return None
        manual[shot_id] = value
    return EpisodeDurationPlanConfig(target, strategy, manual)


def is_item_duration_locked(item: Mapping[str, Any]) -> bool:
    """Return the additive duration-lock flag used by planning-aware callers."""
    return item.get("duration_locked") is True or item.get("locked") is True


def is_item_video_generated(item: Mapping[str, Any]) -> bool:
    """Detect an existing video without treating the planned duration as an actual result."""
    assets = item.get("generated_assets")
    if not isinstance(assets, Mapping):
        return False
    return bool(assets.get("video_clip") or assets.get("video_uri") or assets.get("status") == "completed")


@dataclass(frozen=True, slots=True)
class ShotDurationInput:
    """The stable planning view of one shot; this does not own persisted script data."""

    shot_id: str
    current_seconds: int | None
    supported_durations: tuple[int, ...]
    locked: bool = False
    generated: bool = False
    weight: float = 1.0

    @property
    def is_adjustable(self) -> bool:
        return not self.locked and not self.generated


@dataclass(frozen=True, slots=True)
class ShotDurationAllocation:
    """An explainable allocation, request clamp, and future actual-result slot."""

    shot_id: str
    current_seconds: int | None
    allocated_seconds: int | None
    requested_seconds: int | None
    actual_seconds: int | None
    locked: bool
    generated: bool
    clamp_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EpisodeDurationPlan:
    """An immutable preview artifact which never applies itself to a script."""

    target_seconds: int
    strategy: DurationPlanningStrategy
    allocations: tuple[ShotDurationAllocation, ...]
    source_revision: str | None = None

    @property
    def by_shot_id(self) -> dict[str, ShotDurationAllocation]:
        return {allocation.shot_id: allocation for allocation in self.allocations}


@dataclass(frozen=True, slots=True)
class DurationChange:
    """One user-confirmable change created by a duration plan."""

    shot_id: str
    from_seconds: int | None
    to_seconds: int
    clamp_reason: str | None


@dataclass(frozen=True, slots=True)
class DurationPlanPreview:
    """The diff the UI must show before a caller applies a plan."""

    target_seconds: int
    changes: tuple[DurationChange, ...]


class EpisodeDurationPlanner:
    """Deep planning module for allocating an episode target to eligible shots.

    Interface invariants:
    - locked and generated shots are retained and never appear in ``changes``;
    - the target is a planning request, not a persisted shot duration;
    - provider supported durations determine ``requested_seconds`` and are always
      accompanied by an explicit clamp reason when they differ from allocation.
    """

    def build_plan(
        self,
        *,
        target_seconds: int,
        shots: Iterable[ShotDurationInput],
        strategy: DurationPlanningStrategy = DurationPlanningStrategy.EQUAL,
        manual_allocations: Mapping[str, int] | None = None,
        source_revision: str | None = None,
    ) -> EpisodeDurationPlan:
        if target_seconds <= 0:
            raise ValueError("target_seconds must be positive")

        shot_list = tuple(shots)
        self._validate_shots(shot_list)
        adjustable = tuple(shot for shot in shot_list if shot.is_adjustable)
        fixed_total = sum((shot.current_seconds or 0) for shot in shot_list if not shot.is_adjustable)
        if target_seconds < fixed_total:
            raise ValueError("target_seconds cannot be less than the fixed shot duration total")
        remaining = target_seconds - fixed_total
        allocated = self._allocate(
            remaining=remaining,
            shots=adjustable,
            strategy=strategy,
            manual_allocations=manual_allocations or {},
        )

        allocations = tuple(self._make_allocation(shot, allocated.get(shot.shot_id)) for shot in shot_list)
        return EpisodeDurationPlan(
            target_seconds=target_seconds,
            strategy=strategy,
            allocations=allocations,
            source_revision=source_revision,
        )

    def preview_replan(
        self,
        shots: Iterable[ShotDurationInput],
        plan: EpisodeDurationPlan,
    ) -> DurationPlanPreview:
        current_by_id = {shot.shot_id: shot for shot in shots}
        changes: list[DurationChange] = []
        for allocation in plan.allocations:
            shot = current_by_id.get(allocation.shot_id)
            if shot is None or not shot.is_adjustable or allocation.requested_seconds is None:
                continue
            if shot.current_seconds != allocation.requested_seconds:
                changes.append(
                    DurationChange(
                        shot_id=shot.shot_id,
                        from_seconds=shot.current_seconds,
                        to_seconds=allocation.requested_seconds,
                        clamp_reason=allocation.clamp_reason,
                    )
                )
        return DurationPlanPreview(target_seconds=plan.target_seconds, changes=tuple(changes))

    def apply_confirmed_plan(
        self,
        shots: Iterable[ShotDurationInput],
        plan: EpisodeDurationPlan,
    ) -> dict[str, int]:
        """Return only user-confirmed, safe updates; the caller persists them atomically."""
        return {change.shot_id: change.to_seconds for change in self.preview_replan(shots, plan).changes}

    @staticmethod
    def requested_seconds_for(shot_id: str, plan: EpisodeDurationPlan) -> int | None:
        """Return the provider-ready request for one item, if the plan contains it."""
        allocation = plan.by_shot_id.get(shot_id)
        return allocation.requested_seconds if allocation is not None else None

    @staticmethod
    def _validate_shots(shots: tuple[ShotDurationInput, ...]) -> None:
        shot_ids = [shot.shot_id for shot in shots]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("shot_id values must be unique")
        for shot in shots:
            if not shot.shot_id:
                raise ValueError("shot_id is required")
            if shot.current_seconds is not None and shot.current_seconds <= 0:
                raise ValueError("current_seconds must be positive when set")
            if shot.weight <= 0:
                raise ValueError("weight must be positive")
            if not shot.supported_durations:
                raise ValueError("supported_durations must not be empty")
            if any(duration <= 0 for duration in shot.supported_durations):
                raise ValueError("supported_durations must contain positive values")

    @staticmethod
    def _allocate(
        *,
        remaining: int,
        shots: tuple[ShotDurationInput, ...],
        strategy: DurationPlanningStrategy,
        manual_allocations: Mapping[str, int],
    ) -> dict[str, int]:
        if not shots:
            return {}
        if strategy is DurationPlanningStrategy.MANUAL:
            missing = [shot.shot_id for shot in shots if shot.shot_id not in manual_allocations]
            if missing:
                raise ValueError(f"manual allocations are required for: {', '.join(missing)}")
            values = {shot.shot_id: manual_allocations[shot.shot_id] for shot in shots}
            if any(value <= 0 for value in values.values()):
                raise ValueError("manual allocations must be positive")
            return values

        weights = [1.0 if strategy is DurationPlanningStrategy.EQUAL else shot.weight for shot in shots]
        total_weight = sum(weights)
        raw = [remaining * weight / total_weight for weight in weights]
        floor_values = [int(value) for value in raw]
        leftovers = remaining - sum(floor_values)
        # Stable tie-breaking preserves script order and makes previews reproducible.
        ordered_remainders = sorted(
            range(len(shots)),
            key=lambda index: (raw[index] - floor_values[index], -index),
            reverse=True,
        )
        for index in ordered_remainders[:leftovers]:
            floor_values[index] += 1
        return {shot.shot_id: floor_values[index] for index, shot in enumerate(shots)}

    @staticmethod
    def _make_allocation(
        shot: ShotDurationInput,
        allocated_seconds: int | None,
    ) -> ShotDurationAllocation:
        if not shot.is_adjustable:
            return ShotDurationAllocation(
                shot_id=shot.shot_id,
                current_seconds=shot.current_seconds,
                allocated_seconds=shot.current_seconds,
                requested_seconds=shot.current_seconds,
                actual_seconds=None,
                locked=shot.locked,
                generated=shot.generated,
            )
        if allocated_seconds is None:
            return ShotDurationAllocation(
                shot_id=shot.shot_id,
                current_seconds=shot.current_seconds,
                allocated_seconds=None,
                requested_seconds=None,
                actual_seconds=None,
                locked=False,
                generated=False,
            )
        requested, reason = EpisodeDurationPlanner._clamp_to_supported(allocated_seconds, shot.supported_durations)
        return ShotDurationAllocation(
            shot_id=shot.shot_id,
            current_seconds=shot.current_seconds,
            allocated_seconds=allocated_seconds,
            requested_seconds=requested,
            actual_seconds=None,
            locked=False,
            generated=False,
            clamp_reason=reason,
        )

    @staticmethod
    def _clamp_to_supported(target: int, supported: tuple[int, ...]) -> tuple[int, str | None]:
        if not supported:
            return target, None
        values = tuple(sorted(set(supported)))
        if target < values[0]:
            return values[0], "provider_min_duration"
        if target > values[-1]:
            return values[-1], "provider_max_duration"
        if target in values:
            return target, None
        nearest = min(values, key=lambda value: (abs(value - target), value))
        return nearest, "nearest_supported_duration"
