"""Pure media rendering helpers for low-resolution preview generation."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import shutil
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.media_assembly.plan import packaging_section_enabled

ProgressCallback = Callable[[float], Awaitable[None] | None]
CancelCheck = Callable[[], Awaitable[bool] | bool]


class RenderToolError(RuntimeError):
    """Raised when ffmpeg or ffprobe is unavailable or rejects an input."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RenderCancelledError(RenderToolError):
    """Raised when a caller requests that a running media process stop."""

    def __init__(self, message: str = "media process cancelled") -> None:
        super().__init__("media_process_cancelled", message)


def resolve_tool(name: str) -> str:
    """Resolve a media tool without allowing a caller-supplied shell command."""
    path = shutil.which(name)
    if not path:
        raise RenderToolError(f"{name}_unavailable", f"{name} is not installed or is not on PATH")
    return path


@dataclass(frozen=True)
class TimelineClip:
    """A validated timeline entry resolved to a project-local media file."""

    path: Path
    start_seconds: float
    duration_seconds: float | None


def resolve_timeline_clips(timeline: list[dict[str, Any]], *, project_root: Path) -> list[TimelineClip]:
    """Resolve timeline source refs into validated clips with their play windows."""
    root = project_root.resolve()
    clips: list[TimelineClip] = []
    for item in timeline:
        source_ref = item.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise RenderToolError("source_ref_invalid", "timeline source_ref must be a non-empty string")
        candidate = Path(source_ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        try:
            path = candidate.resolve(strict=True)
            path.relative_to(root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise RenderToolError("source_file_missing", f"source file is unavailable: {source_ref}") from exc
        if not path.is_file():
            raise RenderToolError("source_file_missing", f"source file is not a file: {source_ref}")
        start = _non_negative_seconds(item.get("trim_start_seconds"))
        end = _non_negative_seconds(item.get("trim_end_seconds"))
        duration = item.get("duration_seconds")
        length: float | None = None
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            remaining = float(duration) - end - start
            if remaining > 0:
                length = remaining
        clips.append(TimelineClip(path=path, start_seconds=start, duration_seconds=length))
    return clips


def _non_negative_seconds(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return 0.0


async def _probe_clip_input(path: Path, *, ffprobe_path: str | None) -> dict[str, Any]:
    """Describe one timeline input so the filtergraph can normalise uneven sources."""
    ffprobe = ffprobe_path or resolve_tool("ffprobe")
    args = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(path),
    ]
    stdout, _ = await _run_process(args)
    try:
        probe = json.loads(stdout.decode("utf-8"))
        streams = probe.get("streams", [])
        duration = float(probe["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RenderToolError("source_probe_invalid", "ffprobe returned an invalid clip description") from exc
    return {
        "audio_present": any(stream.get("codec_type") == "audio" for stream in streams),
        "duration_seconds": duration,
    }


def _clip_length_seconds(clip: TimelineClip, probe: Mapping[str, Any]) -> float:
    """Return how long a clip plays, falling back to the probed container duration."""
    if clip.duration_seconds is not None:
        return clip.duration_seconds
    probed = probe.get("duration_seconds")
    if isinstance(probed, (int, float)) and not isinstance(probed, bool):
        return max(float(probed) - clip.start_seconds, 0.0)
    return 0.0


def build_concat_filter(
    clips: Sequence[TimelineClip],
    *,
    probes: Sequence[Mapping[str, Any]],
    width: int,
    height: int,
    fps: float,
) -> str:
    """Normalise every clip to one video/audio shape and concatenate them.

    The ffconcat demuxer requires every input to share codec parameters, so footage
    from different suppliers (mixed resolution, profile, and audio rate) corrupted the
    stream at each boundary.  Normalising each segment inside one filtergraph keeps
    heterogeneous sources renderable in a single encode.
    """
    chains: list[str] = []
    segments: list[str] = []
    for index, (clip, probe) in enumerate(zip(clips, probes, strict=True)):
        chains.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g},"
            f"format=yuv420p,setpts=PTS-STARTPTS[v{index}]"
        )
        if probe.get("audio_present"):
            chains.append(
                f"[{index}:a]aresample=48000,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
        else:
            length = _clip_length_seconds(clip, probe)
            if length <= 0:
                raise RenderToolError(
                    "source_duration_invalid",
                    f"clip duration is unknown for silent input: {clip.path.name}",
                )
            chains.append(f"anullsrc=channel_layout=stereo:sample_rate=48000:d={length:.6f}[a{index}]")
        segments.append(f"[v{index}][a{index}]")
    chains.append(f"{''.join(segments)}concat=n={len(clips)}:v=1:a=1[outv][outa]")
    return ";".join(chains)


_FFMPEG_TIME_RE = re.compile(rb"time=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


def _parse_ffmpeg_seconds(stderr: bytes) -> float | None:
    """Return the most recent ffmpeg ``time=`` position in captured output."""
    matches = _FFMPEG_TIME_RE.findall(stderr)
    if not matches:
        return None
    hours, minutes, seconds = matches[-1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


async def _drain_stream(stream: asyncio.StreamReader, sink: bytearray) -> None:
    """Drain a subprocess stream into ``sink`` as chunks arrive.

    Reading incrementally instead of a single read-to-EOF keeps the run loop
    able to observe ffmpeg progress while the subprocess is still alive.
    """
    try:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            sink.extend(chunk)
    except (asyncio.CancelledError, ValueError):
        return


async def _invoke_cancel_check(cancel_check: CancelCheck | None) -> bool:
    if cancel_check is None:
        return False
    result = cancel_check()
    if inspect.isawaitable(result):
        return bool(await result)
    return bool(result)


async def _invoke_progress(progress_callback: ProgressCallback | None, fraction: float) -> None:
    if progress_callback is None:
        return
    result = progress_callback(max(0.0, min(1.0, fraction)))
    if inspect.isawaitable(result):
        await result


async def _run_process(
    args: list[str],
    *,
    timeout_seconds: float = 900,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    total_duration_seconds: float | None = None,
    poll_interval_seconds: float = 0.5,
) -> tuple[bytes, bytes]:
    """Run a media process with an argv list, progress parsing, and cancellation.

    stdout and stderr are drained continuously so a long ffmpeg run cannot
    deadlock on a full pipe, and the most recent ``time=`` position on stderr
    is translated into a progress fraction when a total duration is known.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise RenderToolError("media_process_unavailable", str(exc)) from exc
    assert process.stdout is not None and process.stderr is not None
    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    stdout_task = asyncio.create_task(_drain_stream(process.stdout, stdout_buffer))
    stderr_task = asyncio.create_task(_drain_stream(process.stderr, stderr_buffer))
    wait_task = asyncio.create_task(process.wait())
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    last_seconds: float | None = None
    try:
        while True:
            done, _ = await asyncio.wait({wait_task}, timeout=poll_interval_seconds)
            if wait_task in done:
                break
            if await _invoke_cancel_check(cancel_check):
                process.kill()
                await process.wait()
                raise RenderCancelledError()
            if loop.time() >= deadline:
                process.kill()
                await process.wait()
                raise RenderToolError("media_process_timeout", "media process timed out")
            position = _parse_ffmpeg_seconds(bytes(stderr_buffer))
            if position is not None and position != last_seconds:
                last_seconds = position
                if total_duration_seconds and total_duration_seconds > 0:
                    await _invoke_progress(on_progress, position / total_duration_seconds)
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        stdout = bytes(stdout_buffer)
        stderr = bytes(stderr_buffer)
        final_position = _parse_ffmpeg_seconds(stderr)
        if final_position is not None and final_position != last_seconds:
            last_seconds = final_position
            if total_duration_seconds and total_duration_seconds > 0:
                await _invoke_progress(on_progress, final_position / total_duration_seconds)
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    finally:
        for task in (stdout_task, stderr_task, wait_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(wait_task, stdout_task, stderr_task, return_exceptions=True)
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-4000:]
        raise RenderToolError("media_process_failed", detail or "media process failed")
    return stdout, stderr


async def probe_media(
    media_path: Path,
    *,
    ffprobe_path: str | None = None,
    error_code: str = "render_probe_invalid",
) -> dict[str, Any]:
    """Probe a rendered media file and require one usable video stream."""
    ffprobe = ffprobe_path or resolve_tool("ffprobe")
    if not media_path.is_file() or media_path.stat().st_size <= 0:
        raise RenderToolError("render_output_missing", "rendered media file is missing")
    args = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height",
        "-of",
        "json",
        str(media_path),
    ]
    stdout, _ = await _run_process(args)
    try:
        probe = json.loads(stdout.decode("utf-8"))
        duration = float(probe["format"]["duration"])
        streams = probe.get("streams", [])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        result = {
            "duration_seconds": duration,
            "width": int(video["width"]),
            "height": int(video["height"]),
            "audio_present": any(stream.get("codec_type") == "audio" for stream in streams),
        }
    except (KeyError, TypeError, ValueError, StopIteration, json.JSONDecodeError) as exc:
        raise RenderToolError(error_code, "ffprobe returned an invalid video description") from exc
    if result["duration_seconds"] <= 0:
        raise RenderToolError(error_code, "rendered video duration must be positive")
    return result


def _packaging_project_file(project_root: Path, source_ref: object) -> Path:
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise RenderToolError("packaging_source_invalid", "packaging source_ref must be a non-empty string")
    candidate = Path(source_ref)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(project_root.resolve())
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise RenderToolError(
            "packaging_source_missing", "packaging source is outside the project or unavailable"
        ) from exc
    if not resolved.is_file():
        raise RenderToolError("packaging_source_missing", "packaging source is not a file")
    return resolved


def _ffmpeg_filter_path(path: Path) -> str:
    return path.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


async def _create_packaging_clip(
    *,
    kind: str,
    config: Mapping[str, Any],
    project_root: Path,
    work_dir: Path,
    width: int,
    height: int,
    fps: float,
    ffmpeg: str,
) -> Path:
    duration = config.get("duration_seconds")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        raise RenderToolError("packaging_duration_invalid", f"packaging {kind} duration must be positive")
    output = work_dir / f"packaged-{kind}.mp4"
    if kind == "cover":
        source = _packaging_project_file(project_root, config.get("source_ref"))
        fit = config.get("fit", "cover")
        scale = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
            if fit == "cover"
            else f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
        args = [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(source),
            "-t",
            str(float(duration)),
            "-vf",
            scale,
            "-r",
            str(fps),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
    else:
        text = config.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RenderToolError("packaging_text_invalid", f"packaging {kind} text must be non-empty")
        text_file = work_dir / f"packaged-{kind}.txt"
        text_file.write_text(text, encoding="utf-8")
        drawtext = (
            f"drawtext=textfile='{_ffmpeg_filter_path(text_file)}':fontcolor=white:fontsize={max(24, width // 18)}:"
            "x=(w-text_w)/2:y=(h-text_h)/2"
        )
        args = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:r={fps}:d={float(duration)}",
            "-vf",
            drawtext,
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
    await _run_process(args)
    if not output.is_file() or output.stat().st_size <= 0:
        raise RenderToolError("packaging_output_missing", f"ffmpeg did not produce the {kind} clip")
    return output


async def _build_packaged_timeline(
    timeline: list[dict[str, Any]],
    *,
    packaging: object,
    project_root: Path,
    work_dir: Path,
    width: int,
    height: int,
    fps: float,
    ffmpeg: str,
) -> list[dict[str, Any]]:
    if not isinstance(packaging, dict) or not packaging:
        return timeline
    result: list[dict[str, Any]] = []
    for kind in ("cover", "intro"):
        config = packaging.get(kind)
        if packaging_section_enabled(config):
            clip = await _create_packaging_clip(
                kind=kind,
                config=config,
                project_root=project_root,
                work_dir=work_dir,
                width=width,
                height=height,
                fps=fps,
                ffmpeg=ffmpeg,
            )
            result.append({"source_ref": str(clip), "duration_seconds": config["duration_seconds"]})
    result.extend(timeline)
    config = packaging.get("outro")
    if packaging_section_enabled(config):
        clip = await _create_packaging_clip(
            kind="outro",
            config=config,
            project_root=project_root,
            work_dir=work_dir,
            width=width,
            height=height,
            fps=fps,
            ffmpeg=ffmpeg,
        )
        result.append({"source_ref": str(clip), "duration_seconds": config["duration_seconds"]})
    return result


async def render_video(
    timeline: list[dict[str, Any]],
    *,
    project_root: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: float | None = None,
    preset: str = "medium",
    crf: int = 18,
    audio_bitrate: str = "192k",
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
    probe_error_code: str = "render_probe_invalid",
    packaging: object | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Hard-cut timeline clips into a validated MP4 using explicit argv execution."""
    if width <= 0 or height <= 0:
        raise RenderToolError("render_dimensions_invalid", "render dimensions must be positive")
    if not 0 < crf <= 51:
        raise RenderToolError("render_quality_invalid", "CRF must be between 1 and 51")
    ffmpeg = ffmpeg_path or resolve_tool("ffmpeg")
    frame_rate = float(fps or 24)
    work_dir = output_path.parent / f".{output_path.stem}-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        packaged_timeline = await _build_packaged_timeline(
            timeline,
            packaging=packaging,
            project_root=project_root,
            work_dir=work_dir,
            width=width,
            height=height,
            fps=frame_rate,
            ffmpeg=ffmpeg,
        )
        clips = resolve_timeline_clips(packaged_timeline, project_root=project_root)
        if not clips:
            raise RenderToolError("source_ref_invalid", "timeline must contain at least one clip")
        probes = await asyncio.gather(*(_probe_clip_input(clip.path, ffprobe_path=ffprobe_path) for clip in clips))
        total_duration = sum(_clip_length_seconds(clip, probe) for clip, probe in zip(clips, probes, strict=True))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        args = [ffmpeg, "-y"]
        for clip in clips:
            if clip.start_seconds > 0:
                args.extend(["-ss", f"{clip.start_seconds:.6f}"])
            if clip.duration_seconds is not None:
                args.extend(["-t", f"{clip.duration_seconds:.6f}"])
            args.extend(["-i", str(clip.path)])
        args.extend(
            [
                "-filter_complex",
                build_concat_filter(clips, probes=probes, width=width, height=height, fps=frame_rate),
                "-map",
                "[outv]",
                "-map",
                "[outa]",
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                audio_bitrate,
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        await _run_process(
            args,
            on_progress=on_progress,
            cancel_check=cancel_check,
            total_duration_seconds=total_duration or None,
        )
        return {
            key: value
            for key, value in (
                await probe_media(output_path, ffprobe_path=ffprobe_path, error_code=probe_error_code)
            ).items()
            if key != "audio_present"
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def render_low_resolution_preview(
    timeline: list[dict[str, Any]],
    *,
    project_root: Path,
    output_path: Path,
    width: int = 480,
    height: int = 854,
    fps: float | None = None,
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
    packaging: object | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Hard-cut timeline clips into a validated low-resolution MP4 preview."""
    return await render_video(
        timeline,
        project_root=project_root,
        output_path=output_path,
        width=width,
        height=height,
        fps=fps,
        preset="veryfast",
        crf=30,
        audio_bitrate="96k",
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        probe_error_code="preview_probe_invalid",
        packaging=packaging,
        on_progress=on_progress,
        cancel_check=cancel_check,
    )


def _resolve_project_file(project_root: Path, path: Path) -> Path:
    """Resolve an existing project-local file for a subtitle filter."""
    root = project_root.resolve()
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise RenderToolError("subtitle_file_invalid", "subtitle file is outside the project or unavailable") from exc
    if not resolved.is_file():
        raise RenderToolError("subtitle_file_invalid", "subtitle path is not a file")
    return resolved


def build_subtitle_burn_in_command(
    ffmpeg_path: str,
    *,
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
) -> list[str]:
    """Build a shell-free FFmpeg command that burns an SRT file into video."""
    subtitle_filter_path = subtitle_path.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        f"subtitles=filename='{subtitle_filter_path}'",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


async def burn_in_subtitles(
    *,
    project_root: Path,
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    ffmpeg_path: str | None = None,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    """Burn a project-local subtitle file into a video using direct argv execution."""
    source = _resolve_project_file(project_root, video_path)
    subtitles = _resolve_project_file(project_root, subtitle_path)
    destination = output_path.resolve()
    try:
        destination.relative_to(project_root.resolve())
    except ValueError as exc:
        raise RenderToolError("render_output_invalid", "render output is outside the project") from exc
    if source == destination:
        raise RenderToolError("render_output_invalid", "subtitle output must differ from input")
    destination.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_path or resolve_tool("ffmpeg")
    await _run_process(
        build_subtitle_burn_in_command(ffmpeg, video_path=source, subtitle_path=subtitles, output_path=destination),
        on_progress=on_progress,
        cancel_check=cancel_check,
    )
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RenderToolError("subtitle_output_missing", "ffmpeg did not produce a subtitled video")
    return {"output_path": destination, "size_bytes": destination.stat().st_size}


def file_fingerprint(path: Path) -> str:
    """Fingerprint an artifact by bytes for stable download validation."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "RenderToolError",
    "TimelineClip",
    "build_concat_filter",
    "resolve_timeline_clips",
    "build_subtitle_burn_in_command",
    "burn_in_subtitles",
    "file_fingerprint",
    "probe_media",
    "render_low_resolution_preview",
    "render_video",
    "resolve_tool",
]
