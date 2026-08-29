"""Application seam for optional MediaAsset indexing.

This module delegates persistence to lib.media_catalog and never changes the
existing upload, generation, public-file URL, or project-JSON path contracts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Literal

from lib.media_catalog import (
    BindingKind,
    MediaAsset,
    MediaAssetReferencedError,
    MediaKind,
    MediaOrigin,
    classify_media_path,
    media_index_enabled,
    project_media_catalog,
)
from server.services.media_indexing import (
    backfill_project_media_assets,
    retry_project_media_reconciliation,
    scan_project_media_assets,
)


def index_existing_project_media(project_id: str, project_root: Path) -> list[MediaAsset]:
    """Idempotently index old media references when rollout enables the feature."""

    return backfill_project_media_assets(project_id, project_root)


def register_media_asset(
    *,
    project_id: str,
    project_root: Path,
    relative_path: str,
    origin: MediaOrigin,
    workflow_run_id: str | None = None,
    workflow_node_key: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    prompt_snapshot: str | None = None,
    original_name: str | None = None,
) -> MediaAsset | None:
    """Index a new upload or generated file without changing its legacy path.

    Indexing is a no-op while SHOTWISE_MEDIA_ASSET_INDEX is disabled.
    """

    if not media_index_enabled():
        return None
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("relative_path must stay inside the project root")
    return project_media_catalog(project_root).register(
        project_id=project_id,
        path=project_root / relative,
        origin=origin,
        workflow_run_id=workflow_run_id,
        workflow_node_key=workflow_node_key,
        provider_id=provider_id,
        model_id=model_id,
        prompt_snapshot=prompt_snapshot,
        original_name=original_name,
    )


def list_project_media_assets(
    *,
    project_id: str | None = None,
    project_root: Path,
    kind: MediaKind | None = None,
    origin: MediaOrigin | None = None,
    workflow_run_id: str | None = None,
    binding_kind: BindingKind | None = None,
    target_id: str | None = None,
    purpose: str | None = None,
    archived: bool | None = None,
) -> dict[str, Any]:
    """Return the project media library as semantic index data."""

    catalog = project_media_catalog(project_root)
    assets = catalog.list_assets(
        project_id=project_id,
        kind=kind,
        origin=origin,
        workflow_run_id=workflow_run_id,
        archived=archived,
    )
    items: list[dict[str, Any]] = []
    for asset in assets:
        bindings = catalog.bindings_for(asset.id)
        if binding_kind is not None:
            bindings = [binding for binding in bindings if binding.binding_kind == binding_kind]
            if not bindings:
                continue
        if target_id is not None:
            bindings = [binding for binding in bindings if binding.target_id == target_id]
            if not bindings:
                continue
        if purpose is not None:
            bindings = [binding for binding in bindings if binding.purpose == purpose]
            if not bindings:
                continue
        item = asdict(asset)
        item["bindings"] = [asdict(binding) for binding in bindings]
        item["derivations"] = [asdict(derivation) for derivation in catalog.derivations_for(asset.id)]
        items.append(item)
    return {"items": items, "count": len(items)}


async def sync_project_media_catalog(*, session: Any, project_id: str, project_root: Path) -> dict[str, int | bool]:
    """Synchronize the JSON-first catalog into database mirror tables."""

    if not media_index_enabled():
        return {"enabled": False, "assets": 0, "bindings": 0, "derivations": 0}
    catalog = project_media_catalog(project_root)
    try:
        result = await catalog.sync_to_database(session, project_id=project_id)
    except Exception as exc:  # noqa: BLE001 -- retain retry context and preserve the original failure
        catalog.enqueue_reconciliation(
            project_id=project_id,
            relative_path=".media-assets.json",
            reason=f"database_sync_failed:{exc}",
            operation="database_sync",
        )
        raise
    catalog.resolve_reconciliation(operation="database_sync")
    return {"enabled": True, **result}


def get_project_media_asset(*, project_root: Path, media_asset_id: str) -> dict[str, Any]:
    catalog = project_media_catalog(project_root)
    asset = catalog.get(media_asset_id)
    if asset is None:
        raise KeyError(media_asset_id)
    result = asdict(asset)
    result["bindings"] = [asdict(item) for item in catalog.bindings_for(media_asset_id)]
    result["derivations"] = [asdict(item) for item in catalog.derivations_for(media_asset_id)]
    result["reconciliation"] = [
        asdict(item)
        for item in catalog.reconciliation_items()
        if item.media_asset_id == media_asset_id or item.relative_path == asset.physical_path
    ]
    return result


def bind_project_media_asset(
    *,
    project_root: Path,
    project_id: str,
    media_asset_id: str,
    binding_kind: BindingKind,
    target_id: str | None,
    purpose: str,
) -> dict[str, Any]:
    binding = project_media_catalog(project_root).bind(
        media_asset_id,
        project_id=project_id,
        binding_kind=binding_kind,
        target_id=target_id,
        purpose=purpose,
    )
    return asdict(binding)


def archive_project_media_asset(*, project_root: Path, media_asset_id: str, archived: bool) -> dict[str, Any]:
    return asdict(project_media_catalog(project_root).set_archived(media_asset_id, archived))


def scan_project_media(*, project_id: str, project_root: Path) -> dict[str, Any]:
    return scan_project_media_assets(project_id, project_root)


def audit_project_media(*, project_id: str, project_root: Path) -> dict[str, Any]:
    from server.services.media_indexing import audit_project_media_assets

    return audit_project_media_assets(project_id, project_root)


def retry_media_reconciliation(*, project_id: str, project_root: Path, item_id: str | None = None) -> dict[str, Any]:
    return retry_project_media_reconciliation(project_id, project_root, item_id)


def delete_project_media_asset(*, project_root: Path, media_asset_id: str) -> dict[str, Any]:
    """Delete an index entry only; physical media files remain untouched."""

    from server.services.media_indexing import legacy_media_asset_references

    catalog = project_media_catalog(project_root)
    asset = catalog.get(media_asset_id)
    if asset is None:
        raise KeyError(media_asset_id)
    legacy_references, inspection_errors = legacy_media_asset_references(project_root, asset.physical_path)
    if inspection_errors:
        raise MediaAssetReferencedError(asset.id, [f"legacy_data_unreadable:{item}" for item in inspection_errors])
    if legacy_references:
        raise MediaAssetReferencedError(asset.id, [f"legacy_reference:{item}" for item in legacy_references])
    asset = catalog.delete(media_asset_id)
    return {"deleted": True, "media_asset_id": asset.id, "physical_path": asset.physical_path}


def index_workflow_outputs(
    *,
    project_id: str,
    project_root: Path,
    workflow_run_id: str,
    workflow_node_key: str,
    outputs: Mapping[str, Sequence[Any]],
    parent_media_asset_ids: Sequence[str] = (),
    origin: MediaOrigin = "generated",
    derivation_operation: Literal["generated", "edited", "extracted", "composited"] = "generated",
    provider_id: str | None = None,
    model_id: str | None = None,
    prompt_snapshot: str | None = None,
) -> dict[str, list[Any]]:
    """Register successful media outputs while preserving legacy paths."""

    normalized = {port: list(refs) for port, refs in outputs.items()}
    if not media_index_enabled():
        return normalized
    catalog = project_media_catalog(project_root)
    parent_ids = tuple(dict.fromkeys(str(value) for value in parent_media_asset_ids if str(value).strip()))
    for port, refs in normalized.items():
        for index, ref in enumerate(refs):
            raw_path = getattr(ref, "path", None)
            if not isinstance(raw_path, str) or not raw_path.strip() or classify_media_path(raw_path) is None:
                continue
            path = Path(raw_path)
            if path.is_absolute():
                try:
                    relative_path = path.resolve().relative_to(project_root.resolve()).as_posix()
                except ValueError:
                    relative_path = raw_path
            else:
                relative_path = path.as_posix()
            try:
                asset = register_media_asset(
                    project_id=project_id,
                    project_root=project_root,
                    relative_path=relative_path,
                    origin=origin,
                    workflow_run_id=workflow_run_id,
                    workflow_node_key=workflow_node_key,
                    provider_id=provider_id,
                    model_id=model_id,
                    prompt_snapshot=prompt_snapshot,
                )
                if asset is None:
                    continue
                try:
                    catalog.bind(
                        media_asset_id=asset.id,
                        project_id=project_id,
                        binding_kind="project",
                        target_id=None,
                        purpose=f"workflow_output:{workflow_node_key}:{port}",
                    )
                except Exception as exc:  # noqa: BLE001 -- retry binding without losing output
                    catalog.enqueue_reconciliation(
                        project_id=project_id,
                        relative_path=relative_path,
                        reason=f"binding_failed:{exc}",
                        workflow_run_id=workflow_run_id,
                        workflow_node_key=workflow_node_key,
                        media_asset_id=asset.id,
                        binding_kind="project",
                        purpose=f"workflow_output:{workflow_node_key}:{port}",
                        operation="binding",
                    )
                for parent_id in parent_ids:
                    if parent_id == asset.id:
                        continue
                    try:
                        catalog.derive(
                            parent_media_asset_id=parent_id,
                            child_media_asset_id=asset.id,
                            operation=derivation_operation,
                        )
                    except Exception as exc:  # noqa: BLE001 -- retry derivation without losing output
                        catalog.enqueue_reconciliation(
                            project_id=project_id,
                            relative_path=relative_path,
                            reason=f"derivation_failed:{exc}",
                            workflow_run_id=workflow_run_id,
                            workflow_node_key=workflow_node_key,
                            media_asset_id=asset.id,
                            parent_media_asset_id=parent_id,
                            derivation_operation="generated",
                            operation="derivation",
                        )
                refs[index] = replace(ref, media_asset_id=asset.id)
            except Exception as exc:  # noqa: BLE001 -- indexing must not fail a generated node
                catalog.enqueue_reconciliation(
                    project_id=project_id,
                    relative_path=relative_path,
                    reason=f"asset_registration_failed:{exc}",
                    workflow_run_id=workflow_run_id,
                    workflow_node_key=workflow_node_key,
                )
    return normalized


_TASK_OUTPUT_KEYS = frozenset(
    {
        "output_path",
        "output_paths",
        "file_path",
        "file_paths",
        "image_path",
        "image_paths",
        "video_path",
        "video_paths",
        "audio_path",
        "audio_paths",
    }
)


def _normalize_task_media_path(value: str, project_root: Path) -> str | None:
    if not value.strip() or "://" in value:
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            path = path.resolve().relative_to(project_root.resolve())
        except ValueError:
            return None
    elif ".." in path.parts:
        return None
    relative = path.as_posix()
    return relative if classify_media_path(relative) is not None else None


def _task_output_paths(result: Mapping[str, Any], project_root: Path) -> list[tuple[str, str]]:
    """Extract local media outputs from a successful generation result."""

    found: list[tuple[str, str]] = []

    def collect(value: Any, field: str) -> None:
        if isinstance(value, str):
            relative = _normalize_task_media_path(value, project_root)
            if relative is not None:
                found.append((field, relative))
        elif isinstance(value, Mapping):
            for key, child in value.items():
                key_name = str(key)
                if key_name.lower().endswith("_uri"):
                    continue
                collect(child, key_name)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child, field)

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_name = str(key)
                lower_key = key_name.lower()
                if lower_key == "generated_assets":
                    collect(child, key_name)
                elif lower_key in _TASK_OUTPUT_KEYS:
                    collect(child, key_name)
                else:
                    visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(result)
    return list(dict.fromkeys(found))


def _task_parent_media_asset_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Collect input MediaAsset IDs from task payloads for derivation links."""

    found: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if "media_asset_id" in str(key).lower():
                    values = child if isinstance(child, (list, tuple)) else (child,)
                    found.extend(str(item) for item in values if isinstance(item, str) and item.strip())
                else:
                    visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(payload)
    return tuple(dict.fromkeys(found))


def index_generation_task_result(
    *,
    project_id: str,
    project_root: Path | str | None,
    task_id: str,
    task_type: str,
    result: Any,
    payload: Mapping[str, Any] | None = None,
    provider_id: str | None = None,
) -> Any:
    """Index successful GenerationWorker outputs without changing task success semantics."""

    if not media_index_enabled() or not project_id or not isinstance(result, Mapping):
        return result
    if project_root is None:
        try:
            from lib.project_manager import get_project_manager

            project_root = get_project_manager().get_project_path(project_id)
        except Exception:  # noqa: BLE001 -- indexing must not alter task outcome
            return result
    root = Path(project_root)
    output_paths = _task_output_paths(result, root)
    if not output_paths:
        return result

    media_kind = {
        "video": "video",
        "reference_video": "video",
        "tts": "audio",
        "voice_sample": "audio",
    }.get(task_type, "image")
    origin_by_task: dict[str, MediaOrigin] = {
        "image_edit": "edited",
        "grid_split": "extracted",
        "canvas_image_split": "extracted",
        "canvas_image_layers": "extracted",
        "canvas_image_panorama": "generated",
        "canvas_image_angles": "generated",
        "canvas_image_hd": "generated",
    }
    origin = origin_by_task.get(task_type, "generated")
    operation: Literal["generated", "edited", "extracted", "composited"] = "generated"
    if task_type == "image_edit":
        operation = "edited"
    elif task_type in {"grid_split", "canvas_image_split", "canvas_image_layers"}:
        operation = "extracted"
    elif task_type == "canvas_image_hd":
        operation = "composited"
    from server.services.workflow_execution import AssetRef

    refs = {"result": [AssetRef(kind=media_kind, path=path, label=task_type) for _, path in output_paths]}
    payload_map = payload or {}
    indexed = index_workflow_outputs(
        project_id=project_id,
        project_root=root,
        workflow_run_id=task_id,
        workflow_node_key=task_type,
        outputs=refs,
        parent_media_asset_ids=_task_parent_media_asset_ids(payload_map),
        origin=origin,
        derivation_operation=operation,
        provider_id=provider_id,
        model_id=str(payload_map.get("model_id") or payload_map.get("model") or "") or None,
        prompt_snapshot=str(payload_map.get("prompt") or "") or None,
    )
    indexed_refs = indexed["result"]
    updated = dict(result)
    asset_ids = [ref.media_asset_id for ref in indexed_refs if getattr(ref, "media_asset_id", None)]
    if asset_ids:
        updated["media_asset_ids"] = asset_ids
        if len(asset_ids) == 1:
            updated["media_asset_id"] = asset_ids[0]
    field_ids: dict[str, list[str]] = {}
    for (field, _), ref in zip(output_paths, indexed_refs, strict=False):
        media_asset_id = getattr(ref, "media_asset_id", None)
        if media_asset_id:
            field_ids.setdefault(field, []).append(media_asset_id)
    for field, ids in field_ids.items():
        updated[f"{field}_media_asset_ids"] = ids
        if len(ids) == 1:
            updated[f"{field}_media_asset_id"] = ids[0]
    return updated
