"""Project media library API backed by the index-only MediaAsset catalog."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lib.feature_flags import feature_enabled
from lib.media_catalog import (
    BindingKind,
    MediaAssetReferencedError,
    MediaKind,
    MediaOrigin,
    classify_media_path,
    project_media_catalog,
)
from server.routers.projects import get_project_manager
from server.services import media_assets as service


def _require_feature() -> None:
    if not feature_enabled("media_library"):
        raise HTTPException(status_code=404, detail={"code": "feature_disabled", "feature": "media_library"})


router = APIRouter(dependencies=[Depends(_require_feature)])


class MediaBindingRequest(BaseModel):
    binding_kind: BindingKind
    target_id: str | None = Field(default=None, max_length=256)
    purpose: str = Field(min_length=1, max_length=128)


class MediaArchiveRequest(BaseModel):
    archived: bool


def _project_root(project_id: str):
    manager = get_project_manager()
    if not manager.project_exists(project_id):
        raise HTTPException(status_code=404, detail="project_not_found")
    return manager.get_project_path(project_id)


@router.get("/projects/{project_id}/media-assets")
async def list_media_assets(
    project_id: str,
    kind: MediaKind | None = Query(default=None),
    origin: MediaOrigin | None = Query(default=None),
    workflow_run_id: str | None = Query(default=None, max_length=128),
    binding_kind: BindingKind | None = Query(default=None),
    target_id: str | None = Query(default=None, max_length=256),
    purpose: str | None = Query(default=None, max_length=128),
    archived: bool | None = Query(default=None),
):
    project_root = await asyncio.to_thread(_project_root, project_id)
    return await asyncio.to_thread(
        service.list_project_media_assets,
        project_id=project_id,
        project_root=project_root,
        kind=kind,
        origin=origin,
        workflow_run_id=workflow_run_id,
        binding_kind=binding_kind,
        target_id=target_id,
        purpose=purpose,
        archived=archived,
    )


@router.post("/projects/{project_id}/media-assets/upload", status_code=201)
async def upload_media_asset(project_id: str, file: UploadFile = File(...)):
    project_root = await asyncio.to_thread(_project_root, project_id)
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if classify_media_path(filename) is None:
        raise HTTPException(status_code=415, detail="unsupported_media")
    relative_path = Path("uploads") / f"{uuid.uuid4().hex}{suffix}"
    destination = project_root / relative_path
    await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
    try:
        with destination.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                stream.write(chunk)
    finally:
        await file.close()
    asset = await asyncio.to_thread(
        service.register_media_asset,
        project_id=project_id,
        project_root=project_root,
        relative_path=relative_path.as_posix(),
        origin="upload",
        original_name=filename,
    )
    if asset is None:
        catalog = project_media_catalog(project_root)
        await asyncio.to_thread(
            catalog.enqueue_reconciliation,
            project_id=project_id,
            relative_path=relative_path.as_posix(),
            reason="upload_registration_unavailable",
            origin="upload",
        )
        raise HTTPException(status_code=503, detail="media_index_unavailable")
    return await asyncio.to_thread(service.get_project_media_asset, project_root=project_root, media_asset_id=asset.id)


@router.get("/projects/{project_id}/media-assets/content/{media_asset_id}")
async def get_media_content(project_id: str, media_asset_id: str):
    project_root = await asyncio.to_thread(_project_root, project_id)
    asset = await asyncio.to_thread(
        service.get_project_media_asset, project_root=project_root, media_asset_id=media_asset_id
    )
    path = Path(str(asset["physical_path"]))
    try:
        safe_path = path.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="media_file_not_found") from exc
    if not (project_root / safe_path).is_file():
        raise HTTPException(status_code=404, detail="media_file_not_found")
    return FileResponse(project_root / safe_path, media_type=asset.get("mime_type"), filename=asset["original_name"])


@router.get("/projects/{project_id}/media-assets/{media_asset_id}")
async def get_media_asset(project_id: str, media_asset_id: str):
    project_root = await asyncio.to_thread(_project_root, project_id)
    try:
        return await asyncio.to_thread(
            service.get_project_media_asset, project_root=project_root, media_asset_id=media_asset_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="media_asset_not_found") from exc


@router.post("/projects/{project_id}/media-assets/{media_asset_id}/bindings", status_code=201)
async def bind_media_asset(project_id: str, media_asset_id: str, body: MediaBindingRequest):
    project_root = await asyncio.to_thread(_project_root, project_id)
    try:
        return await asyncio.to_thread(
            service.bind_project_media_asset,
            project_root=project_root,
            project_id=project_id,
            media_asset_id=media_asset_id,
            binding_kind=body.binding_kind,
            target_id=body.target_id,
            purpose=body.purpose,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="media_asset_not_found") from exc


@router.patch("/projects/{project_id}/media-assets/{media_asset_id}/archive")
async def archive_media_asset(project_id: str, media_asset_id: str, body: MediaArchiveRequest):
    project_root = await asyncio.to_thread(_project_root, project_id)
    try:
        return await asyncio.to_thread(
            service.archive_project_media_asset,
            project_root=project_root,
            media_asset_id=media_asset_id,
            archived=body.archived,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="media_asset_not_found") from exc


@router.post("/projects/{project_id}/media-assets/scan")
async def scan_media_assets(project_id: str, dry_run: bool = Query(default=False)):
    project_root = await asyncio.to_thread(_project_root, project_id)
    if dry_run:
        return await asyncio.to_thread(service.audit_project_media, project_id=project_id, project_root=project_root)
    return await asyncio.to_thread(service.scan_project_media, project_id=project_id, project_root=project_root)


@router.post("/projects/{project_id}/media-assets/reconciliation/retry")
async def retry_media_assets(project_id: str, item_id: str | None = Query(default=None, max_length=64)):
    project_root = await asyncio.to_thread(_project_root, project_id)
    return await asyncio.to_thread(
        service.retry_media_reconciliation, project_id=project_id, project_root=project_root, item_id=item_id
    )


@router.delete("/projects/{project_id}/media-assets/{media_asset_id}")
async def delete_media_asset(project_id: str, media_asset_id: str):
    project_root = await asyncio.to_thread(_project_root, project_id)
    try:
        return await asyncio.to_thread(
            service.delete_project_media_asset,
            project_root=project_root,
            media_asset_id=media_asset_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="media_asset_not_found") from exc
    except MediaAssetReferencedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "media_asset_still_referenced", "references": list(exc.references)},
        ) from exc
