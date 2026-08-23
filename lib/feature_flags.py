"""Environment-backed rollout flags for the creation platform surfaces."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock

_FLAG_NAME_RE = re.compile(r"[^A-Za-z0-9]+")
_ENV_NAMES: Mapping[str, str] = {
    "official_creation_skills": "SHOTWISE_FEATURE_OFFICIAL_CREATION_SKILLS",
    "media_asset_index": "SHOTWISE_MEDIA_ASSET_INDEX",
    "media_library": "SHOTWISE_FEATURE_MEDIA_LIBRARY",
    "creation_plan": "SHOTWISE_FEATURE_CREATION_PLAN",
    "creative_board": "SHOTWISE_FEATURE_CREATIVE_BOARD",
    "context_agent": "SHOTWISE_FEATURE_CONTEXT_AGENT",
}
_DEFAULTS: Mapping[str, bool] = {
    "official_creation_skills": True,
    "media_asset_index": False,
    "media_library": True,
    "creation_plan": True,
    "creative_board": True,
    "context_agent": True,
}
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_CREATION_METRIC_EVENTS = frozenset(
    {
        "skill_open",
        "skill_preview",
        "skill_start",
        "skill_success",
        "skill_failure",
        "skill_cancel",
        "skill_incompatible",
    }
)
_CREATION_METRIC_OUTCOMES = frozenset(
    {"completed", "failed", "cancelled", "incompatible", "alternative_skill", "new_project", "dismissed"}
)
_CREATION_METRIC_RESOURCE_TYPES = frozenset(
    {"manuscript", "character", "scene", "prop", "product", "episode", "shot", "image", "video", "audio"}
)
_creation_metric_lock = Lock()
_creation_metric_counts: Counter[tuple[str, str, str, str, str, str]] = Counter()


@dataclass(frozen=True, slots=True)
class _FlagState:
    enabled: bool
    source: str
    valid: bool


def _read_state(normalized: str) -> _FlagState:
    raw = os.environ.get(_ENV_NAMES[normalized])
    if raw is None:
        return _FlagState(_DEFAULTS[normalized], "default", True)

    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return _FlagState(True, "environment", True)
    if value in _FALSE_VALUES:
        return _FlagState(False, "environment", True)

    # A malformed rollout value must never enable a feature accidentally.
    return _FlagState(False, "invalid", False)


def _normalize_name(name: str) -> str:
    normalized = _FLAG_NAME_RE.sub("_", name.strip().lower()).strip("_")
    if normalized not in _ENV_NAMES:
        raise ValueError(f"unknown feature flag: {name}")
    return normalized


def feature_enabled(name: str, *, default: bool | None = None) -> bool:
    """Read one rollout flag without exposing arbitrary environment variables."""

    normalized = _normalize_name(name)
    state = _read_state(normalized)
    if state.source == "default" and default is not None:
        return default
    return state.enabled


def validate_rollout_configuration() -> dict[str, object]:
    """Validate rollout environment configuration without exposing raw values."""

    known_names = set(_ENV_NAMES.values())
    errors: list[str] = []
    flags: dict[str, dict[str, object]] = {}

    for env_name in sorted(os.environ):
        if (
            env_name.startswith("SHOTWISE_FEATURE_") or env_name == "SHOTWISE_MEDIA_ASSET_INDEX"
        ) and env_name not in known_names:
            errors.append(f"unknown feature flag environment variable: {env_name}")

    for flag_name in _ENV_NAMES:
        state = _read_state(flag_name)
        flags[flag_name] = {
            "enabled": state.enabled,
            "source": state.source,
            "valid": state.valid,
        }
        if not state.valid:
            errors.append(f"invalid boolean for {_ENV_NAMES[flag_name]}")

    return {"valid": not errors, "errors": errors, "flags": flags}


def feature_snapshot() -> dict[str, bool]:
    """Return the public, non-secret rollout state for the frontend."""

    return {name: feature_enabled(name) for name in _ENV_NAMES}


def feature_audit_snapshot() -> dict[str, object]:
    """Return non-secret rollout configuration diagnostics.

    Raw environment values are deliberately excluded. Invalid values fail closed
    and are represented only by their known flag name and validity state.
    """

    flags = {
        name: {
            "enabled": state.enabled,
            "source": state.source,
            "valid": state.valid,
        }
        for name in _ENV_NAMES
        for state in (_read_state(name),)
    }
    invalid_flags = sorted(name for name, state in flags.items() if not state["valid"])
    return {
        "flags": flags,
        "invalid_flags": invalid_flags,
        "invalid_count": len(invalid_flags),
    }


def _safe_metric_value(value: str | None, *, allowed: frozenset[str] | None = None) -> str:
    """Normalize a metric dimension without accepting arbitrary user content."""

    if value is None:
        return ""
    normalized = value.strip().lower()
    if len(normalized) > 80 or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-:." for char in normalized):
        return ""
    if allowed is not None and normalized not in allowed:
        return ""
    return normalized


def _safe_rollout_dimension(
    value: str | None,
    *,
    field: str,
    allowed: frozenset[str] | None = None,
) -> str:
    """Accept only categorical metric dimensions, never free-form content or paths."""

    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if len(raw) > 80 or any(not (character.isalnum() or character in "._:-") for character in raw):
        return ""
    normalized = _safe_metric_value(raw, allowed=allowed)
    if not normalized or (allowed is not None and normalized not in allowed):
        return ""
    return normalized


def record_creation_metric(
    event: str,
    *,
    creation_skill_version_id: str | None = None,
    project_generation_mode: str | None = None,
    resource_type: str | None = None,
    reason: str | None = None,
    outcome: str | None = None,
) -> None:
    """Record one coarse, process-local creation rollout event.

    Only bounded categorical dimensions are retained. In particular, callers must
    not pass manuscript text, prompts, paths, asset IDs, or other content-bearing
    values. The process-local store is intentionally a rollout diagnostic rather
    than a durable product analytics system.
    """

    event_name = _safe_metric_value(event, allowed=_CREATION_METRIC_EVENTS)
    if not event_name:
        raise ValueError(f"unknown creation metric event: {event}")
    dimensions = (
        event_name,
        _safe_rollout_dimension(creation_skill_version_id, field="creation_skill_version_id"),
        _safe_rollout_dimension(project_generation_mode, field="project_generation_mode"),
        _safe_rollout_dimension(resource_type, field="resource_type", allowed=_CREATION_METRIC_RESOURCE_TYPES),
        _safe_rollout_dimension(reason, field="reason"),
        _safe_rollout_dimension(outcome, field="outcome", allowed=_CREATION_METRIC_OUTCOMES),
    )
    with _creation_metric_lock:
        _creation_metric_counts[dimensions] += 1


def creation_metric_snapshot() -> dict[str, object]:
    """Return aggregated non-sensitive creation rollout metrics."""

    with _creation_metric_lock:
        rows = [
            {
                "event": event,
                "creation_skill_version_id": skill,
                "project_generation_mode": generation_mode,
                "resource_type": resource_type,
                "reason": reason,
                "outcome": outcome,
                "count": count,
            }
            for (event, skill, generation_mode, resource_type, reason, outcome), count in sorted(
                _creation_metric_counts.items()
            )
        ]
    return {"items": rows}


def reset_creation_metrics() -> None:
    """Clear process-local rollout metrics for tests and controlled resets."""

    with _creation_metric_lock:
        _creation_metric_counts.clear()
