"""Pure media rendering helpers for low-resolution preview generation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


class RenderToolError(RuntimeError):
    """Raised when ffmpeg or ffprobe is unavailable or rejects an input."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_tool(name: str) -> str:
    """Resolve a media tool without allowing a caller-supplied shell command."""
    path = shutil.which(name)
    if not path:
        raise RenderToolError(f"{name}_unavailable", f"{name} is not installed or is not on PATH")
    return path


def _ffconcat_quote(path: Path) -> str:
    """Quote a local path for the ffconcat demuxer without invoking a shell."""
    value = path.as_posix().replace("'", "'\\''")
    return f"file '{value}'"


def build_concat_manifest(
    timeline: list[dict[str, Any]],
    *,
    project_root: Path,
    manifest_path: Path,
) -> list[Path]:
    """Resolve timeline inputs and write a deterministic concat manifest."""
    resolved: list[Path] = []
    lines = ["ffconcat version 1.0"]
    for item in timeline:
        source_ref = item.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref.strip():
            raise RenderToolError("source_ref_invalid", "timeline source_ref must be a non-empty string")
        candidate = Path(source_ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        try:
            path = candidate.resolve(strict=True)
            path.relative_to(project_root.resolve())
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise RenderToolError("source_file_missing", f"source file is unavailable: {source_ref}") from exc
        if not path.is_file():
            raise RenderToolError("source_file_missing", f"source file is not a file: {source_ref}")
        resolved.append(path)
        lines.append(_ffconcat_quote(path))
        trim_start = item.get("trim_start_seconds", 0)
        trim_end = item.get("trim_end_seconds", 0)
        duration = item.get("duration_seconds")
        if isinstance(trim_start, (int, float)) and trim_start > 0:
            lines.append(f"inpoint {float(trim_start):.6f}")
        if isinstance(duration, (int, float)) and isinstance(trim_end, (int, float)):
            outpoint = float(duration) - float(trim_end)
            if outpoint > float(trim_start or 0):
                lines.append(f"outpoint {outpoint:.6f}")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return resolved


async def _run_process(args: list[str], *, timeout_seconds: float = 900) -> tuple[bytes, bytes]:
    """Run a media process directly with an argv list and bounded output."""
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
    config: dict[str, Any],
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
        if isinstance(config, dict):
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
    if isinstance(config, dict):
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
) -> dict[str, Any]:
    """Hard-cut timeline clips into a validated MP4 using explicit argv execution."""
    if width <= 0 or height <= 0:
        raise RenderToolError("render_dimensions_invalid", "render dimensions must be positive")
    if not 0 < crf <= 51:
        raise RenderToolError("render_quality_invalid", "CRF must be between 1 and 51")
    ffmpeg = ffmpeg_path or resolve_tool("ffmpeg")
    work_dir = output_path.parent / f".{output_path.stem}-work"
    manifest_path = work_dir / "concat.ffconcat"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        packaged_timeline = await _build_packaged_timeline(
            timeline,
            packaging=packaging,
            project_root=project_root,
            work_dir=work_dir,
            width=width,
            height=height,
            fps=float(fps or 24),
            ffmpeg=ffmpeg,
        )
        build_concat_manifest(packaged_timeline, project_root=project_root, manifest_path=manifest_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
        args = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest_path),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-vf",
            video_filter,
            "-r",
            str(fps or 24),
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
        await _run_process(args)
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
        build_subtitle_burn_in_command(ffmpeg, video_path=source, subtitle_path=subtitles, output_path=destination)
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
    "build_concat_manifest",
    "build_subtitle_burn_in_command",
    "burn_in_subtitles",
    "file_fingerprint",
    "probe_media",
    "render_low_resolution_preview",
    "render_video",
    "resolve_tool",
]
