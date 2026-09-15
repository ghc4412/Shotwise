"""Deterministic subtitle cue validation and SRT/VTT serialization."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


class SubtitleValidationError(ValueError):
    """Raised when subtitle cues are invalid or unsafe to serialize."""


@dataclass(frozen=True)
class SubtitleCue:
    """A timed subtitle cue in seconds."""

    start_seconds: float
    end_seconds: float
    text: str
    identifier: str | None = None


def _time(value: object, *, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise SubtitleValidationError(f"{name} must be a finite number")
    result = float(value)
    if result < 0:
        raise SubtitleValidationError(f"{name} must be non-negative")
    return result


def _cue_from_value(value: object, index: int) -> SubtitleCue:
    if isinstance(value, SubtitleCue):
        raw_start: object = value.start_seconds
        raw_end: object = value.end_seconds
        raw_text: object = value.text
        raw_identifier: object = value.identifier
    elif isinstance(value, Mapping):
        try:
            raw_start = value["start_seconds"]
            raw_end = value["end_seconds"]
            raw_text = value["text"]
            raw_identifier = value.get("identifier")
        except KeyError as exc:
            raise SubtitleValidationError(f"cues[{index}] is missing {exc.args[0]}") from exc
    else:
        raise SubtitleValidationError(f"cues[{index}] must be a SubtitleCue or object")

    start = _time(raw_start, name=f"cues[{index}].start_seconds")
    end = _time(raw_end, name=f"cues[{index}].end_seconds")
    if end <= start:
        raise SubtitleValidationError(f"cues[{index}].end_seconds must be greater than start_seconds")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise SubtitleValidationError(f"cues[{index}].text must be a non-empty string")
    if "\x00" in raw_text:
        raise SubtitleValidationError(f"cues[{index}].text must not contain NUL")
    if raw_identifier is not None and (not isinstance(raw_identifier, str) or not raw_identifier.strip()):
        raise SubtitleValidationError(f"cues[{index}].identifier must be a non-empty string when provided")
    normalized_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    return SubtitleCue(start, end, normalized_text, raw_identifier)


def normalize_cues(cues: Iterable[SubtitleCue | Mapping[str, object]]) -> tuple[SubtitleCue, ...]:
    """Validate cues and require chronological, non-overlapping ordering."""
    normalized = tuple(_cue_from_value(value, index) for index, value in enumerate(cues))
    previous_end = 0.0
    for index, cue in enumerate(normalized):
        if cue.start_seconds < previous_end:
            raise SubtitleValidationError(f"cues[{index}] overlaps the previous cue")
        previous_end = cue.end_seconds
    return normalized


def _format_timestamp(seconds: float, *, separator: str) -> str:
    total_milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"


def generate_srt(cues: Iterable[SubtitleCue | Mapping[str, object]]) -> str:
    """Serialize cues to UTF-8 SRT text with stable numbering."""
    normalized = normalize_cues(cues)
    blocks = []
    for index, cue in enumerate(normalized, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{_format_timestamp(cue.start_seconds, separator=',')} --> "
                    f"{_format_timestamp(cue.end_seconds, separator=',')}",
                    cue.text,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def generate_vtt(cues: Iterable[SubtitleCue | Mapping[str, object]]) -> str:
    """Serialize cues to WebVTT text with stable optional identifiers."""
    normalized = normalize_cues(cues)
    blocks = ["WEBVTT", ""]
    for cue in normalized:
        cue_lines: list[str] = []
        if cue.identifier is not None:
            cue_lines.append(cue.identifier)
        cue_lines.extend(
            [
                f"{_format_timestamp(cue.start_seconds, separator='.')} --> "
                f"{_format_timestamp(cue.end_seconds, separator='.')}",
                cue.text,
            ]
        )
        blocks.append("\n".join(cue_lines))
        blocks.append("")
    return "\n".join(blocks)


__all__ = [
    "SubtitleCue",
    "SubtitleValidationError",
    "generate_srt",
    "generate_vtt",
    "normalize_cues",
]
