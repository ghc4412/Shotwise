"""Stable character-variant helpers shared by project storage and reference parsing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from lib.asset_types import normalize_asset_name, validate_asset_name

VARIANT_STATUSES = frozenset({"draft", "ready", "missing", "archived"})


def validate_variant_slug(slug: object) -> str:
    """Validate a variant slug as a single safe mention/path component."""
    return validate_asset_name(slug)


def new_variant_id() -> str:
    return str(uuid4())


def normalize_variant(raw: object, character_id: str, slug: str | None = None) -> dict[str, Any] | None:
    """Return a normalized variant record, or ``None`` for malformed legacy data."""
    if not isinstance(raw, Mapping):
        return None
    raw_slug = raw.get("slug") if "slug" in raw else slug
    if not isinstance(raw_slug, str):
        return None
    try:
        clean_slug = validate_variant_slug(raw_slug)
        if slug is not None and validate_variant_slug(slug) != clean_slug:
            return None
    except ValueError:
        return None
    variant_id = raw.get("id")
    if not isinstance(variant_id, str) or not variant_id.strip():
        variant_id = new_variant_id()
    status = raw.get("status", "draft")
    if status not in VARIANT_STATUSES:
        status = "draft"
    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    image_path = raw.get("image_path", "")
    if not isinstance(image_path, str):
        image_path = ""
    image_asset_id = raw.get("image_asset_id")
    result: dict[str, Any] = {
        "id": variant_id,
        "character_id": character_id,
        "slug": clean_slug,
        "display_name": raw.get("display_name") if isinstance(raw.get("display_name"), str) else clean_slug,
        "description": raw.get("description") if isinstance(raw.get("description"), str) else "",
        "image_path": image_path,
        "status": status,
        "metadata": dict(metadata),
    }
    if isinstance(image_asset_id, str) and image_asset_id:
        result["image_asset_id"] = image_asset_id
    return result


def iter_character_variants(character: object, character_id: str) -> list[dict[str, Any]]:
    """Read the dict-shaped variant collection while tolerating malformed legacy values."""
    if not isinstance(character, Mapping):
        return []
    raw_variants = character.get("variants")
    if not isinstance(raw_variants, Mapping):
        return []
    result: list[dict[str, Any]] = []
    for slug, raw in raw_variants.items():
        item = normalize_variant(raw, character_id, slug if isinstance(slug, str) else None)
        if item is not None:
            result.append(item)
    return result


def find_character_variant(character: object, character_id: str, identifier: str) -> dict[str, Any] | None:
    """Find by stable id first, then by slug."""
    target = normalize_asset_name(identifier)
    for variant in iter_character_variants(character, character_id):
        if variant["id"] == identifier or normalize_asset_name(str(variant["slug"])) == target:
            return variant
    return None


def split_character_variant_mention(name: str) -> tuple[str, str | None]:
    """Split ``角色/衍生slug``; only one slash is meaningful to the mention grammar."""
    if "/" not in name:
        return name, None
    character_name, slug = name.split("/", 1)
    if not character_name or not slug or "/" in slug:
        return name, None
    return character_name, slug
