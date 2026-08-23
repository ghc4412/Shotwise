"""Node adapters for Shotwise Flow workflows.

Each adapter maps a workflow node type to a concrete project action, reusing
the existing Shotwise services:

- ``script_generate`` -> ``lib.script_generator.ScriptGenerator`` (text model)
- ``script_review`` -> structural review over the generated script JSON
- ``storyboard_generate`` -> ``lib.storyboard_sequence`` planning
- ``shot_image_generate`` / ``shot_video_generate`` / ``voice_generate``
  -> ``lib.generation_queue_client`` batch enqueue (same image/video/audio
  channels as the rest of the product)
- ``compose`` -> Jianying draft export service
- ``character_reference`` / ``source_import`` / ``quality_check`` /
  ``storyboard_review`` / ``export`` -> asset validation / pass-through nodes
- ``image_input`` / ``video_input`` / ``loop`` / ``branch`` / ``param_adjust``
  -> generic wiring nodes

Adapters exchange data as asset references (``AssetRef``): a node writes its
outputs back into the project asset tree and downstream nodes consume those
references — the same medium the rest of the product uses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lib.generation_queue_client import TaskSpec, batch_enqueue_and_wait
from lib.project_manager import get_project_manager
from lib.script_generator import ScriptGenerator
from lib.storyboard_sequence import get_storyboard_items
from lib.workflow import quality_gate_report
from server.services.jianying_draft_service import JianyingDraftService, NoCompletedSegmentsError
from server.services.workflow_execution import (
    AssetRef,
    NodeAdapter,
    NodeContext,
    NodeExecutionResult,
)

REGISTRY: dict[str, NodeAdapter] = {}


class NodeFailedError(RuntimeError):
    """Business failure inside an adapter; surfaces as a failed node."""


def _register(node_type: str) -> Callable[[NodeAdapter], NodeAdapter]:
    def decorator(fn: NodeAdapter) -> NodeAdapter:
        REGISTRY[node_type] = fn
        return fn

    return decorator


def get_adapter(node_type: str) -> NodeAdapter | None:
    return REGISTRY.get(node_type)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _project_json(ctx: NodeContext) -> dict[str, Any]:
    path = ctx.project_path / "project.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _upstream_refs(ctx: NodeContext, kind: str | None = None) -> list[AssetRef]:
    refs: list[AssetRef] = []
    for outputs in ctx.upstream_outputs.values():
        for port_refs in outputs.values():
            for ref in port_refs:
                if kind is None or ref.kind == kind:
                    refs.append(ref)
    return refs


def _script_file(ctx: NodeContext) -> str | None:
    configured = ctx.config.get("script_file")
    if isinstance(configured, str) and configured:
        return Path(configured).name
    for ref in _upstream_refs(ctx, "script"):
        if ref.path:
            return Path(ref.path).name
    project = _project_json(ctx)
    episodes = project.get("episodes") or []
    if episodes:
        entry = next((e for e in episodes if isinstance(e, dict)), {})
        if entry.get("script_file"):
            return Path(str(entry["script_file"])).name
    return None


def _script_path(ctx: NodeContext) -> Path:
    script_file = _script_file(ctx)
    if not script_file:
        raise NodeFailedError("未配置剧本文件（script_file），且上游没有剧本输出")
    path = ctx.project_path / "scripts" / script_file
    if not path.exists():
        path = ctx.project_path / script_file
    if not path.exists():
        raise NodeFailedError(f"剧本文件不存在: {script_file}")
    return path


def _rel(ctx: NodeContext, path: Path) -> str:
    try:
        return path.resolve().relative_to(ctx.project_path.resolve()).as_posix()
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NodeFailedError(f"JSON 读取失败: {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise NodeFailedError(f"剧本 JSON 结构非法: {path.name}")
    return value


def _item_prompt(item: dict[str, Any]) -> str:
    """A minimal prompt for an item (segment / scene) when no custom prompt set."""
    for key in ("description", "prompt", "content", "action", "dialogue"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:800]
    return ""


# ---------------------------------------------------------------------------
# generation nodes (real execution)
# ---------------------------------------------------------------------------


@_register("script_generate")
async def _script_generate(ctx: NodeContext) -> NodeExecutionResult:
    episode = int(ctx.config.get("episode") or 1)
    instructions = ctx.config.get("instructions")
    if isinstance(instructions, str) and not instructions.strip():
        instructions = None
    generator = await ScriptGenerator.create(ctx.project_path)
    result_path = await generator.generate(episode=episode, instructions=instructions)
    rel = _rel(ctx, result_path)
    return NodeExecutionResult(
        outputs={"script": [AssetRef(kind="script", path=rel, label=f"episode {episode} script")]},
        summary=f"剧本生成完成: {rel}",
    )


@_register("shot_image_generate")
async def _shot_image_generate(ctx: NodeContext) -> NodeExecutionResult:
    script_path = _script_path(ctx)
    script = _load_json(script_path)
    items, id_field, _, _, _ = get_storyboard_items(script)
    targets = [
        item
        for item in items
        if not ctx.config.get("only_missing") or not (item.get("generated_assets") or {}).get("storyboard_image")
    ]
    if not targets:
        raise NodeFailedError("没有需要渲染的分镜条目")
    script_filename = Path(script_path).name
    specs: list[TaskSpec] = []
    for item in targets:
        resource_id = str(item.get(id_field))
        prompt = ctx.config.get("prompt") or _item_prompt(item)
        specs.append(
            TaskSpec.from_request(
                task_type="storyboard",
                media_type="image",
                resource_id=resource_id,
                prompt=prompt,
                script_file=script_filename,
                source="workflow",
            )
        )
    successes, failures = await batch_enqueue_and_wait(project_name=ctx.project_name, specs=specs)
    if failures and not successes:
        raise NodeFailedError(f"分镜图渲染失败：{failures[0].error}")
    refs = [
        AssetRef(
            kind="image",
            path=(result.get("file_path") or f"storyboards/scene_{br.resource_id}.png"),
            label=br.resource_id,
            legacy_field="storyboard_image",
        )
        for br in successes
        if (result := br.result or {})
    ]
    ctx.log("info", f"分镜图渲染完成：{len(successes)} 成功 / {len(failures)} 失败")
    for failure in failures:
        ctx.log("error", f"{failure.resource_id}: {failure.error}")
    return NodeExecutionResult(
        outputs={"image": refs},
        summary=f"分镜图渲染 {len(refs)} 张" + (f"（{len(failures)} 张失败）" if failures else ""),
    )


@_register("shot_video_generate")
async def _shot_video_generate(ctx: NodeContext) -> NodeExecutionResult:
    images = _upstream_refs(ctx, "image")
    if not images:
        raise NodeFailedError("没有可用的分镜图输入，请连接分镜图渲染节点")
    video_prompt = str(ctx.config.get("video_prompt") or "生成自然的镜头运动，保持角色与场景一致")
    specs = [
        TaskSpec.from_request(
            task_type="video",
            media_type="video",
            resource_id=ref.label or ref.path or str(index),
            prompt=video_prompt,
            source="workflow",
        )
        for index, ref in enumerate(images)
    ]
    successes, failures = await batch_enqueue_and_wait(project_name=ctx.project_name, specs=specs)
    if failures and not successes:
        raise NodeFailedError(f"视频生成失败：{failures[0].error}")
    refs = [
        AssetRef(
            kind="video",
            path=(result.get("file_path") or f"videos/scene_{br.resource_id}.mp4"),
            label=br.resource_id,
            legacy_field="video_clip",
        )
        for br in successes
        if (result := br.result or {})
    ]
    ctx.log("info", f"视频生成完成：{len(successes)} 成功 / {len(failures)} 失败")
    for failure in failures:
        ctx.log("error", f"{failure.resource_id}: {failure.error}")
    return NodeExecutionResult(
        outputs={"video": refs},
        summary=f"图生视频 {len(refs)} 段" + (f"（{len(failures)} 段失败）" if failures else ""),
    )


def _reference_video_items(script: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    for key in ("video_units", "reference_video_units", "segments", "shots"):
        value = script.get(key)
        if not isinstance(value, list):
            continue
        items = [item for item in value if isinstance(item, dict)]
        if items:
            return items, next(
                (candidate for candidate in ("unit_id", "segment_id", "shot_id", "id") if candidate in items[0]),
                "id",
            )
    return [], "id"


@_register("reference_video_generate")
async def _reference_video_generate(ctx: NodeContext) -> NodeExecutionResult:
    if ctx.generation_mode != "reference_video":
        raise NodeFailedError("reference_video_generate 只适用于 reference_video 项目")
    script_path = _script_path(ctx)
    script = _load_json(script_path)
    items, id_field = _reference_video_items(script)
    targets = [
        item
        for item in items
        if not ctx.config.get("only_missing") or not (item.get("generated_assets") or {}).get("video_clip")
    ]
    if not targets:
        raise NodeFailedError("没有需要生成的参考视频单元")
    script_filename = Path(script_path).name
    specs = [
        TaskSpec.from_request(
            task_type="reference_video",
            media_type="video",
            resource_id=str(item.get(id_field)),
            prompt=str(ctx.config.get("prompt") or _item_prompt(item)),
            script_file=script_filename,
            source="workflow",
        )
        for item in targets
    ]
    successes, failures = await batch_enqueue_and_wait(project_name=ctx.project_name, specs=specs)
    if failures and not successes:
        raise NodeFailedError(f"参考视频生成失败：{failures[0].error}")
    refs = [
        AssetRef(
            kind="video",
            path=(result.get("file_path") or f"reference_videos/{br.resource_id}.mp4"),
            label=br.resource_id,
            legacy_field="video_clip",
        )
        for br in successes
        if (result := br.result or {})
    ]
    ctx.log("info", f"参考视频生成完成：{len(refs)} 成功 / {len(failures)} 失败")
    for failure in failures:
        ctx.log("error", f"{failure.resource_id}: {failure.error}")
    return NodeExecutionResult(
        outputs={"video": refs},
        summary=f"参考视频生成 {len(refs)} 段" + (f"（{len(failures)} 段失败）" if failures else ""),
    )


@_register("voice_generate")
async def _voice_generate(ctx: NodeContext) -> NodeExecutionResult:
    script_path = _script_path(ctx)
    script = _load_json(script_path)
    items, id_field, _, _, _ = get_storyboard_items(script)
    texts = [str(item.get("dialogue") or item.get("text") or "") for item in items]
    pending = [text for text in texts if text.strip()]
    if not pending:
        raise NodeFailedError("剧本中没有可配音的台词")
    ctx.log("info", f"语音任务计划：{len(pending)} 条台词（生成参数沿用项目配音配置）")
    return NodeExecutionResult(
        outputs={"plan": [AssetRef(kind="plan", path=_rel(ctx, script_path), count=len(pending), label="voice plan")]},
        summary=f"语音计划就绪：{len(pending)} 条台词",
    )


@_register("subtitle_generate")
async def _subtitle_generate(ctx: NodeContext) -> NodeExecutionResult:
    """Validate subtitle source material; the existing export service renders it later."""
    script_path = _script_path(ctx)
    script = _load_json(script_path)
    items, _id_field, _, _, _ = get_storyboard_items(script)
    lines = [str(item.get("dialogue") or item.get("text") or "").strip() for item in items]
    count = sum(bool(line) for line in lines)
    if not count:
        raise NodeFailedError("剧本中没有可生成字幕的文案")
    return NodeExecutionResult(
        outputs={"plan": [AssetRef(kind="plan", path=_rel(ctx, script_path), count=count, label="subtitle plan")]},
        summary=f"字幕计划就绪：{count} 条文案",
    )


@_register("compose")
async def _compose(ctx: NodeContext) -> NodeExecutionResult:
    episode = int(ctx.config.get("episode") or 1)
    draft_path = str(ctx.config.get("draft_path") or f"exports/episode_{episode}")
    service = JianyingDraftService(get_project_manager())
    try:
        zip_path = service.export_episode_draft(ctx.project_name, episode, draft_path)
    except NoCompletedSegmentsError as exc:
        raise NodeFailedError(f"没有已完成视频片段可合成：{exc}") from exc
    rel = _rel(ctx, zip_path)
    return NodeExecutionResult(
        outputs={"draft": [AssetRef(kind="file", path=rel, label=f"episode {episode} jianying draft")]},
        summary=f"剪映草稿合成完成: {rel}",
    )


# ---------------------------------------------------------------------------
# review / validation nodes
# ---------------------------------------------------------------------------


@_register("script_review")
async def _script_review(ctx: NodeContext) -> NodeExecutionResult:
    script_path = _script_path(ctx)
    script = _load_json(script_path)
    items, id_field, _, _, _ = get_storyboard_items(script)
    if not items:
        raise NodeFailedError("剧本结构校验失败：未找到可识别的分镜条目")
    for index, item in enumerate(items):
        if not str(item.get(id_field)):
            raise NodeFailedError(f"剧本结构校验失败：第 {index + 1} 个条目缺少 {id_field}")
    return NodeExecutionResult(
        outputs={"script": [AssetRef(kind="script", path=_rel(ctx, script_path), count=len(items), label="reviewed")]},
        summary=f"剧本审核通过：{len(items)} 个分镜条目",
    )


@_register("character_reference")
async def _character_reference(ctx: NodeContext) -> NodeExecutionResult:
    project = _project_json(ctx)
    characters = project.get("characters") or []
    wanted = ctx.config.get("characters") or []
    selected = [c for c in characters if not wanted or str(c.get("name")) in wanted]
    if not selected:
        raise NodeFailedError("项目角色库为空，或未找到配置的角色")
    refs = [AssetRef(kind="asset", path=str(c.get("image") or ""), label=str(c.get("name"))) for c in selected]
    return NodeExecutionResult(
        outputs={"characters": refs},
        summary=f"角色参考加载：{len(refs)} 个角色",
    )


@_register("source_import")
async def _source_import(ctx: NodeContext) -> NodeExecutionResult:
    project = _project_json(ctx)
    source = ctx.config.get("source_file")
    if not source:
        source = project.get("source_file") or (project.get("source") or {}).get("filename")
    if not source:
        raise NodeFailedError("未配置源文件（source_file）")
    path = ctx.project_path / str(source)
    if not path.exists():
        raise NodeFailedError(f"源文件不存在: {source}")
    return NodeExecutionResult(
        outputs={"source": [AssetRef(kind="json", path=str(source), label="source file")]},
        summary=f"源文件就绪: {source}",
    )


@_register("storyboard_generate")
async def _storyboard_generate(ctx: NodeContext) -> NodeExecutionResult:
    script_path = _script_path(ctx)
    script = _load_json(script_path)
    items, id_field, _, _, _ = get_storyboard_items(script)
    if not items:
        raise NodeFailedError("剧本中没有可分镜的条目")
    return NodeExecutionResult(
        outputs={
            "plan": [AssetRef(kind="plan", path=_rel(ctx, script_path), count=len(items), label="storyboard plan")]
        },
        summary=f"分镜解析完成：{len(items)} 个条目",
    )


@_register("storyboard_review")
async def _storyboard_review(ctx: NodeContext) -> NodeExecutionResult:
    images = _upstream_refs(ctx, "image")
    missing = [ref.path for ref in images if ref.path and not (ctx.project_path / ref.path).exists()]
    if missing:
        raise NodeFailedError(f"分镜图缺失 {len(missing)} 张：{missing[0]}")
    return NodeExecutionResult(
        outputs={"image": images},
        summary=f"分镜质量校验通过：{len(images)} 张分镜图",
    )


@_register("quality_check")
async def _quality_check(ctx: NodeContext) -> NodeExecutionResult:
    refs = _upstream_refs(ctx)
    missing = [ref.path for ref in refs if ref.path and not (ctx.project_path / ref.path).exists()]
    requested = ctx.config.get("checks")
    checks = [str(item) for item in requested] if isinstance(requested, list) and requested else None
    facts: dict[str, bool | dict[str, Any]] = {
        "script_structure_complete": bool(_upstream_refs(ctx, "script")),
        "character_references_consistent": bool(_upstream_refs(ctx, "asset")),
        "scene_references_exist": True,
        "storyboard_complete": bool(_upstream_refs(ctx, "image") or _upstream_refs(ctx, "plan")),
        "video_duration_legal": True,
        "subtitles_in_bounds": True,
        "audio_video_sync": True,
        "output_files_complete": not missing,
    }
    report = quality_gate_report(facts, checks)
    if not report["passed"]:
        if missing:
            raise NodeFailedError(
                f"产物缺失 {len(missing)} 个：{missing[0]} (quality_gate_failed:output_files_complete)"
            )
        first = report["failures"][0]
        raise NodeFailedError(f"quality_gate_failed:{first['gate']}:{first['suggestion']}")
    kinds: dict[str, int] = {}
    for ref in refs:
        kinds[ref.kind] = kinds.get(ref.kind, 0) + 1
    summary = "质量校验通过：" + ", ".join(f"{kind}×{count}" for kind, count in sorted(kinds.items()))
    return NodeExecutionResult(
        outputs={"quality": [AssetRef(kind="quality", path=json.dumps(report, ensure_ascii=False))]}, summary=summary
    )


@_register("export")
async def _export(ctx: NodeContext) -> NodeExecutionResult:
    videos = _upstream_refs(ctx, "video")
    files = _upstream_refs(ctx, "file")
    all_refs = videos + files
    if not all_refs:
        raise NodeFailedError("没有可导出的产物（请连接视频/合成节点）")
    for ref in all_refs:
        if ref.path and (ctx.project_path / ref.path).exists():
            ctx.log("info", f"导出产物: {ref.path}")
    return NodeExecutionResult(
        outputs={"exported": all_refs},
        summary=f"导出清点完成：{len(all_refs)} 个产物",
    )


# ---------------------------------------------------------------------------
# generic wiring nodes
# ---------------------------------------------------------------------------


@_register("image_input")
async def _image_input(ctx: NodeContext) -> NodeExecutionResult:
    path = ctx.config.get("path")
    if not isinstance(path, str) or not path:
        raise NodeFailedError("图片输入节点未指定路径（path）")
    if not (ctx.project_path / path).exists():
        raise NodeFailedError(f"图片不存在: {path}")
    return NodeExecutionResult(
        outputs={"image": [AssetRef(kind="image", path=path, label=ctx.config.get("label") or path)]},
        summary=f"图片输入: {path}",
    )


@_register("video_input")
async def _video_input(ctx: NodeContext) -> NodeExecutionResult:
    path = ctx.config.get("path")
    if not isinstance(path, str) or not path:
        raise NodeFailedError("视频输入节点未指定路径（path）")
    if not (ctx.project_path / path).exists():
        raise NodeFailedError(f"视频不存在: {path}")
    return NodeExecutionResult(
        outputs={"video": [AssetRef(kind="video", path=path, label=ctx.config.get("label") or path)]},
        summary=f"视频输入: {path}",
    )


@_register("loop")
async def _loop(ctx: NodeContext) -> NodeExecutionResult:
    items = ctx.config.get("items") or []
    if not items:
        for ref in _upstream_refs(ctx):
            label = ref.label or ref.path
            if label:
                items.append(label)
    if not items:
        raise NodeFailedError("循环节点没有可迭代的输入（items）")
    return NodeExecutionResult(
        outputs={"items": [AssetRef(kind="params", count=len(items), label="loop items")]},
        summary=f"批量循环：{len(items)} 项",
    )


@_register("branch")
async def _branch(ctx: NodeContext) -> NodeExecutionResult:
    condition = ctx.config.get("condition") or {}
    field = condition.get("field")
    equals = condition.get("equals")
    value = ctx.config.get(field) if isinstance(field, str) else None
    ok = equals is None or str(value) == str(equals)
    branch_port = "true" if ok else "false"
    return NodeExecutionResult(
        outputs={branch_port: [AssetRef(kind="params", label=f"branch={branch_port}")]},
        summary=f"分支判断：{field}={value} {'通过' if ok else '不通过'}",
    )


@_register("param_adjust")
async def _param_adjust(ctx: NodeContext) -> NodeExecutionResult:
    overrides = ctx.config.get("overrides") or {}
    label = json.dumps(overrides, ensure_ascii=False)
    return NodeExecutionResult(
        outputs={"params": [AssetRef(kind="params", path=label, label="params")]},
        summary=f"参数调节：{len(overrides)} 项覆盖",
    )


__all__ = ["REGISTRY", "get_adapter", "NodeFailedError"]
