"""Read-only director review for generated video units.

The tool performs deterministic media checks and returns sampled frames for the
agent's visual review. It deliberately does not generate, compose, or persist a
review result.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from lib.path_safety import safe_join
from lib.reference_video.ad_units import is_ad_unit_stale
from lib.script_models import resolve_content_mode
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error, validate_script_filename

_TOOL_NAME = "inspect_director_review"
_DURATION_TOLERANCE_SECONDS = 0.75
_MAX_FRAME_BYTES = 768_000
_UNIT_NUMBER_RE = re.compile(r"U(\d+)$", re.IGNORECASE)


def _finding(
    *,
    code: str,
    severity: str,
    unit_ids: list[str],
    title: str,
    reason: str,
    recommendation: str,
    action: str,
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "unit_ids": unit_ids,
        "title": title,
        "reason": reason,
        "recommendation": recommendation,
        "action": action,
        "confidence": confidence,
    }


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _relative_script_name(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        # The project metadata may contain a scripts/ prefix, but an agent may
        # only select a validated script filename, never an arbitrary path.
        return validate_script_filename(Path(value).name)
    except ValueError:
        return None


def _script_candidates(project: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    episodes = project.get("episodes")
    if not isinstance(episodes, list):
        return candidates
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        name = _relative_script_name(episode.get("script_file"))
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def _episode_meta(project: dict[str, Any], script_name: str) -> dict[str, Any]:
    episodes = project.get("episodes")
    if not isinstance(episodes, list):
        return {}
    for episode in episodes:
        if isinstance(episode, dict) and _relative_script_name(episode.get("script_file")) == script_name:
            return episode
    return {}


def _choose_script(project: dict[str, Any], requested: Any) -> str:
    if requested is not None:
        if not isinstance(requested, str):
            raise ValueError("script 必须是纯文件名字符串")
        return validate_script_filename(requested)

    candidates = _script_candidates(project)
    for key in ("current_episode", "active_episode", "selected_episode"):
        selected = project.get(key)
        if isinstance(selected, int) and not isinstance(selected, bool):
            for name in candidates:
                if _episode_meta(project, name).get("episode") == selected:
                    return name
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        raise ValueError("无法确定当前剧集，请传入 script（例如 episode_1.json）")
    raise FileNotFoundError("project.json 中没有可用的 episodes[].script_file")


def _item_collection(script: dict[str, Any], project: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    content_mode = resolve_content_mode(script, project)
    generation_mode = project.get("generation_mode")
    if generation_mode == "reference_video":
        key = "reference_units" if content_mode == "ad" else "video_units"
    elif content_mode == "ad":
        key = "shots"
    elif content_mode == "drama":
        key = "scenes"
    else:
        key = "segments"
    raw = script.get(key)
    return key, [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _item_id(item: dict[str, Any]) -> str | None:
    for key in ("unit_id", "scene_id", "segment_id", "shot_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _planned_duration(item: dict[str, Any]) -> float | None:
    for key in ("duration_seconds", "duration"):
        value = _as_number(item.get(key))
        if value is not None and value >= 0:
            return value
    return None


def _item_text(item: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    shots = item.get("shots")
    if isinstance(shots, list):
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            for key in ("video_prompt", "image_prompt", "text", "action", "camera_language"):
                value = shot.get(key)
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
                    break
    for key in ("video_prompt", "image_prompt", "text", "action", "camera_language"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    return texts


def _references(item: dict[str, Any]) -> list[dict[str, str]]:
    raw = item.get("references")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for reference in raw:
        if not isinstance(reference, dict) or not reference.get("name"):
            continue
        result.append({"type": str(reference.get("type", "")), "name": str(reference["name"])})
    return result


def _video_path(project_path: Path, item: dict[str, Any]) -> tuple[Path | None, str | None]:
    assets = item.get("generated_assets")
    if not isinstance(assets, dict):
        return None, None
    clip = assets.get("video_clip")
    if not isinstance(clip, str) or not clip.strip():
        return None, None
    relative = clip.replace("\\", "/")
    return safe_join(project_path, clip), relative


async def _probe_media(path: Path) -> dict[str, Any]:
    available = shutil.which("ffprobe") is not None
    result: dict[str, Any] = {
        "exists": path.is_file(),
        "readable": path.is_file(),
        "probe_available": available,
        "has_video_stream": None,
        "has_audio_stream": None,
        "duration_seconds": None,
        "width": None,
        "height": None,
    }
    if not path.is_file():
        return result
    if not available:
        result["readable"] = None
        result["error"] = "ffprobe 不可用，已跳过媒体元数据探测"
        return result

    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
    except (OSError, subprocess.SubprocessError) as exc:
        result.update({"readable": False, "error": f"ffprobe 执行失败: {type(exc).__name__}"})
        return result
    if process.returncode != 0:
        result.update({"readable": False, "error": "视频文件无法读取"})
        return result
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        result.update({"readable": False, "error": "ffprobe 返回了无效结果"})
        return result

    streams = payload.get("streams", []) if isinstance(payload, dict) else []
    streams = streams if isinstance(streams, list) else []
    video = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"), None
    )
    audio = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"), None
    )
    fmt = payload.get("format", {}) if isinstance(payload, dict) else {}
    duration = _as_number(fmt.get("duration")) if isinstance(fmt, dict) else None
    result.update(
        {
            "has_video_stream": video is not None,
            "has_audio_stream": audio is not None,
            "duration_seconds": duration,
            "width": video.get("width") if isinstance(video, dict) else None,
            "height": video.get("height") if isinstance(video, dict) else None,
        }
    )
    return result


async def _extract_frame(path: Path, timestamp: float, directory: Path, name: str) -> bytes | None:
    if shutil.which("ffmpeg") is None:
        return None
    output = directory / f"{name}.jpg"
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, timestamp):.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "image2",
            "-q:v",
            "4",
            str(output),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()
    except (OSError, subprocess.SubprocessError):
        return None
    if process.returncode != 0 or not output.is_file():
        return None
    try:
        data = output.read_bytes()
    except OSError:
        return None
    if not data or len(data) > _MAX_FRAME_BYTES:
        return None
    return data


def _item_assets(item: dict[str, Any]) -> dict[str, Any]:
    assets = item.get("generated_assets")
    return assets if isinstance(assets, dict) else {}


async def _review_item(
    *,
    project_path: Path,
    project: dict[str, Any],
    script: dict[str, Any],
    item: dict[str, Any],
    include_frames: bool,
    include_short_samples: bool,
    sampling: str,
    is_ad: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[str, str, bytes]]]:
    item_id = _item_id(item) or "unknown"
    assets = _item_assets(item)
    planned = _planned_duration(item)
    findings: list[dict[str, Any]] = []
    status = "keep"
    frames: list[dict[str, Any]] = []
    frame_data: list[tuple[str, str, bytes]] = []

    if assets.get("status") == "failed":
        status = "technical_error"
        findings.append(
            _finding(
                code="generation_failed",
                severity="blocker",
                unit_ids=[item_id],
                title="视频单元生成失败",
                reason="generated_assets.status 标记为 failed。",
                recommendation="确认失败原因后仅重生成该视频单元。",
                action="regenerate",
            )
        )

    try:
        video, relative_path = _video_path(project_path, item)
    except (OSError, ValueError) as exc:
        video, relative_path = None, None
        status = "technical_error"
        findings.append(
            _finding(
                code="video_unreadable",
                severity="blocker",
                unit_ids=[item_id],
                title="视频路径不安全或不可读",
                reason=f"video_clip 未能解析: {type(exc).__name__}。",
                recommendation="修复该单元的视频产物路径后再审阅。",
                action="technical_error",
            )
        )

    if video is None:
        if status == "keep":
            status = "missing"
        findings.append(
            _finding(
                code="video_missing",
                severity="blocker",
                unit_ids=[item_id],
                title="缺少视频片段",
                reason="该单元没有 generated_assets.video_clip。",
                recommendation="补齐该镜头的视频单元后再进行最终合成。",
                action="missing",
            )
        )
        media: dict[str, Any] = {
            "exists": False,
            "readable": False,
            "probe_available": shutil.which("ffprobe") is not None,
        }
    else:
        media = await _probe_media(video)
        if media.get("exists") is False:
            if status == "keep":
                status = "missing"
            findings.append(
                _finding(
                    code="video_missing",
                    severity="blocker",
                    unit_ids=[item_id],
                    title="视频文件不存在",
                    reason=f"记录路径 {relative_path} 没有对应文件。",
                    recommendation="补齐或重生成该视频单元。",
                    action="missing",
                )
            )
        elif media.get("probe_available") is False:
            if status == "keep":
                status = "manual_review"
            findings.append(
                _finding(
                    code="probe_unavailable",
                    severity="info",
                    unit_ids=[item_id],
                    title="无法探测视频元数据",
                    reason="当前环境没有 ffprobe；文件存在但无法确认时长和音视频流。",
                    recommendation="安装 ffmpeg/ffprobe 后重新审阅，或由导演手动确认。",
                    action="manual_review",
                    confidence=0.5,
                )
            )
        elif media.get("readable") is False:
            status = "technical_error"
            findings.append(
                _finding(
                    code="video_unreadable",
                    severity="blocker",
                    unit_ids=[item_id],
                    title="视频文件不可读",
                    reason=str(media.get("error") or "媒体探测失败。"),
                    recommendation="先修复或重新生成该视频片段。",
                    action="regenerate",
                )
            )
        elif media.get("has_video_stream") is False:
            status = "technical_error"
            findings.append(
                _finding(
                    code="video_unreadable",
                    severity="blocker",
                    unit_ids=[item_id],
                    title="视频没有视频流",
                    reason="媒体文件存在，但 ffprobe 没有发现视频流。",
                    recommendation="重新生成该片段。",
                    action="regenerate",
                )
            )

        actual = _as_number(media.get("duration_seconds"))
        if planned is not None and actual is not None and abs(planned - actual) > _DURATION_TOLERANCE_SECONDS:
            if status == "keep":
                status = "manual_review"
            findings.append(
                _finding(
                    code="duration_mismatch",
                    severity="high",
                    unit_ids=[item_id],
                    title="成片时长与规划不一致",
                    reason=f"规划 {planned:g}s，媒体 {actual:g}s。",
                    recommendation="确认节奏是否可接受；必要时只重生成该片段。",
                    action="manual_review",
                )
            )
        if media.get("has_audio_stream") is False:
            findings.append(
                _finding(
                    code="audio_missing_info",
                    severity="info",
                    unit_ids=[item_id],
                    title="视频没有音频流",
                    reason="当前阶段只记录为信息项，不阻断导演审阅。",
                    recommendation="暂不要求重生成；最终成片阶段再单独处理声音。",
                    action="keep",
                )
            )
        if is_ad and is_ad_unit_stale(script, item):
            status = "stale"
            findings.append(
                _finding(
                    code="stale_source",
                    severity="high",
                    unit_ids=[item_id],
                    title="视频片段来源已过期",
                    reason="广告 unit 的镜头或参考集已经与成片来源签名不一致。",
                    recommendation="确认修改是否有意；需要时只重生成该 unit。",
                    action="regenerate",
                )
            )

        actual = _as_number(media.get("duration_seconds"))
        if include_frames and media.get("has_video_stream") and actual is not None:
            positions: list[tuple[str, float]] = [("start", 0.0), ("middle", actual / 2)]
            if sampling == "start_middle_end":
                positions.append(("end", max(0.0, actual - 0.1)))
            if include_short_samples:
                positions.extend(
                    [("sample_25", actual * 0.25), ("sample_75", actual * 0.75), ("sample_end", max(0.0, actual - 0.2))]
                )
            seen: set[float] = set()
            with tempfile.TemporaryDirectory(prefix="shotwise-director-review-") as temp_dir:
                for position, timestamp in positions:
                    timestamp = round(max(0.0, timestamp), 3)
                    if timestamp in seen:
                        continue
                    seen.add(timestamp)
                    data = await _extract_frame(video, timestamp, Path(temp_dir), f"{item_id}-{position}")
                    frames.append({"position": position, "timestamp_seconds": timestamp, "included": data is not None})
                    if data is not None:
                        frame_data.append((item_id, position, data))

    result = {
        "unit_id": item_id,
        "planned_duration_seconds": planned,
        "shots": _item_text(item),
        "references": _references(item),
        "generated_status": assets.get("status", "pending"),
        "review_status": status,
        "video_path": relative_path,
        "media_probe": media,
        "frames": frames,
        "deterministic_findings": findings,
    }
    return result, findings, frame_data


def _sequence_findings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids: list[str] = []
    for item in items:
        item_id = item.get("unit_id")
        if isinstance(item_id, str):
            ids.append(item_id)
    findings: list[dict[str, Any]] = []
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        findings.append(
            _finding(
                code="duplicate_unit",
                severity="blocker",
                unit_ids=duplicates,
                title="发现重复的视频单元",
                reason=f"重复 ID：{', '.join(duplicates)}。",
                recommendation="修正剧本 unit 顺序或 ID 后再审阅。",
                action="manual_review",
            )
        )

    numbered: list[tuple[str, int]] = []
    for item_id in ids:
        match = _UNIT_NUMBER_RE.search(item_id)
        if match:
            numbered.append((item_id, int(match.group(1))))
    numbers = [number for _, number in numbered]
    if len(numbers) > 1 and numbers != sorted(numbers):
        findings.append(
            _finding(
                code="out_of_order",
                severity="high",
                unit_ids=ids,
                title="视频单元顺序异常",
                reason="unit 在剧本中的顺序与其 U 序号不一致。",
                recommendation="先确认镜头顺序，必要时调整剧本顺序，而不是直接合成。",
                action="manual_review",
            )
        )
    if numbers and min(numbers) == 1:
        missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        if missing:
            missing_ids = [f"U{number:02d}" for number in missing]
            findings.append(
                _finding(
                    code="missing_unit",
                    severity="blocker",
                    unit_ids=missing_ids,
                    title="视频单元序号存在缺口",
                    reason=f"缺少 U 序号：{', '.join(str(number) for number in missing)}。",
                    recommendation="补齐或确认缺失镜头后再进行任何合成。",
                    action="missing",
                )
            )
    return findings


async def _review_episode(
    *,
    project_path: Path,
    project: dict[str, Any],
    script_name: str,
    script: dict[str, Any],
    requested_unit_ids: set[str] | None,
    include_frames: bool,
    include_short_samples: bool,
    sampling: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[str, str, bytes]]]:
    collection_key, raw_items = _item_collection(script, project)
    selected = [item for item in raw_items if requested_unit_ids is None or _item_id(item) in requested_unit_ids]
    if requested_unit_ids is not None:
        found = {_item_id(item) for item in selected}
        selected.extend(
            {"unit_id": missing_id, "generated_assets": {}} for missing_id in sorted(requested_unit_ids - found)
        )

    is_ad = resolve_content_mode(script, project) == "ad" and project.get("generation_mode") == "reference_video"
    reviewed: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    frame_data: list[tuple[str, str, bytes]] = []
    for item in selected:
        result, item_findings, item_frames = await _review_item(
            project_path=project_path,
            project=project,
            script=script,
            item=item,
            include_frames=include_frames,
            include_short_samples=include_short_samples,
            sampling=sampling,
            is_ad=is_ad,
        )
        reviewed.append(result)
        findings.extend(item_findings)
        frame_data.extend(item_frames)

    sequence = _sequence_findings(reviewed)
    findings.extend(sequence)
    selected_ids = {item.get("unit_id") for item in reviewed}
    for finding in sequence:
        affected = set(finding["unit_ids"]) & selected_ids
        for item in reviewed:
            if item.get("unit_id") in affected:
                item.setdefault("deterministic_findings", []).append(finding)
                if item.get("review_status") == "keep":
                    item["review_status"] = "manual_review"

    planned_total = sum(_as_number(item.get("planned_duration_seconds")) or 0 for item in reviewed)
    script_duration = _as_number(script.get("duration_seconds"))
    available_total = sum(
        _as_number(item.get("media_probe", {}).get("duration_seconds")) or 0
        for item in reviewed
        if item.get("media_probe", {}).get("has_video_stream")
    )
    summary = {
        "unit_count": len(raw_items),
        "reviewed_unit_count": len(reviewed),
        "completed_count": sum(1 for item in reviewed if item.get("media_probe", {}).get("has_video_stream")),
        "missing_count": sum(1 for item in reviewed if item.get("review_status") == "missing"),
        "failed_count": sum(1 for item in reviewed if item.get("review_status") in {"technical_error", "stale"}),
        "planned_duration_seconds": round(script_duration if script_duration is not None else planned_total, 3),
        "available_duration_seconds": round(available_total, 3),
    }
    episode = {
        "script": script_name,
        "collection": collection_key,
        "summary": summary,
        "units": reviewed,
    }
    return episode, findings, frame_data


def inspect_director_review_tool(ctx: ToolContext) -> Any:
    """Create the session-bound director review tool."""

    @tool(
        _TOOL_NAME,
        "只读审阅当前项目已生成的视频单元：检查缺失、顺序、媒体可读性、时长和音频信息，并返回首帧/中帧/尾帧供导演 Skill 实际查看。不会自动重生成、合成视频或保存审阅结果。",
        {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "剧本文件名，例如 episode_1.json；scope=project 时省略。"},
                "scope": {"type": "string", "enum": ["episode", "project", "units"], "default": "episode"},
                "unit_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "scope=units 时指定要审阅的 unit。",
                },
                "include_frames": {"type": "boolean", "default": True},
                "sampling": {
                    "type": "string",
                    "enum": ["start_middle_end", "start_middle"],
                    "default": "start_middle_end",
                },
                "include_short_samples": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否额外抽取 25%、75% 和尾部短采样帧。",
                },
            },
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            scope = args.get("scope", "episode")
            if scope not in {"episode", "project", "units"}:
                raise ValueError("scope 只支持 episode、project 或 units")
            include_frames = args.get("include_frames", True)
            if not isinstance(include_frames, bool):
                raise ValueError("include_frames 必须是布尔值")
            include_short_samples = args.get("include_short_samples", False)
            if not isinstance(include_short_samples, bool):
                raise ValueError("include_short_samples 必须是布尔值")
            sampling = args.get("sampling", "start_middle_end")
            if sampling not in {"start_middle_end", "start_middle"}:
                raise ValueError("sampling 只支持 start_middle_end 或 start_middle")
            raw_unit_ids = args.get("unit_ids")
            if raw_unit_ids is not None and (
                not isinstance(raw_unit_ids, list)
                or not raw_unit_ids
                or any(not isinstance(value, str) or not value for value in raw_unit_ids)
            ):
                raise ValueError("unit_ids 必须是非空字符串数组")
            unit_ids = set(raw_unit_ids) if isinstance(raw_unit_ids, list) else None
            if scope == "units" and not unit_ids:
                raise ValueError("scope=units 时必须传入 unit_ids")
            if scope != "units" and unit_ids is not None:
                raise ValueError("只有 scope=units 时才能传 unit_ids")
            project = ctx.pm.load_project(ctx.project_name)
            project_path = ctx.project_path.resolve()
            if scope == "project":
                script_names = _script_candidates(project)
                if not script_names:
                    raise FileNotFoundError("project.json 中没有可用剧本")
            else:
                script_names = [_choose_script(project, args.get("script"))]

            episodes: list[dict[str, Any]] = []
            all_findings: list[dict[str, Any]] = []
            content: list[dict[str, Any]] = []
            for script_name in script_names:
                script = ctx.pm.load_script(ctx.project_name, script_name)
                episode, findings, frame_data = await _review_episode(
                    project_path=project_path,
                    project=project,
                    script_name=script_name,
                    script=script,
                    requested_unit_ids=unit_ids if scope == "units" else None,
                    include_frames=include_frames,
                    include_short_samples=include_short_samples,
                    sampling=sampling,
                )
                episodes.append(episode)
                all_findings.extend(findings)
                for unit_id, position, data in frame_data:
                    content.append({"type": "text", "text": f"{script_name} / {unit_id} / {position} frame"})
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": base64.b64encode(data).decode("ascii"),
                            },
                        }
                    )

            summary = {
                "episode_count": len(episodes),
                "unit_count": sum(episode["summary"]["unit_count"] for episode in episodes),
                "reviewed_unit_count": sum(episode["summary"]["reviewed_unit_count"] for episode in episodes),
                "missing_count": sum(episode["summary"]["missing_count"] for episode in episodes),
                "failed_count": sum(episode["summary"]["failed_count"] for episode in episodes),
                "planned_duration_seconds": round(
                    sum(episode["summary"]["planned_duration_seconds"] for episode in episodes), 3
                ),
                "available_duration_seconds": round(
                    sum(episode["summary"]["available_duration_seconds"] for episode in episodes), 3
                ),
            }
            result = {
                "status": "ok",
                "project": {"name": ctx.project_name},
                "scope": scope,
                "summary": summary,
                "episodes": episodes,
                "deterministic_findings": all_findings,
                "limitations": [
                    "必须由导演 Skill 实际查看返回的图像后判断镜头语言、人物/场景/道具连续性和故事节奏。",
                    "音频流缺失只记录为 info，不作为阻塞问题。",
                    "本次审阅不会合成最终视频，也不会自动重生成或保存审阅结果。",
                ],
            }
            text = f"导演审阅素材检查完成：{summary['reviewed_unit_count']} 个视频单元，发现 {len(all_findings)} 条确定性问题。请逐个查看带有 unit/位置标签的首、中、尾帧，再输出导演审阅报告。"
            return {"content": [{"type": "text", "text": text}, *content], "structured_content": result}
        except Exception as exc:  # noqa: BLE001
            return tool_error(_TOOL_NAME, exc)

    return _handler


__all__ = ["inspect_director_review_tool"]
