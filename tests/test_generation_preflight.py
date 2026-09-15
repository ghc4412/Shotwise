from pathlib import Path

import pytest

from lib.generation_preflight import collect_item_references, validate_asset_references

pytestmark = pytest.mark.unit


def _project() -> dict:
    return {
        "characters": {
            "Alice": {
                "character_sheet": "characters/Alice.png",
                "variants": {
                    "armor": {"id": "variant-armor", "slug": "armor", "image_path": "characters/Alice-armor.png"},
                    "draft": {"id": "variant-draft", "slug": "draft", "image_path": ""},
                },
            },
            "Híếu": {"character_sheet": "characters/Híếu.png"},
        },
        "scenes": {"祠堂": {"scene_sheet": "scenes/祠堂.png"}},
        "props": {"玉佩": {"prop_sheet": "props/玉佩.png"}},
        "products": {"保温杯": {"product_sheet": "products/保温杯.png"}},
    }


def test_collect_item_references_deduplicates_in_stable_order():
    refs = collect_item_references(
        {
            "characters_in_segment": ["Alice", "Alice"],
            "scenes": ["祠堂"],
            "props": ["玉佩", "玉佩"],
            "products_in_shot": ["保温杯"],
        },
        char_field="characters_in_segment",
        scene_field="scenes",
        prop_field="props",
        include_products=True,
    )
    assert refs == [
        ("character", "Alice"),
        ("scene", "祠堂"),
        ("prop", "玉佩"),
        ("product", "保温杯"),
    ]


def test_validate_asset_references_reports_unregistered_before_missing(tmp_path: Path):
    project = _project()
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "Alice.png").write_bytes(b"png")
    result = validate_asset_references(
        project,
        tmp_path,
        [
            ("character", "未登记角色"),
            ("character", "Alice"),
            ("scene", "祠堂"),
            ("prop", "玉佩"),
            ("product", "保温杯"),
        ],
    )
    assert result.unregistered == ("character:未登记角色",)
    assert result.missing_images == (
        "scene:祠堂",
        "prop:玉佩",
        "product:保温杯",
    )


def test_validate_asset_references_accepts_existing_files_and_normalizes_unicode(tmp_path: Path):
    project = _project()
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "Híếu.png").write_bytes(b"png")
    result = validate_asset_references(project, tmp_path, [("character", "Híếu")])
    assert not result.has_errors


def test_validate_asset_references_rejects_empty_or_unsafe_sheet(tmp_path: Path):
    project = _project()
    project["characters"]["Alice"]["character_sheet"] = ""
    project["scenes"]["祠堂"]["scene_sheet"] = "../outside.png"
    result = validate_asset_references(
        project,
        tmp_path,
        [("character", "Alice"), ("scene", "祠堂")],
    )
    assert result.missing_images == ("character:Alice", "scene:祠堂")


def test_validate_asset_references_checks_character_variants_by_slug_and_id(tmp_path: Path):
    project = _project()
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "Alice-armor.png").write_bytes(b"png")
    result = validate_asset_references(
        project,
        tmp_path,
        [
            ("character", "Alice/armor"),
            ("character", "Alice/variant-armor"),
            ("character", "Alice/draft"),
            ("character", "Alice/unknown"),
        ],
    )
    assert result.unregistered == ()
    assert result.missing_images == ("character:Alice/draft",)
    assert result.missing_variants == ("character:Alice/unknown",)


def test_validate_asset_references_rejects_variant_path_traversal(tmp_path: Path):
    project = _project()
    project["characters"]["Alice"]["variants"]["armor"]["image_path"] = "../outside.png"
    result = validate_asset_references(project, tmp_path, [("character", "Alice/armor")])
    assert result.missing_images == ("character:Alice/armor",)


def test_validate_asset_references_can_tolerate_missing_sheet_images(tmp_path: Path):
    """ad 单元缺图按软口径跳过，准入复检只硬拦未登记名与缺失变体。"""
    project = _project()
    result = validate_asset_references(
        project,
        tmp_path,
        [
            ("character", "Alice"),
            ("character", "Alice/draft"),
            ("character", "Alice/unknown"),
            ("product", "保温杯"),
            ("character", "未登记角色"),
        ],
        require_sheet_images=False,
    )
    assert result.unregistered == ("character:未登记角色",)
    assert result.missing_images == ()
    assert result.missing_variants == ("character:Alice/unknown",)
