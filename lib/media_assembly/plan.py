"""Pure domain contracts and validation for deterministic media assembly plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, TypeGuard

PLAN_STATUSES = frozenset(
    {
        "draft",
        "confirmed",
        "preview_pending",
        "preview_ready",
        "render_pending",
        "rendering",
        "completed",
        "stale",
        "failed",
    }
)

_RUNNING_STATUSES = frozenset({"preview_pending", "render_pending", "rendering"})


class AssemblyPlanValidationError(ValueError):
    """Raised when an assembly plan violates its deterministic contract."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("assembly plan validation failed")
        self.errors = errors


class AssemblyPlanTransitionError(ValueError):
    """Raised when a plan lifecycle transition is not allowed."""


_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"confirmed", "stale"}),
    "confirmed": frozenset({"draft", "preview_pending", "stale"}),
    "preview_pending": frozenset({"preview_ready", "failed", "stale"}),
    "preview_ready": frozenset({"confirmed", "render_pending", "stale"}),
    "render_pending": frozenset({"rendering", "confirmed", "stale"}),
    "rendering": frozenset({"completed", "failed", "stale"}),
    "completed": frozenset({"draft", "stale"}),
    "stale": frozenset({"draft", "confirmed"}),
    "failed": frozenset({"draft", "confirmed", "stale"}),
}


def _error(path: str, code: str, message: str) -> dict[str, str]:
    return {"path": path, "code": code, "message": message}


def _mapping(value: Any, path: str, errors: list[dict[str, Any]]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append(_error(path, "object_required", "expected an object"))
        return None
    return value


def _non_empty_string(value: Any, path: str, errors: list[dict[str, Any]]) -> bool:
    if not isinstance(value, str) or not value.strip():
        errors.append(_error(path, "string_required", "expected a non-empty string"))
        return False
    return True


def _non_negative_number(value: Any, path: str, errors: list[dict[str, Any]]) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        errors.append(_error(path, "non_negative_number_required", "expected a non-negative number"))
        return False
    return True


def _positive_number(value: Any, path: str, errors: list[dict[str, Any]]) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        errors.append(_error(path, "positive_number_required", "expected a positive number"))
        return False
    return True


def _validate_timeline(value: Any, errors: list[dict[str, Any]]) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        errors.append(_error("timeline", "list_required", "timeline must be a list"))
        return
    if not value:
        errors.append(_error("timeline", "not_empty", "timeline must contain at least one item"))
        return

    seen_ids: set[str] = set()
    seen_orders: set[int] = set()
    for index, raw_item in enumerate(value):
        path = f"timeline[{index}]"
        item = _mapping(raw_item, path, errors)
        if item is None:
            continue
        item_id = item.get("id")
        if _non_empty_string(item_id, f"{path}.id", errors):
            assert isinstance(item_id, str)
            if item_id in seen_ids:
                errors.append(_error(f"{path}.id", "duplicate", "timeline item ids must be unique"))
            seen_ids.add(item_id)
        order = item.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order < 0:
            errors.append(
                _error(f"{path}.order", "non_negative_integer_required", "order must be a non-negative integer")
            )
        elif order in seen_orders:
            errors.append(_error(f"{path}.order", "duplicate", "timeline order values must be unique"))
        else:
            seen_orders.add(order)
        _non_empty_string(item.get("kind"), f"{path}.kind", errors)
        _non_empty_string(item.get("source_ref"), f"{path}.source_ref", errors)
        duration = item.get("duration_seconds")
        if _positive_number(duration, f"{path}.duration_seconds", errors):
            assert isinstance(duration, (int, float))
            trim_start = item.get("trim_start_seconds", 0)
            trim_end = item.get("trim_end_seconds", 0)
            start_ok = _non_negative_number(trim_start, f"{path}.trim_start_seconds", errors)
            end_ok = _non_negative_number(trim_end, f"{path}.trim_end_seconds", errors)
            if start_ok and end_ok and isinstance(trim_start, (int, float)) and isinstance(trim_end, (int, float)):
                if trim_start + trim_end >= duration:
                    errors.append(_error(path, "empty_after_trim", "trimmed duration must remain positive"))
        policy = item.get("audio_policy", "duck")
        if policy not in {"keep", "duck", "mute"}:
            errors.append(
                _error(f"{path}.audio_policy", "invalid_audio_policy", "audio_policy must be keep, duck, or mute")
            )
        transition = item.get("transition")
        if transition is not None:
            transition_obj = _mapping(transition, f"{path}.transition", errors)
            if transition_obj is not None:
                _non_empty_string(transition_obj.get("type"), f"{path}.transition.type", errors)
                transition_duration = transition_obj.get("duration_seconds", 0)
                if _non_negative_number(transition_duration, f"{path}.transition.duration_seconds", errors):
                    if isinstance(duration, (int, float)) and isinstance(transition_duration, (int, float)):
                        if transition_duration >= duration:
                            errors.append(
                                _error(
                                    f"{path}.transition.duration_seconds",
                                    "transition_too_long",
                                    "transition must be shorter than the item",
                                )
                            )

    if seen_orders and seen_orders != set(range(len(value))):
        errors.append(_error("timeline", "non_contiguous_order", "timeline order must be contiguous from zero"))


def _validate_audio(value: Any, errors: list[dict[str, Any]]) -> None:
    if not isinstance(value, Mapping):
        errors.append(_error("audio", "object_required", "audio must be an object"))
        return
    tracks = value.get("tracks", [])
    if not isinstance(tracks, Sequence) or isinstance(tracks, (str, bytes, bytearray)):
        errors.append(_error("audio.tracks", "list_required", "audio.tracks must be a list"))
        return
    seen_ids: set[str] = set()
    for index, raw_track in enumerate(tracks):
        path = f"audio.tracks[{index}]"
        track = _mapping(raw_track, path, errors)
        if track is None:
            continue
        track_id = track.get("id")
        if _non_empty_string(track_id, f"{path}.id", errors):
            assert isinstance(track_id, str)
            if track_id in seen_ids:
                errors.append(_error(f"{path}.id", "duplicate", "audio track ids must be unique"))
            seen_ids.add(track_id)
        _non_empty_string(track.get("kind"), f"{path}.kind", errors)
        _non_empty_string(track.get("source_ref"), f"{path}.source_ref", errors)
        _non_negative_number(track.get("start_seconds", 0), f"{path}.start_seconds", errors)
        volume = track.get("volume", 1.0)
        if not isinstance(volume, (int, float)) or isinstance(volume, bool) or volume < 0:
            errors.append(_error(f"{path}.volume", "invalid_volume", "volume must be a non-negative number"))
        for key in ("fade_in_seconds", "fade_out_seconds"):
            _non_negative_number(track.get(key, 0), f"{path}.{key}", errors)


def _validate_subtitles(value: Any, errors: list[dict[str, Any]]) -> None:
    if not isinstance(value, Mapping):
        errors.append(_error("subtitle", "object_required", "subtitle must be an object"))
        return
    cues = value.get("cues", [])
    if not isinstance(cues, Sequence) or isinstance(cues, (str, bytes, bytearray)):
        errors.append(_error("subtitle.cues", "list_required", "subtitle.cues must be a list"))
        return
    previous_end = 0.0
    for index, raw_cue in enumerate(cues):
        path = f"subtitle.cues[{index}]"
        cue = _mapping(raw_cue, path, errors)
        if cue is None:
            continue
        _non_empty_string(cue.get("id"), f"{path}.id", errors)
        _non_empty_string(cue.get("text"), f"{path}.text", errors)
        start = cue.get("start_seconds")
        end = cue.get("end_seconds")
        start_ok = _non_negative_number(start, f"{path}.start_seconds", errors)
        end_ok = _positive_number(end, f"{path}.end_seconds", errors)
        if start_ok and end_ok and isinstance(start, (int, float)) and isinstance(end, (int, float)):
            if end <= start:
                errors.append(_error(path, "invalid_interval", "subtitle end must be after start"))
            if start < previous_end:
                errors.append(_error(path, "overlap", "subtitle cues must not overlap"))
            previous_end = max(previous_end, float(end))


def packaging_section_enabled(section: object) -> TypeGuard[Mapping[str, Any]]:
    """Return whether a packaging section participates in rendering.

    Sections are active by default; only an explicit ``enabled: false`` opts out,
    so validation, duration review, and rendering share one rule.
    """
    return isinstance(section, Mapping) and section.get("enabled") is not False


def _snapshot_source_paths(source_snapshot: Any) -> dict[str, str]:
    """Map unit ids to their media paths from a plan's source snapshot."""
    if not isinstance(source_snapshot, Mapping):
        return {}
    items = source_snapshot.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        return {}
    paths: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        unit_id = item.get("unit_id")
        source = item.get("source")
        path = source.get("path") if isinstance(source, Mapping) else None
        if isinstance(unit_id, str) and isinstance(path, str) and path.strip():
            paths[unit_id] = path
    return paths


def resolve_timeline_sources(timeline: Any, source_snapshot: Any) -> list[Any]:
    """Resolve timeline source refs that only name a source unit.

    The compact Agent contract lets a timeline item identify its clip with a bare
    ``unit_id``.  Plans persisted from that shape stored the unit id in
    ``source_ref`` instead of the manifest media path, so rendering looked for a
    file literally named after the unit.  Re-resolve those refs from the plan's
    own snapshot so stored revisions stay renderable; explicit paths are kept.
    """
    if not isinstance(timeline, list):
        return []
    paths = _snapshot_source_paths(source_snapshot)
    resolved: list[Any] = []
    for item in timeline:
        if not isinstance(item, Mapping):
            resolved.append(item)
            continue
        updated = dict(item)
        unit_id = updated.get("source_unit_id") or updated.get("unit_id")
        source_ref = updated.get("source_ref")
        path = paths.get(unit_id) if isinstance(unit_id, str) else None
        if path is not None and (not isinstance(source_ref, str) or source_ref == unit_id):
            updated["source_ref"] = path
        resolved.append(updated)
    return resolved


def _validate_packaging(value: Any, errors: list[dict[str, Any]]) -> None:
    packaging = _mapping(value, "packaging", errors)
    if packaging is None:
        return

    cover = packaging.get("cover")
    if cover is not None:
        cover_config = _mapping(cover, "packaging.cover", errors)
        if cover_config is not None and packaging_section_enabled(cover_config):
            _non_empty_string(cover_config.get("source_ref"), "packaging.cover.source_ref", errors)
            _positive_number(cover_config.get("duration_seconds"), "packaging.cover.duration_seconds", errors)
            fit = cover_config.get("fit", "cover")
            if fit not in {"cover", "contain"}:
                errors.append(_error("packaging.cover.fit", "invalid_fit", "cover fit must be cover or contain"))

    for name in ("intro", "outro"):
        section = packaging.get(name)
        if section is None:
            continue
        config = _mapping(section, f"packaging.{name}", errors)
        if config is None or not packaging_section_enabled(config):
            continue
        _non_empty_string(config.get("text"), f"packaging.{name}.text", errors)
        _positive_number(config.get("duration_seconds"), f"packaging.{name}.duration_seconds", errors)


def _validate_output_profile(value: Any, errors: list[dict[str, Any]]) -> None:
    profile = _mapping(value, "output_profile", errors)
    if profile is None:
        return
    if profile.get("format", "mp4") != "mp4":
        errors.append(_error("output_profile.format", "unsupported_format", "only mp4 output is supported"))
    for key in ("width", "height"):
        if key in profile:
            raw = profile[key]
            if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
                errors.append(_error(f"output_profile.{key}", "positive_integer_required", f"{key} must be positive"))
    if "fps" in profile:
        _positive_number(profile["fps"], "output_profile.fps", errors)


def validate_plan_document(
    *,
    source_snapshot: Any,
    timeline: Any,
    audio: Any,
    subtitle: Any,
    packaging: Any,
    output_profile: Any,
) -> dict[str, Any]:
    """Validate a plan without reading files or invoking a media tool."""
    errors: list[dict[str, Any]] = []
    _mapping(source_snapshot, "source_snapshot", errors)
    _validate_timeline(timeline, errors)
    _validate_audio(audio, errors)
    _validate_subtitles(subtitle, errors)
    _validate_packaging(packaging, errors)
    _validate_output_profile(output_profile, errors)
    result = {"valid": not errors, "errors": errors, "warnings": []}
    if errors:
        raise AssemblyPlanValidationError(errors)
    return result


def source_fingerprint(source_snapshot: Mapping[str, Any]) -> str:
    """Return a stable fingerprint for the source material represented by a plan."""
    try:
        encoded = json.dumps(source_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AssemblyPlanValidationError(
            [_error("source_snapshot", "not_json", "source_snapshot must be JSON serializable")]
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def assert_transition(current: str, target: str) -> None:
    if current not in PLAN_STATUSES or target not in PLAN_STATUSES:
        raise AssemblyPlanTransitionError(f"unknown assembly plan status: {current!r} -> {target!r}")
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise AssemblyPlanTransitionError(f"invalid assembly plan transition: {current!r} -> {target!r}")


def is_running_status(status: str) -> bool:
    return status in _RUNNING_STATUSES


__all__ = [
    "AssemblyPlanTransitionError",
    "AssemblyPlanValidationError",
    "PLAN_STATUSES",
    "assert_transition",
    "is_running_status",
    "packaging_section_enabled",
    "resolve_timeline_sources",
    "source_fingerprint",
    "validate_plan_document",
]
