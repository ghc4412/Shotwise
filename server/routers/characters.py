"""角色管理路由（CRUD 由 _asset_router_factory 统一生成）。"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from lib.asset_types import resolve_asset_key, validate_asset_name
from lib.character_variants import VARIANT_STATUSES, validate_variant_slug
from lib.i18n import Translator
from lib.image_utils import ImagePixelLimitError, normalize_storyboard_upload
from lib.path_safety import PathTraversalError, safe_join
from lib.project_change_hints import project_change_source
from lib.project_manager import get_project_manager
from server.routers._asset_router_factory import build_asset_router

# late-binding 必需：测试通过 monkeypatch.setattr(characters, "get_project_manager", ...) 替换模块属性
router = build_asset_router(asset_type="character", pm_getter=lambda: get_project_manager())  # noqa: PLW0108

# The router is mounted at /api/v1; /projects is part of this project-scoped API path.


class CharacterVariantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    display_name: str | None = None
    description: str = ""
    image_path: str = ""
    status: Literal["draft", "ready", "missing", "archived"] = "draft"
    metadata: dict[str, Any] = Field(default_factory=dict)
    image_asset_id: str | None = None


class CharacterVariantUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = None
    display_name: str | None = None
    description: str | None = None
    image_path: str | None = None
    status: Literal["draft", "ready", "missing", "archived"] | None = None
    metadata: dict[str, Any] | None = None
    image_asset_id: str | None = None


def _variant_error(status_code: int, translator: Translator, key: str, **params: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail=translator(key, **params))


def _validate_variant_slug_for_request(slug: str, translator: Translator) -> str:
    try:
        return validate_variant_slug(slug)
    except (TypeError, ValueError) as exc:
        raise _variant_error(422, translator, "character_variant_invalid_slug") from exc


def _validate_variant_status_for_request(status: str | None, translator: Translator) -> None:
    if status is not None and status not in VARIANT_STATUSES:
        raise _variant_error(422, translator, "character_variant_invalid_status")


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


@router.get("/projects/{project_name}/characters/{char_name}/variants")
async def list_character_variants(project_name: str, char_name: str, _t: Translator) -> dict[str, object]:
    try:
        variants = await asyncio.to_thread(get_project_manager().list_character_variants, project_name, char_name)
        return {"variants": variants}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name)) from exc


@router.post("/projects/{project_name}/characters/{char_name}/variants")
async def create_character_variant(
    project_name: str,
    char_name: str,
    req: CharacterVariantCreateRequest,
    _t: Translator,
) -> dict[str, object]:
    slug = _validate_variant_slug_for_request(req.slug, _t)
    _validate_variant_status_for_request(req.status, _t)
    try:

        def _create() -> dict[str, Any]:
            with project_change_source("webui"):
                return get_project_manager().create_character_variant(
                    project_name,
                    char_name,
                    slug,
                    display_name=req.display_name,
                    description=req.description,
                    image_path=req.image_path,
                    status=req.status,
                    metadata=req.metadata,
                    image_asset_id=req.image_asset_id,
                )

        variant = await asyncio.to_thread(_create)
        return {"success": True, "variant": variant}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name)) from exc
    except PathTraversalError as exc:
        raise _variant_error(422, _t, "character_variant_invalid_image_path") from exc
    except ValueError as exc:
        raise _variant_error(409, _t, "character_variant_slug_exists", slug=slug) from exc


@router.patch("/projects/{project_name}/characters/{char_name}/variants/{variant_id}")
async def update_character_variant(
    project_name: str,
    char_name: str,
    variant_id: str,
    req: CharacterVariantUpdateRequest,
    _t: Translator,
) -> dict[str, object]:
    if req.slug is not None:
        slug = _validate_variant_slug_for_request(req.slug, _t)
    else:
        slug = None
    _validate_variant_status_for_request(req.status, _t)
    try:

        def _update() -> dict[str, Any]:
            with project_change_source("webui"):
                return get_project_manager().update_character_variant(
                    project_name,
                    char_name,
                    variant_id,
                    slug=slug,
                    display_name=req.display_name,
                    description=req.description,
                    image_path=req.image_path,
                    status=req.status,
                    metadata=req.metadata,
                    image_asset_id=req.image_asset_id,
                )

        variant = await asyncio.to_thread(_update)
        return {"success": True, "variant": variant}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
    except KeyError as exc:
        if str(exc).strip("'") == char_name:
            raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name)) from exc
        raise _variant_error(404, _t, "character_variant_not_found", name=variant_id) from exc
    except PathTraversalError as exc:
        raise _variant_error(422, _t, "character_variant_invalid_image_path") from exc
    except ValueError as exc:
        raise _variant_error(409, _t, "character_variant_slug_exists", slug=slug or variant_id) from exc


@router.delete("/projects/{project_name}/characters/{char_name}/variants/{variant_id}")
async def delete_character_variant(
    project_name: str,
    char_name: str,
    variant_id: str,
    _t: Translator,
) -> dict[str, object]:
    try:

        def _delete() -> dict[str, Any]:
            manager = get_project_manager()
            variant = manager.get_character_variant(project_name, char_name, variant_id)
            with project_change_source("webui"):
                manager.delete_character_variant(project_name, char_name, variant_id)
            return variant

        variant = await asyncio.to_thread(_delete)
        return {"success": True, "variant": variant}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
    except KeyError as exc:
        if str(exc).strip("'") == char_name:
            raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name)) from exc
        raise _variant_error(404, _t, "character_variant_not_found", name=variant_id) from exc
