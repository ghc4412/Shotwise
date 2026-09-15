"""Pure contracts and FFmpeg command construction for assembly audio."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

AudioPolicy = Literal["keep", "duck", "mute"]
AudioTrackKind = Literal["narration", "dialogue", "bgm", "user_audio"]
_AUDIO_POLICIES = frozenset({"keep", "duck", "mute"})
_AUDIO_TRACK_KINDS = frozenset({"narration", "dialogue", "bgm", "user_audio"})
_MAX_VOLUME = 4.0


class AudioMixValidationError(ValueError):
    """Raised when an audio mix document cannot be represented safely."""


@dataclass(frozen=True)
class VolumePoint:
    """A point in a piecewise-linear volume envelope."""

    time_seconds: float
    volume: float


@dataclass(frozen=True)
class AudioTrack:
    """An additional audio input placed on the assembly timeline."""

    path: Path
    kind: AudioTrackKind
    start_seconds: float = 0.0
    duration_seconds: float | None = None
    volume: float = 1.0
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0
    volume_envelope: tuple[VolumePoint, ...] = ()

    def with_path(self, path: Path) -> AudioTrack:
        """Return this track with a resolved media path."""
        return replace(self, path=path)


@dataclass(frozen=True)
class AudioMixConfig:
    """Audio policy and output-level effects for one rendered video."""

    original_policy: AudioPolicy = "duck"
    duck_volume: float = 0.35
    original_volume: float = 1.0
    duration_seconds: float | None = None
    fade_in_seconds: float = 0.0
    fade_out_seconds: float = 0.0
    volume_envelope: tuple[VolumePoint, ...] = ()


def _finite_number(value: object, *, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise AudioMixValidationError(f"{name} must be a finite number")
    return float(value)


def _non_negative(value: object, *, name: str) -> float:
    result = _finite_number(value, name=name)
    if result < 0:
        raise AudioMixValidationError(f"{name} must be non-negative")
    return result


def _volume(value: object, *, name: str) -> float:
    result = _finite_number(value, name=name)
    if result < 0 or result > _MAX_VOLUME:
        raise AudioMixValidationError(f"{name} must be between 0 and {_MAX_VOLUME:g}")
    return result


def validate_volume_envelope(points: Sequence[object], *, name: str = "volume_envelope") -> tuple[VolumePoint, ...]:
    """Validate and freeze a monotonic, bounded volume envelope."""
    previous_time = -1.0
    normalized: list[VolumePoint] = []
    for index, point in enumerate(points):
        if not isinstance(point, VolumePoint):
            raise AudioMixValidationError(f"{name}[{index}] must be a VolumePoint")
        time_seconds = _non_negative(point.time_seconds, name=f"{name}[{index}].time_seconds")
        volume = _volume(point.volume, name=f"{name}[{index}].volume")
        if time_seconds <= previous_time:
            raise AudioMixValidationError(f"{name} times must be strictly increasing")
        previous_time = time_seconds
        normalized.append(VolumePoint(time_seconds, volume))
    return tuple(normalized)


def validate_audio_mix(config: AudioMixConfig, tracks: Sequence[object]) -> None:
    """Validate policies, fades, envelopes, and track placement before execution."""
    if config.original_policy not in _AUDIO_POLICIES:
        raise AudioMixValidationError(f"unsupported original audio policy: {config.original_policy!r}")
    _volume(config.duck_volume, name="duck_volume")
    _volume(config.original_volume, name="original_volume")
    output_duration = None
    if config.duration_seconds is not None:
        output_duration = _finite_number(config.duration_seconds, name="duration_seconds")
        if output_duration <= 0:
            raise AudioMixValidationError("duration_seconds must be positive")
    fade_in = _non_negative(config.fade_in_seconds, name="fade_in_seconds")
    fade_out = _non_negative(config.fade_out_seconds, name="fade_out_seconds")
    if output_duration is not None and fade_in + fade_out > output_duration:
        raise AudioMixValidationError("output fades cannot exceed duration_seconds")
    if fade_out and output_duration is None:
        raise AudioMixValidationError("duration_seconds is required for an output fade-out")
    validate_volume_envelope(config.volume_envelope)

    for index, track in enumerate(tracks):
        if not isinstance(track, AudioTrack):
            raise AudioMixValidationError(f"tracks[{index}] must be an AudioTrack")
        if track.kind not in _AUDIO_TRACK_KINDS:
            raise AudioMixValidationError(f"unsupported audio track kind: {track.kind!r}")
        _non_negative(track.start_seconds, name=f"tracks[{index}].start_seconds")
        if track.duration_seconds is not None:
            duration = _finite_number(track.duration_seconds, name=f"tracks[{index}].duration_seconds")
            if duration <= 0:
                raise AudioMixValidationError(f"tracks[{index}].duration_seconds must be positive")
        _volume(track.volume, name=f"tracks[{index}].volume")
        track_fade_in = _non_negative(track.fade_in_seconds, name=f"tracks[{index}].fade_in_seconds")
        track_fade_out = _non_negative(track.fade_out_seconds, name=f"tracks[{index}].fade_out_seconds")
        if track.duration_seconds is not None and track_fade_in + track_fade_out > track.duration_seconds:
            raise AudioMixValidationError(f"tracks[{index}] fades cannot exceed its duration_seconds")
        if track_fade_out and track.duration_seconds is None and output_duration is None:
            raise AudioMixValidationError(f"tracks[{index}].duration_seconds is required for an audio track fade-out")
        validate_volume_envelope(track.volume_envelope, name=f"tracks[{index}].volume_envelope")


def resolve_project_media_path(project_root: Path, source: str | Path, *, require_file: bool = True) -> Path:
    """Resolve a media path only inside ``project_root``."""
    root = project_root.resolve()
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=require_file)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise AudioMixValidationError(f"media path is outside the project or unavailable: {source}") from exc
    if require_file and not resolved.is_file():
        raise AudioMixValidationError(f"media path is not a file: {source}")
    return resolved


def _volume_expression(points: Sequence[VolumePoint]) -> str | None:
    if not points:
        return None
    if len(points) == 1:
        return f"{points[0].volume:g}"
    expression = f"{points[-1].volume:g}"
    for current, following in reversed(list(zip(points, points[1:]))):
        slope = (following.volume - current.volume) / (following.time_seconds - current.time_seconds)
        segment = f"{current.volume:g}+({slope:g})*(t-{current.time_seconds:g})"
        expression = f"if(lt(t\\,{following.time_seconds:g})\\,{segment}\\,{expression})"
    return f"if(lt(t\\,{points[0].time_seconds:g})\\,{points[0].volume:g}\\,{expression})"


def _audio_chain(
    input_label: str,
    output_label: str,
    *,
    volume: float,
    fade_in_seconds: float,
    fade_out_seconds: float,
    duration_seconds: float | None,
    start_seconds: float = 0.0,
    envelope: Sequence[VolumePoint] = (),
) -> str:
    filters = [f"volume={volume:g}"]
    envelope_expression = _volume_expression(envelope)
    if envelope_expression is not None:
        filters.append(f"volume=volume='{envelope_expression}':eval=frame")
    if fade_in_seconds:
        filters.append(f"afade=t=in:st=0:d={fade_in_seconds:g}")
    if fade_out_seconds:
        if duration_seconds is None:
            raise AudioMixValidationError("duration_seconds is required for an audio fade-out")
        filters.append(f"afade=t=out:st={max(0.0, duration_seconds - fade_out_seconds):g}:d={fade_out_seconds:g}")
    if start_seconds:
        filters.append(f"adelay={round(start_seconds * 1000):g}:all=1")
    filters.append("aresample=async=1:first_pts=0")
    return f"[{input_label}]" + ",".join(filters) + f"[{output_label}]"


def build_audio_mix_command(
    ffmpeg_path: str,
    *,
    video_path: Path,
    output_path: Path,
    tracks: Sequence[AudioTrack] = (),
    config: AudioMixConfig | None = None,
    original_audio_present: bool = True,
) -> list[str]:
    """Build a shell-free FFmpeg argv for video audio mixing."""
    config = config or AudioMixConfig()
    validate_audio_mix(config, tracks)
    original_policy: AudioPolicy = config.original_policy if original_audio_present else "mute"

    args = [ffmpeg_path, "-y", "-i", str(video_path)]
    for track in tracks:
        args.extend(["-i", str(track.path)])

    chains: list[str] = []
    mix_labels: list[str] = []
    if original_audio_present and original_policy != "mute":
        chains.append(
            _audio_chain(
                "0:a:0",
                "orig",
                volume=config.duck_volume if original_policy == "duck" else config.original_volume,
                fade_in_seconds=0.0,
                fade_out_seconds=0.0,
                duration_seconds=config.duration_seconds,
            )
        )
        mix_labels.append("orig")

    for index, track in enumerate(tracks, start=1):
        duration = track.duration_seconds or config.duration_seconds
        chains.append(
            _audio_chain(
                f"{index}:a:0",
                f"track{index}",
                volume=track.volume,
                fade_in_seconds=track.fade_in_seconds,
                fade_out_seconds=track.fade_out_seconds,
                duration_seconds=duration,
                start_seconds=track.start_seconds,
                envelope=track.volume_envelope,
            )
        )
        mix_labels.append(f"track{index}")

    args.extend(["-map", "0:v:0"])
    if mix_labels:
        if len(mix_labels) == 1:
            chains.append(f"[{mix_labels[0]}]anull[aout]")
        else:
            chains.append(
                "".join(f"[{label}]" for label in mix_labels)
                + f"amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=0[aout]"
            )
        output_filters: list[str] = []
        if config.fade_in_seconds:
            output_filters.append(f"afade=t=in:st=0:d={config.fade_in_seconds:g}")
        if config.fade_out_seconds:
            if config.duration_seconds is None:
                raise AudioMixValidationError("duration_seconds is required for an output fade-out")
            output_filters.append(
                f"afade=t=out:st={max(0.0, config.duration_seconds - config.fade_out_seconds):g}:d={config.fade_out_seconds:g}"
            )
        envelope_expression = _volume_expression(config.volume_envelope)
        if envelope_expression is not None:
            output_filters.append(f"volume=volume='{envelope_expression}':eval=frame")
        if output_filters:
            chains.append("[aout]" + ",".join(output_filters) + "[mixed]")
            audio_label = "[mixed]"
        else:
            audio_label = "[aout]"
        args.extend(["-filter_complex", ";".join(chains), "-map", audio_label, "-c:a", "aac", "-b:a", "192k"])
    else:
        args.append("-an")

    args.extend(["-c:v", "copy"])
    if config.duration_seconds is not None:
        args.extend(["-t", f"{config.duration_seconds:g}"])
    args.extend(["-movflags", "+faststart", str(output_path)])
    return args


__all__ = [
    "AudioMixConfig",
    "AudioMixValidationError",
    "AudioPolicy",
    "AudioTrack",
    "AudioTrackKind",
    "VolumePoint",
    "build_audio_mix_command",
    "resolve_project_media_path",
    "validate_audio_mix",
    "validate_volume_envelope",
]
