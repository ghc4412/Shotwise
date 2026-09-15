"""Phase 2A episode-editing MCP contracts.

This adapter persists timeline plans through the media assembly service. It
reads existing project/script/media files, but does not modify project data,
enqueue work, invoke FFmpeg, or render media.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from claude_agent_sdk import tool

import server.agent_runtime.sdk_tools.director_review as director_review
from lib.db import async_session_factory
from lib.media_assembly.plan import AssemblyPlanValidationError
from lib.script_models import resolve_content_mode
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services import media_assembly as assembly_service

CONTRACT_VERSION = "episode-editing/v1"
MANIFEST_CONTRACT_VERSION = "episode-media-manifest/v1"
PERSISTENCE_READ_ONLY = "read_only"
PERSISTENCE_DATABASE = "database"
_ALLOWED_AUDIO_POLICIES = {"duck", "mute"}
_ALLOWED_PLAN_PATCHES = {
    "director_review",
    "timeline_items",
    "audio",
    "subtitles",
    "intro",
    "outro",
    "cover",
    "render_profile",
}

# Kept as a module seam so tests and a future media service adapter can replace
# probing without changing the public MCP contract.
_probe_media = director_review._probe_media


def _result(payload: dict[str, Any], message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "structured_content": payload}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _require_plan_id(args: dict[str, Any]) -> str:
    value = args.get("plan_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("plan_id 必须是非空字符串")
    return value.strip()


def _select_script(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    project = ctx.pm.load_project(ctx.project_name)
    requested = args.get("script")
    if requested is not None and not isinstance(requested, str):
        raise ValueError("script 必须是纯文件名字符串")
    script_name = director_review._choose_script(project, requested)
    script: Any = ctx.pm.load_script(ctx.project_name, script_name)
    if not isinstance(script, dict):
        raise ValueError(f"剧本不是对象：{script_name}")
    return script_name, script, project


def _episode_number(project: dict[str, Any], script_name: str) -> int | None:
    meta = director_review._episode_meta(project, script_name)
    value = meta.get("episode")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _file_fingerprint(path: Any) -> dict[str, Any]:
    if path is None:
        return {"exists": False, "size": None, "mtime_ns": None, "sha256": None}
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False, "size": None, "mtime_ns": None, "sha256": None}
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return {"exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": None}
    return {"exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest()}


async def _build_manifest(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    script_name, script, project = _select_script(ctx, args)
    collection, raw_items = director_review._item_collection(script, project)
    project_path = ctx.project_path.resolve()
    items: list[dict[str, Any]] = []
    for order, raw_item in enumerate(raw_items, start=1):
        item_id = director_review._item_id(raw_item) or f"unknown-{order}"
        try:
            media_path, relative_path = director_review._video_path(project_path, raw_item)
        except (OSError, ValueError):
            media_path, relative_path = None, None
        if media_path is not None:
            media_probe = await _probe_media(media_path)
        else:
            media_probe = {
                "exists": False,
                "readable": False,
                "probe_available": False,
                "has_video_stream": False,
                "has_audio_stream": None,
                "duration_seconds": None,
                "width": None,
                "height": None,
            }
        items.append(
            {
                "order": order,
                "unit_id": item_id,
                "planned_duration_seconds": director_review._planned_duration(raw_item),
                "description": director_review._item_text(raw_item),
                "references": director_review._references(raw_item),
                "source": {"path": relative_path, "kind": "generated_video"},
                "asset_status": director_review._item_assets(raw_item).get("status"),
                "version": next(
                    (
                        director_review._item_assets(raw_item).get(key)
                        for key in ("version", "media_version", "video_version", "video_clip_version")
                        if director_review._item_assets(raw_item).get(key) is not None
                    ),
                    raw_item.get("version"),
                ),
                "file_fingerprint": _file_fingerprint(media_path),
                "media_probe": media_probe,
            }
        )

    fingerprint_payload = {"script": script_name, "collection": collection, "items": items}
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "contract_version": MANIFEST_CONTRACT_VERSION,
        "persistence": PERSISTENCE_READ_ONLY,
        "project_manifest": {
            "name": ctx.project_name,
            "generation_mode": project.get("generation_mode"),
            "content_mode": project.get("content_mode"),
            "current_episode": project.get("current_episode"),
            "episodes": copy.deepcopy(project.get("episodes", [])),
        },
        "script": script_name,
        "episode": _episode_number(project, script_name),
        "content_mode": resolve_content_mode(script, project),
        "generation_mode": project.get("generation_mode"),
        "collection": collection,
        "fingerprint": fingerprint,
        "items": items,
    }


def _manifest_timeline_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "order": item["order"],
            "unit_id": item["unit_id"],
            "source": copy.deepcopy(item["source"]),
            "trim": {"start_seconds": 0.0, "end_seconds": None},
            "speed": 1.0,
            "transition_to_next": "cut",
            "audio_policy": "duck",
        }
        for item in manifest["items"]
    ]


def _validate_timeline_item(item: Any, index: int) -> dict[str, Any]:
    """Normalize the compact timeline shape accepted from the Agent.

    The Agent-facing contract identifies a clip by ``unit_id`` and uses the
    array order as playback order.  Older sessions also emitted a 1-based
    ``order`` plus ``video_clip``, absolute ``start_seconds``/``end_seconds``
    and a scalar ``transition``.  Keep accepting those forms here, while the
    service adapter below emits the strict assembly-domain document.
    """
    if not isinstance(item, dict):
        raise ValueError(f"timeline_items[{index}] 必须是对象")
    unit_id = item.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id.strip():
        raise ValueError(f"timeline_items[{index}].unit_id 必须是非空字符串")

    normalized = copy.deepcopy(item)
    normalized["unit_id"] = unit_id.strip()
    # Playback order is defined by array position; expose the stable,
    # human-facing 1-based value regardless of what an older Agent emitted.
    normalized["order"] = index + 1

    if "source" not in normalized and "video_clip" in normalized:
        video_clip = normalized["video_clip"]
        if isinstance(video_clip, str) and video_clip.strip():
            normalized["source"] = {"path": video_clip.strip(), "kind": "generated_video"}

    if "trim" not in normalized and ("start_seconds" in normalized or "end_seconds" in normalized):
        normalized["trim"] = {
            "start_seconds": normalized.get("start_seconds", 0.0),
            "end_seconds": normalized.get("end_seconds"),
        }

    if "transition_to_next" not in normalized and "transition" in normalized:
        transition = normalized["transition"]
        if isinstance(transition, str):
            normalized["transition_to_next"] = transition
        elif isinstance(transition, dict):
            transition_type = transition.get("type")
            if isinstance(transition_type, str) and transition_type.strip():
                normalized["transition_to_next"] = transition_type.strip()
        else:
            raise ValueError(f"timeline_items[{index}].transition 必须是字符串或对象")

    normalized.setdefault("transition_to_next", "cut")
    normalized.setdefault("audio_policy", "duck")
    return normalized


def _assembly_validation_log(exc: AssemblyPlanValidationError) -> list[str]:
    """Render structured domain validation issues for the Agent."""
    messages: list[str] = []
    for issue in exc.errors:
        path = issue.get("path", "plan")
        code = issue.get("code", "validation_error")
        message = issue.get("message", "invalid value")
        messages.append(f"{path}: {code} - {message}")
    return messages or ["plan: validation_error - 未提供具体校验详情"]


def _normalize_audio(audio: Any) -> dict[str, Any]:
    if audio is None:
        return {"unit_audio_policy": "duck", "tracks": [], "ducking_db": -12.0}
    if not isinstance(audio, dict):
        raise ValueError("audio 必须是对象")
    result = copy.deepcopy(audio)
    policy = result.get("unit_audio_policy", "duck")
    if policy not in _ALLOWED_AUDIO_POLICIES:
        raise ValueError("audio.unit_audio_policy 只支持 duck 或 mute")
    result["unit_audio_policy"] = policy
    tracks = result.get("tracks", [])
    if not isinstance(tracks, list):
        raise ValueError("audio.tracks 必须是数组")
    result.setdefault("ducking_db", -12.0)
    return result


def _apply_patch(plan: dict[str, Any], patch: dict[str, Any]) -> None:
    unknown = set(patch) - _ALLOWED_PLAN_PATCHES
    if unknown:
        raise ValueError(f"不允许更新的 plan 字段：{sorted(unknown)}")
    for key, value in patch.items():
        if key == "timeline_items":
            if not isinstance(value, list):
                raise ValueError("timeline_items 必须是数组")
            plan[key] = [_validate_timeline_item(item, index) for index, item in enumerate(value)]
        elif key == "audio":
            plan[key] = _normalize_audio(value)
        elif key == "director_review":
            if not isinstance(value, dict):
                raise ValueError("director_review 必须是对象")
            plan[key] = copy.deepcopy(value)
        else:
            if not isinstance(value, dict):
                raise ValueError(f"{key} 必须是对象")
            plan[key] = copy.deepcopy(value)


def _normalize_plan(
    *,
    plan_id: str,
    manifest: dict[str, Any],
    director_review_result: Any,
    timeline_items: Any,
) -> dict[str, Any]:
    if timeline_items is None:
        normalized_items = _manifest_timeline_items(manifest)
    elif isinstance(timeline_items, list):
        normalized_items = [_validate_timeline_item(item, index) for index, item in enumerate(timeline_items)]
    else:
        raise ValueError("timeline_items 必须是数组")
    review = director_review_result
    if review is None:
        review = {"status": "pending", "source": "inspect_director_review", "required": True}
    if not isinstance(review, dict):
        raise ValueError("director_review 必须是对象")
    return {
        "contract_version": CONTRACT_VERSION,
        "persistence": PERSISTENCE_DATABASE,
        "plan_id": plan_id,
        "revision": 1,
        "status": "draft",
        "script": manifest["script"],
        "episode": manifest["episode"],
        "content_mode": manifest["content_mode"],
        "generation_mode": manifest["generation_mode"],
        "manifest_fingerprint": manifest["fingerprint"],
        "director_review": copy.deepcopy(review),
        "timeline_items": normalized_items,
        "audio": _normalize_audio(None),
        "subtitles": {"mode": "burn_in", "cues": [], "source": "script"},
        "intro": {"enabled": False, "kind": "title_card", "duration_seconds": 0.0},
        "outro": {"enabled": False, "kind": "end_card", "duration_seconds": 0.0},
        "cover": {"enabled": False, "source": None},
        "render_profile": {"preview": {"width": 640, "height": 360}, "final": {"width": 1920, "height": 1080}},
        "validation": None,
    }


def _validation(plan: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    review = plan.get("director_review")
    review_status = review.get("status") if isinstance(review, dict) else None
    if review_status not in {"approved", "keep"}:
        issues.append({"code": "director_review_required", "severity": "blocker", "message": "导演审阅尚未通过"})

    manifest_ids = [item["unit_id"] for item in manifest["items"]]
    timeline = plan.get("timeline_items", [])
    seen: set[str] = set()
    timeline_ids: list[str] = []
    for item in timeline if isinstance(timeline, list) else []:
        if not isinstance(item, dict):
            continue
        unit_id = item.get("unit_id")
        if not isinstance(unit_id, str):
            continue
        timeline_ids.append(unit_id)
        if unit_id in seen:
            issues.append(
                {
                    "code": "duplicate_unit_id",
                    "severity": "blocker",
                    "unit_id": unit_id,
                    "message": "时间线存在重复视频单元",
                }
            )
        seen.add(unit_id)
        if unit_id not in manifest_ids:
            issues.append(
                {
                    "code": "unit_not_in_manifest",
                    "severity": "blocker",
                    "unit_id": unit_id,
                    "message": "视频单元不属于当前媒体清单",
                }
            )
    for unit_id in manifest_ids:
        if unit_id not in seen:
            issues.append(
                {
                    "code": "unit_missing_from_plan",
                    "severity": "blocker",
                    "unit_id": unit_id,
                    "message": "媒体清单中的视频单元未加入时间线",
                }
            )
    if (
        timeline_ids
        and not any(issue["code"] == "unit_not_in_manifest" for issue in issues)
        and timeline_ids != manifest_ids
    ):
        issues.append(
            {
                "code": "order_mismatch",
                "severity": "warning",
                "message": "时间线顺序与媒体清单顺序不同，请确认是否为有意调整",
            }
        )

    for item in manifest["items"]:
        probe = item.get("media_probe") or {}
        if probe.get("has_video_stream") is not True:
            issues.append(
                {
                    "code": "media_missing_or_unreadable",
                    "severity": "blocker",
                    "unit_id": item["unit_id"],
                    "message": "视频单元缺少可用视频流",
                }
            )
    return {"valid": not any(issue["severity"] == "blocker" for issue in issues), "issues": issues}


def get_episode_media_manifest_tool(ctx: ToolContext):
    @tool(
        "get_episode_media_manifest",
        "只读获取剧集视频单元媒体清单、顺序、路径和媒体探测信息；不修改项目、不创建计划、不渲染。",
        {
            "type": "object",
            "properties": {"script": {"type": "string", "description": "剧本文件名；省略时使用当前剧集。"}},
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            manifest = await _build_manifest(ctx, args)
            return _result(manifest, f"已读取 {manifest['script']} 的 {len(manifest['items'])} 个视频单元媒体清单。")
        except Exception as exc:  # noqa: BLE001
            return tool_error("get_episode_media_manifest", exc)

    return _handler


def _service_timeline(items: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    manifest_by_id = {item["unit_id"]: item for item in manifest.get("items", []) if isinstance(item, dict)}
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        source = _as_dict(item.get("source"))
        source_ref = source.get("path") or item.get("unit_id")
        source_item = _as_dict(manifest_by_id.get(item.get("unit_id")))
        probe = _as_dict(source_item.get("media_probe"))
        duration = item.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            duration = source_item.get("planned_duration_seconds") or probe.get("duration_seconds") or 0.001
        trim = _as_dict(item.get("trim"))
        start = trim.get("start_seconds", 0.0)
        end = trim.get("end_seconds")
        end_trim = 0.0 if end is None else max(0.0, float(duration) - float(end))
        transition_name = item.get("transition_to_next", "cut")
        transition = None if transition_name == "cut" else {"type": transition_name, "duration_seconds": 0.0}
        result.append(
            {
                # The domain schema requires unique ids even when the director
                # draft intentionally contains a duplicate source unit so that
                # the MCP validation layer can report it as a review issue.
                "id": f"{item['unit_id']}:{index}",
                "source_unit_id": str(item["unit_id"]),
                "order": index,
                "kind": "video_unit",
                "source_ref": str(source_ref),
                "duration_seconds": float(duration),
                "trim_start_seconds": float(start or 0.0),
                "trim_end_seconds": end_trim,
                "audio_policy": item.get("audio_policy", "duck"),
                "transition": transition,
            }
        )
    return result


def _service_document(plan: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    packaging = {
        "director_review": copy.deepcopy(plan.get("director_review", {})),
        "intro": copy.deepcopy(plan.get("intro", {})),
        "outro": copy.deepcopy(plan.get("outro", {})),
        "cover": copy.deepcopy(plan.get("cover", {})),
    }
    render_profile = copy.deepcopy(plan.get("render_profile", {}))
    if not isinstance(render_profile, dict):
        render_profile = {"format": "mp4"}
    render_profile.setdefault("format", "mp4")
    return {
        "source_manifest": manifest,
        "timeline": _service_timeline(plan.get("timeline_items", []), manifest),
        "audio": copy.deepcopy(plan.get("audio", {})),
        "subtitle": copy.deepcopy(plan.get("subtitles", {})),
        "packaging": packaging,
        "output_profile": render_profile,
    }


def _plan_from_service(payload: dict[str, Any]) -> dict[str, Any]:
    revision = _as_dict(payload.get("current_revision"))
    source = _as_dict(revision.get("source_snapshot"))
    items = _as_list(source.get("items"))
    packaging = _as_dict(revision.get("packaging"))
    timeline = _as_list(revision.get("timeline"))
    timeline_items: list[dict[str, Any]] = []
    source_by_id = {item.get("unit_id"): item for item in items if isinstance(item, dict)}
    for index, item in enumerate(timeline):
        if not isinstance(item, dict):
            continue
        unit_id = item.get("source_unit_id") or item.get("id")
        source_item = _as_dict(source_by_id.get(unit_id))
        source_info = _as_dict(source_item.get("source"))
        transition = item.get("transition")
        transition_name = transition.get("type") if isinstance(transition, dict) else "cut"
        timeline_items.append(
            {
                "order": index + 1,
                "unit_id": unit_id,
                "source": copy.deepcopy(source_info),
                "trim": {"start_seconds": item.get("trim_start_seconds", 0.0), "end_seconds": None},
                "speed": 1.0,
                "transition_to_next": transition_name,
                "audio_policy": item.get("audio_policy", "duck"),
            }
        )
    output_profile = _as_dict(revision.get("output_profile"))
    plan = {
        "contract_version": CONTRACT_VERSION,
        "persistence": PERSISTENCE_DATABASE,
        "plan_id": payload["id"],
        "revision": payload["current_revision_number"],
        "status": payload["status"],
        "script": source.get("script"),
        "episode": payload.get("episode_number", source.get("episode")),
        "content_mode": source.get("content_mode"),
        "generation_mode": source.get("generation_mode"),
        "manifest_fingerprint": source.get("manifest_fingerprint") or revision.get("source_fingerprint"),
        "director_review": copy.deepcopy(packaging.get("director_review", {"status": "pending", "required": True})),
        "timeline_items": timeline_items,
        "audio": copy.deepcopy(revision.get("audio", {})),
        "subtitles": copy.deepcopy(revision.get("subtitle", {})),
        "intro": copy.deepcopy(packaging.get("intro", {})),
        "outro": copy.deepcopy(packaging.get("outro", {})),
        "cover": copy.deepcopy(packaging.get("cover", {})),
        "render_profile": copy.deepcopy(output_profile),
        "validation": copy.deepcopy(revision.get("validation")),
        "source_snapshot": source,
    }
    return plan


async def _commit(session: Any) -> None:
    await session.commit()


def create_timeline_plan_tool(ctx: ToolContext):
    @tool(
        "create_timeline_plan",
        "创建正式持久化的成片时间线计划；默认采用 duck 保留视频环境声，只做计划和校验前准备，不调用 FFmpeg、不渲染。",
        {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "director_review": {"type": "object"},
                "timeline_items": {"type": "array", "items": {"type": "object"}},
            },
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            manifest = await _build_manifest(ctx, args)
            draft = _normalize_plan(
                plan_id="pending",
                manifest=manifest,
                director_review_result=args.get("director_review"),
                timeline_items=args.get("timeline_items"),
            )
            document = _service_document(draft, manifest)
            async with async_session_factory() as session:
                payload = await assembly_service.create_plan(
                    session,
                    user_id=ctx.user_id,
                    project_name=ctx.project_name,
                    name=f"{manifest['script']} assembly",
                    scope="episode",
                    episode_number=manifest.get("episode"),
                    **document,
                )
                await _commit(session)
            plan = _plan_from_service(payload)
            return _result(plan, f"已创建正式时间线计划 {plan['plan_id']}（database，revision {plan['revision']}）。")
        except AssemblyPlanValidationError as exc:
            return tool_error("create_timeline_plan", exc, _assembly_validation_log(exc))
        except Exception as exc:  # noqa: BLE001
            return tool_error("create_timeline_plan", exc)

    return _handler


def get_timeline_plan_tool(ctx: ToolContext):
    @tool(
        "get_timeline_plan",
        "读取当前用户拥有的正式持久化时间线计划；不会执行渲染。",
        {
            "type": "object",
            "properties": {"plan_id": {"type": "string"}},
            "required": ["plan_id"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            plan_id = _require_plan_id(args)
            async with async_session_factory() as session:
                payload = await assembly_service.get_plan(session, plan_id, user_id=ctx.user_id)
            return _result(_plan_from_service(payload), f"已读取正式时间线计划 {plan_id}。")
        except Exception as exc:  # noqa: BLE001
            return tool_error("get_timeline_plan", exc)

    return _handler


def update_timeline_plan_tool(ctx: ToolContext):
    @tool(
        "update_timeline_plan",
        "更新正式持久化时间线计划的允许字段并创建 immutable revision；不渲染。",
        {
            "type": "object",
            "properties": {"plan_id": {"type": "string"}, "patch": {"type": "object"}},
            "required": ["plan_id", "patch"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            plan_id = _require_plan_id(args)
            patch = args.get("patch")
            if not isinstance(patch, dict) or not patch:
                raise ValueError("patch 必须是非空对象")
            manifest = await _build_manifest(ctx, {})
            async with async_session_factory() as session:
                current_payload = await assembly_service.get_plan(session, plan_id, user_id=ctx.user_id)
                current = _plan_from_service(current_payload)
                _apply_patch(current, patch)
                document = _service_document(current, manifest)
                payload = await assembly_service.create_revision(
                    session,
                    plan_id,
                    user_id=ctx.user_id,
                    expected_revision=current_payload["current_revision_number"],
                    validation_metadata=None,
                    **document,
                )
                await _commit(session)
            return _result(
                _plan_from_service(payload),
                f"已更新正式时间线计划 {plan_id}（revision {payload['current_revision_number']}）。",
            )
        except Exception as exc:  # noqa: BLE001
            return tool_error("update_timeline_plan", exc)

    return _handler


def validate_timeline_plan_tool(ctx: ToolContext):
    @tool(
        "validate_timeline_plan",
        "对正式持久化时间线计划执行确定性校验并写入新 revision：导演审阅、单元完整性、顺序、媒体可用性和音频策略；不渲染。",
        {
            "type": "object",
            "properties": {"plan_id": {"type": "string"}},
            "required": ["plan_id"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            plan_id = _require_plan_id(args)
            manifest = await _build_manifest(ctx, {})
            async with async_session_factory() as session:
                current_payload = await assembly_service.get_plan(session, plan_id, user_id=ctx.user_id)
                current = _plan_from_service(current_payload)
                validation = _validation(current, manifest)
                document = _service_document(current, manifest)
                payload = await assembly_service.create_revision(
                    session,
                    plan_id,
                    user_id=ctx.user_id,
                    expected_revision=current_payload["current_revision_number"],
                    validation_metadata=validation,
                    **document,
                )
                await _commit(session)
            result = _plan_from_service(payload)
            result["validation"] = validation
            result["status"] = "validated" if validation["valid"] else "draft"
            return _result(result, f"时间线校验完成：{'通过' if validation['valid'] else '存在阻塞问题'}。")
        except Exception as exc:  # noqa: BLE001
            return tool_error("validate_timeline_plan", exc)

    return _handler
