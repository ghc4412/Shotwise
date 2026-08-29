"""Independent image tasks used by the Creative Board.

Canvas operations deliberately do not mutate project assets or screenplay Grid records.
Every operation preserves its source and returns newly registered MediaAsset outputs.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Literal

from lib.asset_types import ASSET_SPECS
from lib.db.base import DEFAULT_USER_ID
from lib.path_safety import safe_exists, safe_join
from server.services.generation_context import ImageLaneRequest, resolve_generation_context
from server.services.generation_tasks import get_project_manager
from server.services.image_edit_tasks import resolve_current_image_rel, resolve_reference_media_asset_path
from server.services.media_assets import register_media_asset

CANVAS_IMAGE_TASK_TYPES = (
    "canvas_image_split",
    "canvas_image_panorama",
    "canvas_image_angles",
    "canvas_image_layers",
    "canvas_image_hd",
    "canvas_image_outpaint",
    "canvas_image_redraw",
    "canvas_image_erase",
    "canvas_image_cutout",
    "canvas_image_crop",
)
CANVAS_IMAGE_OPERATIONS = frozenset(CANVAS_IMAGE_TASK_TYPES)

# 确定性 PIL 操作：几何裁剪 / 宫格切分，无 AI 语义。
_CANVAS_PIL_OPERATIONS = frozenset({"canvas_image_split", "canvas_image_crop"})

# 其余操作一律走现有 i2i 图生图管线，复用项目「图生图」模型绑定（见项目设置 / 按用途绑定模型）。
_CANVAS_AI_OPERATIONS = CANVAS_IMAGE_OPERATIONS - _CANVAS_PIL_OPERATIONS

# These operations use the selected area as an edit mask. The provider receives a
# cropped reference, then the generated patch is composited back onto the full source
# so pixels outside the selection remain available in the new canvas card.
_REGION_COMPOSITE_OPERATIONS = frozenset({"canvas_image_redraw", "canvas_image_erase"})
_OUTPAINT_OPERATIONS = frozenset({"canvas_image_outpaint"})


def _validate_grid(rows: Any, cols: Any) -> tuple[int, int]:
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 2 or rows > 8:
        raise ValueError("rows must be an integer between 2 and 8")
    if isinstance(cols, bool) or not isinstance(cols, int) or cols < 2 or cols > 8:
        raise ValueError("cols must be an integer between 2 and 8")
    return rows, cols


def _validate_count(value: Any, *, default: int, maximum: int = 8) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValueError(f"count must be an integer between 1 and {maximum}")
    return value


def resolve_canvas_image_source(
    project_name: str,
    payload: dict[str, Any],
    *,
    project_manager: Any | None = None,
) -> tuple[Path, Path, str]:
    """Resolve an in-project image path for a canvas task."""
    pm = project_manager or get_project_manager()
    project = pm.load_project(project_name)
    project_root = pm.get_project_path(project_name)
    source_kind = payload.get("source_kind")

    if source_kind == "media":
        media_id = payload.get("media_asset_id")
        if not isinstance(media_id, str) or not media_id.strip():
            raise ValueError("media_asset_id is required for media source")
        source = resolve_reference_media_asset_path(project_root, media_id.strip())
        return project_root, source, media_id.strip()

    if source_kind != "project":
        raise ValueError("source_kind must be project or media")
    resource_type = payload.get("resource_type")
    resource_id = payload.get("resource_id")
    if not isinstance(resource_type, str) or resource_type not in (*ASSET_SPECS.keys(), "storyboard"):
        raise ValueError("unsupported project image resource_type")
    if not isinstance(resource_id, str) or not resource_id.strip():
        raise ValueError("resource_id is required for project source")
    script_file = payload.get("script_file")
    script = pm.load_script(project_name, str(script_file)) if resource_type == "storyboard" else None
    current_rel = resolve_current_image_rel(project, resource_type, resource_id.strip(), script)
    if not current_rel or not safe_exists(project_root, current_rel):
        raise ValueError("project image does not exist")
    return project_root, safe_join(project_root, current_rel, require_file=True), resource_id.strip()


def _asset_record(asset: Any) -> dict[str, Any]:
    return {
        "id": asset.id,
        "kind": asset.kind,
        "original_name": asset.original_name,
        "physical_path": asset.physical_path,
        "mime_type": asset.mime_type,
        "width": asset.width,
        "height": asset.height,
    }


def _register_output(
    *,
    project_name: str,
    project_root: Path,
    source_id: str,
    path: Path,
    label: str,
    origin: Literal["generated", "edited", "extracted", "imported", "upload"],
) -> dict[str, Any]:
    relative = path.relative_to(project_root).as_posix()
    asset = register_media_asset(
        project_id=project_name,
        project_root=project_root,
        relative_path=relative,
        origin=origin,
        original_name=f"{source_id}-{label}.png",
    )
    output: dict[str, Any] = {"file_path": relative, "label": label}
    if asset is not None:
        output["media_asset_id"] = asset.id
        output["media_asset"] = _asset_record(asset)
    return output


def _region_box(image: Any, region: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(region, dict):
        return None
    width, height = image.size
    try:
        left = float(region.get("x", 0))
        top = float(region.get("y", 0))
        right = left + float(region.get("width", width))
        bottom = top + float(region.get("height", height))
    except (TypeError, ValueError):
        raise ValueError("region must contain numeric x, y, width, height") from None
    if max(abs(left), abs(top), abs(right), abs(bottom)) <= 1.0:
        left, right = left * width, right * width
        top, bottom = top * height, bottom * height
    left = max(0, min(width - 1, round(left)))
    top = max(0, min(height - 1, round(top)))
    right = max(left + 1, min(width, round(right)))
    bottom = max(top + 1, min(height, round(bottom)))
    return left, top, right, bottom


def _crop_region(image: Any, region: Any) -> Any:
    box = _region_box(image, region)
    return image if box is None else image.crop(box)


def _outpaint_geometry(image: Any, region: Any) -> tuple[int, int, int, int] | None:
    """Return ``(canvas_width, canvas_height, source_left, source_top)`` for outpaint."""
    if not isinstance(region, dict):
        return None
    width, height = image.size
    try:
        x = float(region.get("x", 0))
        y = float(region.get("y", 0))
        region_width = float(region.get("width", 1))
        region_height = float(region.get("height", 1))
    except (TypeError, ValueError):
        raise ValueError("region must contain numeric x, y, width, height") from None
    if max(abs(x), abs(y), abs(region_width), abs(region_height)) > 1.0:
        x, y = x / width, y / height
        region_width, region_height = region_width / width, region_height / height
    if region_width <= 0 or region_height <= 0 or x < 0 or y < 0 or x + region_width > 1 or y + region_height > 1:
        raise ValueError("outpaint region must be a positive normalized box inside the canvas")
    canvas_width = max(width, round(width / region_width))
    canvas_height = max(height, round(height / region_height))
    source_left = min(max(0, round(x * canvas_width)), canvas_width - width)
    source_top = min(max(0, round(y * canvas_height)), canvas_height - height)
    return canvas_width, canvas_height, source_left, source_top


def _source_aspect_ratio(source: Path) -> str:
    from PIL import Image

    with Image.open(source) as opened:
        width, height = opened.size
    return f"{width}:{height}"


def _requested_image_size(payload: dict[str, Any], configured: str | None) -> str | None:
    requested = payload.get("quality")
    if isinstance(requested, str) and requested.strip().upper() in {"2K", "4K"}:
        return requested.strip().upper()
    return configured


async def _write_outputs(
    project_name: str,
    source: Path,
    project_root: Path,
    source_id: str,
    task_id: str | None,
    operation: str,
    build_outputs: Any,
) -> list[dict[str, Any]]:
    from PIL import Image

    output_dir = (
        project_root / "canvas_outputs" / operation.removeprefix("canvas_image_") / (task_id or uuid.uuid4().hex)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    def render() -> list[dict[str, Any]]:
        with Image.open(source) as opened:
            opened.load()
            image = opened.convert("RGBA")
            rendered = build_outputs(image)
            outputs: list[dict[str, Any]] = []
            for index, (label, item) in enumerate(rendered):
                path = output_dir / f"{index + 1:02d}-{label}.png"
                item.save(path, format="PNG")
                outputs.append(
                    {
                        "index": index,
                        "label": label,
                        "file_path": path.relative_to(project_root).as_posix(),
                        "width": item.width,
                        "height": item.height,
                    }
                )
            return outputs

    raw_outputs = await asyncio.to_thread(render)
    registered: list[dict[str, Any]] = []
    for raw in raw_outputs:
        output = await asyncio.to_thread(
            _register_output,
            project_name=project_name,
            project_root=project_root,
            source_id=source_id,
            path=project_root / raw["file_path"],
            label=raw["label"],
            origin="extracted" if operation in {"canvas_image_split", "canvas_image_layers"} else "generated",
        )
        registered.append({**raw, **output})
    return registered


def _build_split(image: Any, rows: int, cols: int) -> list[tuple[str, Any]]:
    width, height = image.size
    cells: list[tuple[str, Any]] = []
    for row in range(rows):
        for col in range(cols):
            left = col * width // cols
            top = row * height // rows
            right = (col + 1) * width // cols
            bottom = (row + 1) * height // rows
            cells.append((f"cell-{row + 1}-{col + 1}", image.crop((left, top, right, bottom))))
    return cells


def _default_count(operation: str) -> int:
    """每个操作默认产出的变体数（多角度 / 图层分离走「按用途指定模型」的批量变体）。"""
    return {"canvas_image_angles": 4, "canvas_image_layers": 3}.get(operation, 1)


def _build_ai_prompt(operation: str, payload: dict[str, Any]) -> str:
    """组装 i2i prompt：操作语义 + 区域描述 + 用户指令（agent 侧字符串，不参与 i18n）。"""
    instruction = (payload.get("instruction") or "").strip()
    region = payload.get("region")
    region_desc = ""
    if isinstance(region, dict):
        region_desc = (
            f" 处理区域：x={region.get('x', 0)} y={region.get('y', 0)} "
            f"宽={region.get('width', 0)} 高={region.get('height', 0)}。"
        )
    multiplier = payload.get("multiplier")
    op_prompt = {
        "canvas_image_panorama": "将画面向左、右延伸为全景横幅，保持主体与整体风格一致，自然补全新区域。",
        "canvas_image_angles": "保持主体与风格一致，生成新的拍摄角度/视角变体。",
        "canvas_image_layers": "将主体与背景分离，输出仅含主体的前景图。",
        "canvas_image_hd": "高清晰放大图片，提升细节与锐度。",
        "canvas_image_outpaint": "向外扩图画布并自然补全四周新区域，保持主体与风格一致。",
        "canvas_image_redraw": "在指定区域重新绘制，按指令修改内容。",
        "canvas_image_erase": "移除指定区域内的物体并自然补全背景。",
        "canvas_image_cutout": "抠图：移除背景，仅保留主体，输出透明背景。",
    }.get(operation, "对图片进行智能编辑。")
    multiplier_desc = f" 放大倍数：{multiplier}。" if multiplier else ""
    parts = [op_prompt]
    if region_desc:
        parts.append(region_desc)
    if multiplier_desc:
        parts.append(multiplier_desc)
    if instruction:
        parts.append(instruction)
    return "".join(parts).strip()


async def _generate_ai_outputs(
    project_name: str,
    project_root: Path,
    source: Path,
    source_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    task_id: str | None,
    user_id: str,
) -> list[dict[str, Any]]:
    """走项目「图生图」模型生成独立输出并登记为 media asset（不触碰源资产版本）。"""
    from PIL import Image

    pm = get_project_manager()
    project = await asyncio.to_thread(pm.load_project, project_name)
    ctx = await resolve_generation_context(
        project_name,
        payload,
        project=project,
        user_id=user_id,
        image=ImageLaneRequest(capability="i2i"),
    )
    generator = ctx.generator
    image_size = _requested_image_size(payload, ctx.image.resolution)
    prompt = _build_ai_prompt(operation, payload)
    count = _validate_count(payload.get("count"), default=_default_count(operation))

    outpaint_geometry: tuple[int, int, int, int] | None = None
    if operation in _OUTPAINT_OPERATIONS and isinstance(payload.get("region"), dict):

        def _read_outpaint_geometry() -> tuple[int, int, int, int] | None:
            with Image.open(source) as opened:
                opened.load()
                return _outpaint_geometry(opened.convert("RGBA"), payload["region"])

        outpaint_geometry = await asyncio.to_thread(_read_outpaint_geometry)

    requested_ratio = payload.get("aspect_ratio")
    aspect_ratio = (
        requested_ratio.strip()
        if isinstance(requested_ratio, str) and requested_ratio.strip()
        else (
            f"{outpaint_geometry[0]}:{outpaint_geometry[1]}"
            if outpaint_geometry is not None
            else _source_aspect_ratio(source)
        )
    )

    output_dir = (
        project_root / "canvas_outputs" / operation.removeprefix("canvas_image_") / (task_id or uuid.uuid4().hex)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    # Region edits use a cropped reference to focus the model, then composite the
    # generated patch back onto the full source. Outpaint is different: the
    # selected box describes where the original image belongs in a larger canvas.
    region_box: tuple[int, int, int, int] | None = None
    ref_path = source
    if operation not in _OUTPAINT_OPERATIONS and isinstance(payload.get("region"), dict):

        def _crop_ref() -> tuple[Path, tuple[int, int, int, int] | None]:
            with Image.open(source) as opened:
                opened.load()
                original = opened.convert("RGBA")
                box = _region_box(original, payload["region"])
                if box is None:
                    return source, None
                cropped = original.crop(box)
                target = output_dir / "region-ref.png"
                cropped.save(target, format="PNG")
                return target, box

        ref_path, region_box = await asyncio.to_thread(_crop_ref)

    label = operation.removeprefix("canvas_image_")
    outputs: list[dict[str, Any]] = []
    for index in range(count):
        path = output_dir / f"{index + 1:02d}-{label}.png"
        await generator.generate_image_output_async(
            prompt=prompt,
            output_path=path,
            reference_images=[ref_path],
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            resource_id=f"{source_id}-{operation}-{index}",
        )
        if operation in _REGION_COMPOSITE_OPERATIONS and region_box is not None:

            def _composite_patch() -> None:
                with Image.open(source) as original_opened, Image.open(path) as patch_opened:
                    original = original_opened.convert("RGBA")
                    patch = patch_opened.convert("RGBA")
                    left, top, right, bottom = region_box
                    patch = patch.resize((right - left, bottom - top), Image.Resampling.LANCZOS)
                    original.alpha_composite(patch, (left, top))
                    original.save(path, format="PNG")

            await asyncio.to_thread(_composite_patch)
        elif operation in _OUTPAINT_OPERATIONS and outpaint_geometry is not None:

            def _composite_outpaint() -> None:
                canvas_width, canvas_height, source_left, source_top = outpaint_geometry
                with Image.open(source) as original_opened, Image.open(path) as generated_opened:
                    original = original_opened.convert("RGBA")
                    generated = generated_opened.convert("RGBA").resize(
                        (canvas_width, canvas_height), Image.Resampling.LANCZOS
                    )
                    generated.alpha_composite(original, (source_left, source_top))
                    generated.save(path, format="PNG")

            await asyncio.to_thread(_composite_outpaint)
        with Image.open(path) as opened:
            opened.load()
            width, height = opened.size
        registered = await asyncio.to_thread(
            _register_output,
            project_name=project_name,
            project_root=project_root,
            source_id=source_id,
            path=path,
            label=label,
            origin="generated",
        )
        outputs.append(
            {
                "index": index,
                "label": label,
                "file_path": path.relative_to(project_root).as_posix(),
                "width": width,
                "height": height,
                **registered,
            }
        )
    return outputs


async def execute_canvas_image_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Execute one independent Creative Board image operation."""
    operation = str(payload.get("operation") or "canvas_image_split")
    if operation not in CANVAS_IMAGE_OPERATIONS:
        raise ValueError(f"unsupported canvas image operation: {operation}")
    project_root, source, source_id = await asyncio.to_thread(resolve_canvas_image_source, project_name, payload)

    metadata: dict[str, Any] = {
        "operation": operation,
        "source_kind": payload.get("source_kind"),
        "source_id": source_id,
    }
    if operation == "canvas_image_split":
        rows, cols = _validate_grid(payload.get("rows"), payload.get("cols"))
        outputs = await _write_outputs(
            project_name,
            source,
            project_root,
            source_id,
            task_id,
            operation,
            lambda image: _build_split(image, rows, cols),
        )
        for output in outputs:
            cell = output["index"]
            output.update({"row": cell // cols, "col": cell % cols})
        metadata.update(
            {
                "rows": rows,
                "cols": cols,
                "include_split_lines": bool(payload.get("include_split_lines", True)),
                "cells": outputs,
            }
        )
    elif operation == "canvas_image_crop":

        def crop(image: Any) -> list[tuple[str, Any]]:
            return [("crop", _crop_region(image, payload.get("region")))]

        outputs = await _write_outputs(project_name, source, project_root, source_id, task_id, operation, crop)
        metadata.update({"region": payload.get("region"), "outputs": outputs})
    else:
        # 其余操作（全景 / 多角度 / 图层分离 / 高清 / 扩图 / 重绘 / 擦除 / 抠图）
        # 一律走项目「图生图」模型的 i2i 管线，产出独立 media asset。
        outputs = await _generate_ai_outputs(
            project_name,
            project_root,
            source,
            source_id,
            operation,
            payload,
            task_id=task_id,
            user_id=user_id,
        )
        metadata.update({"region": payload.get("region"), "outputs": outputs})
    return metadata


async def execute_canvas_image_split_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible split executor entry point."""
    return await execute_canvas_image_task(
        project_name, resource_id, {**payload, "operation": "canvas_image_split"}, user_id=user_id, task_id=task_id
    )
