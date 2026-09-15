"""Pure quality checks for rendered assembly artifacts."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_SILENCE_START = re.compile(rf"silence_start:\s*(?P<start>{_NUMBER})", re.IGNORECASE)
_SILENCE_END = re.compile(
    rf"silence_end:\s*(?P<end>{_NUMBER}).*?silence_duration:\s*(?P<duration>{_NUMBER})",
    re.IGNORECASE,
)
_AUDIO_MEAN_VOLUME = re.compile(rf"mean_volume:\s*(?P<value>{_NUMBER})\s*dB", re.IGNORECASE)
_AUDIO_MAX_VOLUME = re.compile(rf"max_volume:\s*(?P<value>{_NUMBER})\s*dB", re.IGNORECASE)
_AUDIO_INTEGRATED_LUFS = re.compile(
    rf"(?:integrated\s+loudness:.*?\bI:|\bI:)\s*(?P<value>{_NUMBER})\s*LUFS",
    re.IGNORECASE | re.DOTALL,
)
_AUDIO_CLIPPED_SAMPLES = re.compile(
    rf"(?:number\s+of\s+clipped\s+samples|clipping_count|histogram_0db)\s*[:=]\s*(?P<value>{_NUMBER})",
    re.IGNORECASE,
)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _duration(value: object, *, name: str) -> float:
    result = _number(value)
    if result is None or result < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return result


def subtitle_bounds_check(
    subtitle: object,
    *,
    duration_seconds: float,
    tolerance_seconds: float = 0.05,
) -> dict[str, Any]:
    """Find subtitle cues outside the rendered duration or overlapping one another."""
    duration = _duration(duration_seconds, name="duration_seconds")
    config = subtitle if isinstance(subtitle, Mapping) else {}
    raw_cues = config.get("cues", [])
    issues: list[dict[str, Any]] = []
    if not isinstance(raw_cues, Sequence) or isinstance(raw_cues, (str, bytes, bytearray)):
        return {
            "detected": True,
            "valid": False,
            "cue_count": 0,
            "severity": "blocking",
            "items": [{"code": "cues_not_a_list", "severity": "blocking"}],
        }

    normalized: list[tuple[int, float, float]] = []
    for index, raw_cue in enumerate(raw_cues):
        cue = raw_cue if isinstance(raw_cue, Mapping) else {}
        start = _number(cue.get("start_seconds"))
        end = _number(cue.get("end_seconds"))
        cue_id = cue.get("id", cue.get("identifier"))
        base: dict[str, Any] = {"index": index}
        if isinstance(cue_id, str) and cue_id:
            base["id"] = cue_id
        if start is None or end is None:
            issues.append({**base, "code": "invalid_interval"})
            continue
        normalized.append((index, start, end))
        if start < 0 or end > duration + tolerance_seconds:
            issues.append(
                {
                    **base,
                    "code": "out_of_bounds",
                    "start_seconds": start,
                    "end_seconds": end,
                    "duration_seconds": duration,
                }
            )
        if end <= start:
            issues.append({**base, "code": "invalid_interval", "start_seconds": start, "end_seconds": end})

    ordered = sorted(normalized, key=lambda item: (item[1], item[2], item[0]))
    for previous, current in zip(ordered, ordered[1:]):
        if current[1] < previous[2]:
            issues.append(
                {
                    "code": "overlap",
                    "previous_index": previous[0],
                    "index": current[0],
                    "overlap_start_seconds": current[1],
                    "overlap_end_seconds": min(previous[2], current[2]),
                }
            )

    for issue in issues:
        issue.setdefault("severity", "blocking")
    return {
        "detected": bool(issues),
        "valid": not issues,
        "cue_count": len(raw_cues),
        "severity": "blocking" if issues else None,
        "items": issues,
    }


def parse_silencedetect_log(log: str) -> list[dict[str, float | None]]:
    """Parse FFmpeg silencedetect output into deterministic silence segments."""
    starts = list(_SILENCE_START.finditer(log))
    ends = list(_SILENCE_END.finditer(log))
    segments: list[dict[str, float | None]] = []
    end_index = 0
    for start_match in starts:
        start = float(start_match.group("start"))
        while end_index < len(ends) and float(ends[end_index].group("end")) < start:
            end_index += 1
        if end_index < len(ends):
            end_match = ends[end_index]
            end = float(end_match.group("end"))
            duration = float(end_match.group("duration"))
            if end >= start:
                segments.append(
                    {
                        "start_seconds": start,
                        "end_seconds": end,
                        "duration_seconds": duration,
                    }
                )
                end_index += 1
                continue
        segments.append({"start_seconds": start, "end_seconds": None, "duration_seconds": None})
    return segments


def parse_audio_metrics_log(log: str) -> dict[str, float | int | None]:
    """Parse FFmpeg audio-analysis output into stable loudness metrics."""
    mean_match = _AUDIO_MEAN_VOLUME.search(log)
    max_match = _AUDIO_MAX_VOLUME.search(log)
    integrated_match = _AUDIO_INTEGRATED_LUFS.search(log)
    clipped_match = _AUDIO_CLIPPED_SAMPLES.search(log)
    clipped_samples: int | None = None
    if clipped_match is not None:
        clipped_value = _number(float(clipped_match.group("value")))
        if clipped_value is not None and clipped_value >= 0:
            clipped_samples = int(clipped_value)
    return {
        "mean_volume_db": float(mean_match.group("value")) if mean_match else None,
        "max_volume_db": float(max_match.group("value")) if max_match else None,
        "integrated_lufs": float(integrated_match.group("value")) if integrated_match else None,
        "clipped_samples": clipped_samples,
    }


def audio_level_check(
    metrics: Mapping[str, object],
    *,
    target_lufs: float = -16.0,
    loudness_tolerance_lufs: float = 6.0,
    clipping_warning_db: float = -0.1,
) -> dict[str, Any]:
    """Classify loudness outside the short-form target and clipped peaks."""
    target = _number(target_lufs)
    tolerance = _number(loudness_tolerance_lufs)
    warning_threshold = _number(clipping_warning_db)
    if target is None or tolerance is None or tolerance < 0 or warning_threshold is None:
        raise ValueError("audio level thresholds must be finite numbers")

    integrated_lufs = _number(metrics.get("integrated_lufs"))
    mean_volume_db = _number(metrics.get("mean_volume_db"))
    max_volume_db = _number(metrics.get("max_volume_db"))
    clipped_samples_value = _number(metrics.get("clipped_samples"))
    clipped_samples = int(clipped_samples_value) if clipped_samples_value is not None else None
    issues: list[dict[str, Any]] = []

    if integrated_lufs is not None and not (target - tolerance <= integrated_lufs <= target + tolerance):
        issues.append(
            {
                "code": "loudness_out_of_range",
                "severity": "warning",
                "integrated_lufs": integrated_lufs,
                "target_lufs": target,
                "tolerance_lufs": tolerance,
            }
        )

    clipping_detected = clipped_samples is not None and clipped_samples > 0
    if max_volume_db is not None and max_volume_db >= 0:
        clipping_detected = True
    if clipping_detected:
        issues.append(
            {
                "code": "audio_clipping_detected",
                "severity": "blocking",
                "max_volume_db": max_volume_db,
                "clipped_samples": clipped_samples,
            }
        )
    elif max_volume_db is not None and max_volume_db >= warning_threshold:
        issues.append(
            {
                "code": "audio_peak_near_clipping",
                "severity": "warning",
                "max_volume_db": max_volume_db,
                "threshold_db": warning_threshold,
            }
        )

    severity: str | None = None
    for candidate in ("blocking", "warning"):
        if any(issue["severity"] == candidate for issue in issues):
            severity = candidate
            break
    return {
        "available": any(
            value is not None for value in (integrated_lufs, mean_volume_db, max_volume_db, clipped_samples)
        ),
        "mean_volume_db": mean_volume_db,
        "max_volume_db": max_volume_db,
        "integrated_lufs": integrated_lufs,
        "clipped_samples": clipped_samples,
        "detected": bool(issues),
        "valid": not any(issue["severity"] == "blocking" for issue in issues),
        "severity": severity,
        "issues": issues,
    }


def audio_quality_check(
    *,
    audio_stream_present: bool,
    silence_segments: Sequence[Mapping[str, object]],
    duration_seconds: float,
    long_silence_seconds: float = 5.0,
) -> dict[str, Any]:
    """Classify missing audio, long silence, and full-duration silence."""
    duration = _duration(duration_seconds, name="duration_seconds")
    segments = [dict(segment) for segment in silence_segments]
    if not audio_stream_present:
        return {
            "stream_present": False,
            "silence_segments": segments,
            "abnormal": False,
            "severity": "info",
            "issues": [{"code": "audio_stream_missing", "severity": "info"}],
        }

    full_silence = False
    long_silence = False
    for segment in segments:
        start = _number(segment.get("start_seconds"))
        end = _number(segment.get("end_seconds"))
        segment_duration = _number(segment.get("duration_seconds"))
        if segment_duration is None and start is not None:
            segment_duration = max(0.0, (end if end is not None else duration) - start)
        if segment_duration is not None and segment_duration >= long_silence_seconds:
            long_silence = True
        if start is not None and start <= 0.05 and (end is None or end >= duration - 0.05):
            full_silence = True

    severity = "blocking" if full_silence else ("warning" if long_silence else None)
    issues: list[dict[str, Any]] = []
    if full_silence:
        issues.append({"code": "audio_silence_detected", "severity": "blocking"})
    elif long_silence:
        issues.append({"code": "long_silence_detected", "severity": "warning"})
    return {
        "stream_present": True,
        "silence_segments": segments,
        "abnormal": full_silence or long_silence,
        "severity": severity,
        "issues": issues,
    }


def expected_timeline_duration(
    timeline: Sequence[Mapping[str, object]],
    packaging: object | None = None,
) -> float:
    """Calculate the expected duration of timeline content plus packaging clips."""
    total = 0.0
    for index, item in enumerate(timeline):
        duration = _duration(item.get("duration_seconds"), name=f"timeline[{index}].duration_seconds")
        trim_start = _duration(item.get("trim_start_seconds", 0), name=f"timeline[{index}].trim_start_seconds")
        trim_end = _duration(item.get("trim_end_seconds", 0), name=f"timeline[{index}].trim_end_seconds")
        effective = duration - trim_start - trim_end
        if effective < 0:
            raise ValueError(f"timeline[{index}] has negative effective duration")
        total += effective

    if isinstance(packaging, Mapping):
        for name in ("cover", "intro", "outro"):
            section = packaging.get(name)
            if isinstance(section, Mapping) and section.get("duration_seconds") is not None:
                total += _duration(section.get("duration_seconds"), name=f"packaging.{name}.duration_seconds")
    return total


def classify_black_frame_edges(
    segments: Sequence[Mapping[str, object]],
    *,
    duration_seconds: float,
    tolerance_seconds: float = 0.05,
) -> dict[str, Any]:
    """Classify black-frame segments as opening, ending, full, or middle."""
    duration = _duration(duration_seconds, name="duration_seconds")
    classified: list[dict[str, Any]] = []
    opening: list[dict[str, Any]] = []
    ending: list[dict[str, Any]] = []
    middle: list[dict[str, Any]] = []
    for raw_segment in segments:
        start = _number(raw_segment.get("start_seconds"))
        end = _number(raw_segment.get("end_seconds"))
        if start is None or end is None:
            continue
        item = dict(raw_segment)
        at_start = start <= tolerance_seconds
        at_end = end >= duration - tolerance_seconds
        edge = "full" if at_start and at_end else "opening" if at_start else "ending" if at_end else "middle"
        item["edge"] = edge
        classified.append(item)
        if edge == "opening":
            opening.append(item)
        elif edge == "ending":
            ending.append(item)
        elif edge == "middle":
            middle.append(item)

    full_duration = any(item.get("edge") == "full" for item in classified)
    blocking_segments = [item for item in classified if item["edge"] in {"full", "middle"}]
    warning_segments = [item for item in classified if item["edge"] in {"opening", "ending"}]
    severity = "blocking" if blocking_segments else ("warning" if warning_segments else None)
    return {
        "detected": bool(classified),
        "segments": classified,
        "opening_segments": opening,
        "ending_segments": ending,
        "middle_segments": middle,
        "full_duration": full_duration,
        "blocking_segments": blocking_segments,
        "warning_segments": warning_segments,
        "severity": severity,
    }


__all__ = [
    "audio_level_check",
    "audio_quality_check",
    "classify_black_frame_edges",
    "expected_timeline_duration",
    "parse_audio_metrics_log",
    "parse_silencedetect_log",
    "subtitle_bounds_check",
]
