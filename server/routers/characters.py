"""角色管理路由（CRUD 由 _asset_router_factory 统一生成）。"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import File, HTTPException, UploadFile

from lib.asset_types import resolve_asset_key, validate_asset_name
from lib.i18n import Translator
from lib.image_utils import ImagePixelLimitError, normalize_storyboard_upload
from lib.path_safety import safe_join
from lib.project_manager import get_project_manager
from server.routers._asset_router_factory import build_asset_router

# late-binding 必需：测试通过 monkeypatch.setattr(characters, "get_project_manager", ...) 替换模块属性
router = build_asset_router(asset_type="character", pm_getter=lambda: get_project_manager())  # noqa: PLW0108

# The router is mounted at /api/v1; /projects is part of this project-scoped API path.


@router.post("/projects/{project_name}/characters/{char_name}/avatar")
@router.post("/{project_name}/characters/{char_name}/avatar", include_in_schema=False)
async def upload_character_avatar(
    project_name: str,
    char_name: str,
    _t: Translator,
    file: UploadFile = File(...),
) -> dict[str, object]:
    try:
        safe_char_name = validate_asset_name(char_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_t("asset_invalid_name", name=char_name)) from exc

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail=_t("character_avatar_file_empty"))
    max_bytes = 10 * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=_t("character_avatar_too_large", max_mb=max_bytes // (1024 * 1024)))
    try:
        normalized = await asyncio.to_thread(normalize_storyboard_upload, data, max_long_edge=None)
    except ImagePixelLimitError as exc:
        raise HTTPException(
            status_code=413,
            detail=_t("character_avatar_pixels_too_large", max_megapixels=64),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_t("character_avatar_invalid_file")) from exc

    project_manager = get_project_manager()
    project = project_manager.load_project(project_name)
    if resolve_asset_key(project.get("characters"), safe_char_name) is None:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=safe_char_name))

    relative_path = f"characters/{safe_char_name}_avatar_manual.png"
    avatar_path = safe_join(project_manager.get_project_path(project_name), relative_path)
    avatar_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=avatar_path.parent, prefix=".avatar.", suffix=".tmp", delete=False
        ) as temp:
            temp.write(normalized)
            temp_path = Path(temp.name)
        project_manager.replace_project_character_avatar(
            project_name,
            safe_char_name,
            relative_path,
            temp_path,
        )
        temp_path = None
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=safe_char_name)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=_t("internal_server_error")) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return {"success": True, "path": relative_path}
