"""Generation-time validation for referenced project assets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.asset_types import ASSET_SPECS, normalize_asset_bucket, normalize_asset_name, resolve_asset_key
from lib.character_variants import find_character_variant, split_character_variant_mention
from lib.path_safety import safe_exists


@dataclass(frozen=True)
class AssetPreflightResult:
    """Stable, user-presentable result of generation asset validation."""

    unregistered: tuple[str, ...] = ()
    missing_images: tuple[str, ...] = ()
    missing_variants: tuple[str, ...] = ()

    @property
    def has_errors(self) -> bool:
        return bool(self.unregistered or self.missing_images or self.missing_variants)


def _label(asset_type: str, name: str) -> str:
    return f"{asset_type}:{name}"


def collect_item_references(
    item: dict[str, Any],
    *,
    char_field: str | None,
    scene_field: str,
    prop_field: str,
    include_products: bool = False,
) -> list[tuple[str, str]]:
    """Collect typed asset references from a storyboard or ad shot item."""
    fields: list[tuple[str, str | None]] = [
        ("character", char_field),
        ("scene", scene_field),
        ("prop", prop_field),
    ]
    if include_products:
        fields.append(("product", "products_in_shot"))

    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for asset_type, field in fields:
        if not field:
            continue
        values = item.get(field)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            name = normalize_asset_name(value)
            key = (asset_type, name)
            if key not in seen:
                seen.add(key)
                references.append(key)
    return references


def validate_asset_references(
    project: dict[str, Any],
    project_path: Path,
    references: Iterable[tuple[str, str]],
    *,
    require_sheet_images: bool = True,
) -> AssetPreflightResult:
    """Check registration and usable sheet files for typed asset references.

    ``require_sheet_images=False`` still reports unregistered names and unknown
    character variants, but accepts a registered asset whose sheet file is absent
    or unreadable. Ad units degrade by skipping such references at generation time
    (``ref_ad_reference_skipped``) instead of failing the whole unit.
    """
    buckets = {key: normalize_asset_bucket(project.get(spec.bucket_key)) for key, spec in ASSET_SPECS.items()}
    unregistered: list[str] = []
    missing_images: list[str] = []
    missing_variants: list[str] = []
    seen_unregistered: set[str] = set()
    seen_missing: set[str] = set()
    seen_variants: set[str] = set()

    for asset_type, raw_name in references:
        spec = ASSET_SPECS.get(asset_type)
        if spec is None or not isinstance(raw_name, str) or not raw_name.strip():
            continue
        name = normalize_asset_name(raw_name)
        character_name, variant_identifier = (
            split_character_variant_mention(name) if asset_type == "character" else (name, None)
        )
        if variant_identifier is not None:
            label = _label(asset_type, name)
            character_key = resolve_asset_key(buckets["character"], character_name)
            if character_key is None:
                if label not in seen_unregistered:
                    seen_unregistered.add(label)
                    unregistered.append(label)
                continue
            character = buckets["character"][character_key]
            variant = find_character_variant(character, character_key, variant_identifier)
            if variant is None:
                if label not in seen_variants:
                    seen_variants.add(label)
                    missing_variants.append(label)
                continue
            if require_sheet_images:
                image_path = variant.get("image_path") if isinstance(variant, dict) else None
                if not isinstance(image_path, str) or not image_path or not safe_exists(project_path, image_path):
                    if label not in seen_missing:
                        seen_missing.add(label)
                        missing_images.append(label)
            continue
        label = _label(asset_type, name)
        asset_key = resolve_asset_key(buckets[asset_type], name)
        if asset_key is None:
            if label not in seen_unregistered:
                seen_unregistered.add(label)
                unregistered.append(label)
            continue

        if require_sheet_images:
            entry = buckets[asset_type][asset_key]
            sheet = entry.get(spec.sheet_field) if isinstance(entry, dict) else None
            if not isinstance(sheet, str) or not sheet or not safe_exists(project_path, sheet):
                if label not in seen_missing:
                    seen_missing.add(label)
                    missing_images.append(label)

    return AssetPreflightResult(tuple(unregistered), tuple(missing_images), tuple(missing_variants))


def collect_reference_entries(entries: object) -> list[tuple[str, str]]:
    """Collect typed references from ``[{"type": ..., "name": ...}]`` data."""
    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if not isinstance(entries, list):
        return references
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        asset_type = entry.get("type")
        name = entry.get("name")
        if not isinstance(asset_type, str) or not isinstance(name, str) or not name.strip():
            continue
        key = (asset_type, normalize_asset_name(name))
        if key not in seen:
            seen.add(key)
            references.append(key)
    return references


def collect_ad_shot_references(shots: object) -> list[tuple[str, str]]:
    """Collect ad references from the authoritative shot fields, not unit caches."""
    references: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    fields = (
        ("product", "products_in_shot"),
        ("character", "characters_in_shot"),
        ("scene", "scenes"),
        ("prop", "props"),
    )
    if not isinstance(shots, list):
        return references
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        for asset_type, field in fields:
            values = shot.get(field)
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    continue
                key = (asset_type, normalize_asset_name(value))
                if key not in seen:
                    seen.add(key)
                    references.append(key)
    return references


def merge_preflight_results(*results: AssetPreflightResult) -> AssetPreflightResult:
    """Merge results while preserving first-seen order and removing duplicates."""
    unregistered: list[str] = []
    missing_images: list[str] = []
    missing_variants: list[str] = []
    for result in results:
        for value in result.unregistered:
            if value not in unregistered:
                unregistered.append(value)
        for value in result.missing_images:
            if value not in missing_images:
                missing_images.append(value)
        for value in result.missing_variants:
            if value not in missing_variants:
                missing_variants.append(value)
    return AssetPreflightResult(tuple(unregistered), tuple(missing_images), tuple(missing_variants))


def format_preflight_error(result: AssetPreflightResult) -> str | None:
    """Return a stable, user-facing error string, or ``None`` when validation passes."""
    if not result.has_errors:
        return None
    return (
        "生成前检查失败。未登记资产："
        f"{', '.join(result.unregistered) or '—'}；缺少资产图："
        f"{', '.join(result.missing_images) or '—'}；缺少角色衍生形态："
        f"{', '.join(result.missing_variants) or '—'}"
    )


def validate_item_asset_references(
    project: dict[str, Any],
    project_path: Path,
    item: dict[str, Any],
    *,
    char_field: str | None,
    scene_field: str,
    prop_field: str,
    include_products: bool = False,
) -> AssetPreflightResult:
    """Validate all typed assets declared by one storyboard/ad shot."""
    return validate_asset_references(
        project,
        project_path,
        collect_item_references(
            item,
            char_field=char_field,
            scene_field=scene_field,
            prop_field=prop_field,
            include_products=include_products,
        ),
    )
