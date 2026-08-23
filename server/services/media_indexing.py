"""Backfill legacy project media paths into the optional MediaAsset index."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from lib.media_catalog import MediaAsset, MediaOrigin, classify_media_path, media_index_enabled, project_media_catalog

_MEDIA_DIRECTORY_NAMES = frozenset(
    {
        "assets",
        "audio",
        "characters",
        "edited",
        "episodes",
        "extracted",
        "frames",
        "generated",
        "media",
        "products",
        "props",
        "reference_videos",
        "renders",
        "scenes",
        "shots",
        "storyboards",
        "uploads",
        "videos",
        "voiceovers",
    }
)


def _string_values(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _string_values(nested)


def _project_json_documents(project_root: Path) -> Iterator[dict[str, Any]]:
    candidates = [project_root / "project.json"]
    scripts = project_root / "scripts"
    if scripts.exists():
        candidates.extend(sorted(scripts.glob("*.json")))
    for candidate in candidates:
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict):
            yield raw


def _project_json_paths(project_root: Path) -> list[Path]:
    candidates = [project_root / "project.json"]
    scripts = project_root / "scripts"
    if scripts.exists():
        candidates.extend(sorted(scripts.glob("*.json")))
    return candidates


def legacy_media_reference_report(project_root: Path) -> tuple[set[str], list[str]]:
    """Collect media references and preserve manifest read/parse failures."""

    references: set[str] = set()
    errors: list[str] = []
    for candidate in _project_json_paths(project_root):
        if not candidate.exists():
            continue
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{candidate}: {exc}")
            continue
        if isinstance(raw, dict):
            references.update(value for value in _string_values(raw) if classify_media_path(value) is not None)
    return references, errors


def legacy_media_references(project_root: Path) -> set[str]:
    """Collect only relative media paths stored in legacy project documents."""

    references, _ = legacy_media_reference_report(project_root)
    return references


def legacy_media_asset_references(project_root: Path, physical_path: str) -> tuple[list[str], list[str]]:
    """Find legacy references to a physical asset without guessing on errors."""

    references, errors = legacy_media_reference_report(project_root)
    try:
        target = Path(physical_path).resolve()
    except OSError as exc:
        return [], [f"asset path {physical_path}: {exc}", *errors]
    matches: list[str] = []
    for reference in references:
        candidate = Path(reference)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            if ".." in candidate.parts:
                errors.append(f"reference {reference}: path escapes project root")
                continue
            resolved = (project_root / candidate).resolve()
        if resolved == target:
            matches.append(reference)
    return matches, errors


def backfill_project_media_assets(project_id: str, project_root: Path) -> list[MediaAsset]:
    """Backfill without touching old JSON or physical media; disabled by default."""

    if not media_index_enabled():
        return []
    catalog = project_media_catalog(project_root)
    references, manifest_errors = legacy_media_reference_report(project_root)
    for detail in manifest_errors:
        catalog.record_diagnostic(
            project_id=project_id,
            path=detail.split(":", 1)[0],
            code="unreadable_manifest",
            detail=detail,
        )
    return catalog.backfill(project_id=project_id, project_root=project_root, relative_paths=references)


def _origin_for_path(relative_path: str) -> MediaOrigin:
    parts = {part.lower() for part in Path(relative_path).parts}
    if "uploads" in parts:
        return "upload"
    if "edited" in parts:
        return "edited"
    if "extracted" in parts or "frames" in parts:
        return "extracted"
    if "generated" in parts or "renders" in parts or "storyboards" in parts:
        return "generated"
    return "imported"


def _scan_paths(project_root: Path) -> tuple[set[str], set[str]]:
    """Return supported references and unrecognized files in media directories."""

    supported = set(legacy_media_references(project_root))
    unsupported: set[str] = set()
    ignored = {".git", "node_modules", ".venv", "__pycache__"}
    for path in project_root.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        relative = path.relative_to(project_root).as_posix()
        if classify_media_path(path) is not None:
            supported.add(relative)
        elif any(part.lower() in _MEDIA_DIRECTORY_NAMES for part in path.relative_to(project_root).parts[:-1]):
            unsupported.add(relative)
    return supported, unsupported


def audit_project_media_assets(project_id: str, project_root: Path) -> dict[str, Any]:
    """Inspect candidates without writing the index or changing media files."""

    supported, unsupported = _scan_paths(project_root)
    _, manifest_errors = legacy_media_reference_report(project_root)
    diagnostics: list[dict[str, str]] = [
        {"code": "unreadable_manifest", "path": item.split(":", 1)[0], "detail": item} for item in manifest_errors
    ]
    valid_paths: list[str] = []
    for relative_path in sorted(supported | unsupported):
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            diagnostics.append(
                {"code": "invalid_reference", "path": relative_path, "detail": "path escapes project root"}
            )
            continue
        if classify_media_path(candidate) is None:
            diagnostics.append(
                {"code": "unsupported_media", "path": relative_path, "detail": "extension is not indexed"}
            )
            continue
        path = project_root / candidate
        if not path.is_file():
            diagnostics.append(
                {"code": "missing_file", "path": relative_path, "detail": "referenced file does not exist"}
            )
            continue
        try:
            with path.open("rb") as stream:
                stream.read(1)
        except OSError as exc:
            diagnostics.append({"code": "unreadable_file", "path": relative_path, "detail": str(exc)})
            continue
        valid_paths.append(relative_path)
    return {
        "enabled": media_index_enabled(),
        "dry_run": True,
        "project_id": project_id,
        "project_root": str(project_root),
        "scanned_paths": len(supported) + len(unsupported),
        "would_index_count": len(valid_paths),
        "valid_paths": valid_paths,
        "diagnostics": diagnostics,
        "reconciliation": [asdict(item) for item in project_media_catalog(project_root).reconciliation_items()],
    }


def scan_project_media_assets(project_id: str, project_root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Scan known media locations and legacy JSON references idempotently."""

    if dry_run:
        return audit_project_media_assets(project_id, project_root)
    if not media_index_enabled():
        return {
            "enabled": False,
            "project_id": project_id,
            "project_root": str(project_root),
            "scanned_paths": 0,
            "indexed_count": 0,
            "asset_count": 0,
            "diagnostics": [],
            "reconciliation": [],
        }
    catalog = project_media_catalog(project_root)
    _, manifest_errors = legacy_media_reference_report(project_root)
    for detail in manifest_errors:
        catalog.record_diagnostic(
            project_id=project_id,
            path=detail.split(":", 1)[0],
            code="unreadable_manifest",
            detail=detail,
        )
    supported, unsupported = _scan_paths(project_root)
    indexed: list[MediaAsset] = []
    for relative_path in sorted(supported):
        asset = catalog.register(
            project_id=project_id,
            path=project_root / relative_path,
            origin=_origin_for_path(relative_path),
        )
        if asset is not None:
            indexed.append(asset)
    for relative_path in sorted(unsupported):
        catalog.register(
            project_id=project_id,
            path=project_root / relative_path,
            origin="imported",
        )
    state = catalog._load()
    return {
        "enabled": True,
        "project_id": project_id,
        "project_root": str(project_root),
        "scanned_paths": len(supported) + len(unsupported),
        "indexed_count": len(indexed),
        "asset_count": len(catalog.list_assets()),
        "diagnostics": [asdict(item) for item in state.diagnostics],
        "reconciliation": [asdict(item) for item in catalog.reconciliation_items()],
    }


def retry_project_media_reconciliation(
    project_id: str, project_root: Path, item_id: str | None = None
) -> dict[str, Any]:
    if not media_index_enabled():
        return {"enabled": False, "project_id": project_id, "repaired": [], "reconciliation": []}
    catalog = project_media_catalog(project_root)
    repaired = catalog.retry_reconciliation(project_root=project_root, item_id=item_id)
    return {
        "project_id": project_id,
        "repaired": [asdict(asset) for asset in repaired],
        "reconciliation": [asdict(item) for item in catalog.reconciliation_items()],
    }
