"""Safe execution service for deterministic audio mixing."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from lib.media_assembly.audio import (
    AudioMixConfig,
    AudioMixValidationError,
    AudioTrack,
    build_audio_mix_command,
    resolve_project_media_path,
)
from lib.media_assembly.rendering import RenderToolError, resolve_tool


async def _run_process(args: list[str], *, timeout_seconds: float = 900) -> tuple[bytes, bytes]:
    """Run FFmpeg directly with argv, never through a shell."""
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise RenderToolError("media_process_unavailable", str(exc)) from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RenderToolError("media_process_timeout", "media process timed out") from exc
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-4000:]
        raise RenderToolError("media_process_failed", detail or "media process failed")
    return stdout, stderr


def _resolve_output_path(project_root: Path, output: str | Path) -> Path:
    root = project_root.resolve()
    candidate = Path(output)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AudioMixValidationError(f"output path is outside the project: {output}") from exc
    if resolved == root:
        raise AudioMixValidationError("output path must be a file path")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


async def mix_audio(
    *,
    project_root: Path,
    video_path: str | Path,
    output_path: str | Path,
    tracks: Sequence[AudioTrack] = (),
    config: AudioMixConfig | None = None,
    original_audio_present: bool = True,
    ffmpeg_path: str | None = None,
    timeout_seconds: float = 900,
) -> dict[str, object]:
    """Mix narration/dialogue/BGM into a project video and return artifact metadata."""
    source = resolve_project_media_path(project_root, video_path)
    destination = _resolve_output_path(project_root, output_path)
    if source == destination:
        raise AudioMixValidationError("output_path must differ from video_path")
    resolved_tracks = tuple(
        replace(track, path=resolve_project_media_path(project_root, track.path)) for track in tracks
    )
    ffmpeg = ffmpeg_path or resolve_tool("ffmpeg")
    args = build_audio_mix_command(
        ffmpeg,
        video_path=source,
        output_path=destination,
        tracks=resolved_tracks,
        config=config,
        original_audio_present=original_audio_present,
    )
    await _run_process(args, timeout_seconds=timeout_seconds)
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RenderToolError("audio_output_missing", "ffmpeg did not produce an audio-mixed video")
    return {"output_path": destination, "size_bytes": destination.stat().st_size, "command": args}


__all__ = ["mix_audio"]
