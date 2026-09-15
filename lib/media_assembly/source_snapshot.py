"""Canonical source snapshots for media assembly plans."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_source_snapshot(*, project_name: str, source_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a live project/media manifest into a stable JSON document.

    Unknown fields are retained for compatibility with older source snapshots.
    Missing fields stay explicit instead of being replaced with invented values.
    """
    result = {key: value for key, value in source_manifest.items()}
    items = source_manifest.get("items", [])
    if not isinstance(items, list):
        items = []
    result.update(
        {
            "snapshot_version": "media-assembly-source/v1",
            "project": {"name": project_name},
            "script": source_manifest.get("script"),
            "episode": source_manifest.get("episode"),
            "content_mode": source_manifest.get("content_mode"),
            "generation_mode": source_manifest.get("generation_mode"),
            "collection": source_manifest.get("collection"),
            "manifest_contract_version": source_manifest.get("contract_version"),
            "manifest_fingerprint": source_manifest.get("fingerprint"),
            "items": [_snapshot_item(item) for item in items if isinstance(item, Mapping)],
        }
    )
    return result


def _snapshot_item(item: Mapping[str, Any]) -> dict[str, Any]:
    source = item.get("source")
    if not isinstance(source, Mapping):
        source = {}
    media_probe = item.get("media_probe")
    if not isinstance(media_probe, Mapping):
        media_probe = {}
    file_fingerprint = item.get("file_fingerprint")
    if not isinstance(file_fingerprint, Mapping):
        file_fingerprint = {
            "exists": media_probe.get("exists", False),
            "size": None,
            "mtime_ns": None,
            "sha256": None,
        }
    return {
        "order": item.get("order"),
        "unit_id": item.get("unit_id"),
        "description": item.get("description"),
        "references": item.get("references", []),
        "planned_duration_seconds": item.get("planned_duration_seconds"),
        "asset_status": item.get("asset_status"),
        "source": {"kind": source.get("kind"), "path": source.get("path")},
        "version": item.get("version"),
        "file_fingerprint": dict(file_fingerprint),
        "media_probe": dict(media_probe),
    }


__all__ = ["build_source_snapshot"]
