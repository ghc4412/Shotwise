from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.project_manager import ProjectManager

pytestmark = pytest.mark.unit


def _manager(tmp_path: Path) -> ProjectManager:
    manager = ProjectManager(tmp_path / "projects")
    manager.create_project("demo")
    manager.create_project_metadata("demo", "Demo", "Anime", "narration")
    assert manager.add_character("demo", "Alice", "主角")
    return manager


def test_character_variant_lifecycle_preserves_stable_id(tmp_path: Path):
    manager = _manager(tmp_path)

    created = manager.create_character_variant(
        "demo",
        "Alice",
        "battle",
        display_name="战斗形态",
        image_path="characters/alice-battle.png",
        status="ready",
        metadata={"costume": "armor"},
    )
    variant_id = created["id"]

    assert created["slug"] == "battle"
    assert created["character_id"] == "Alice"
    assert manager.get_character_variant("demo", "Alice", variant_id)["id"] == variant_id
    assert manager.get_character_variant("demo", "Alice", "battle")["id"] == variant_id

    renamed = manager.update_character_variant("demo", "Alice", variant_id, slug="injured", status="archived")
    assert renamed["id"] == variant_id
    assert renamed["slug"] == "injured"
    assert renamed["status"] == "archived"
    with pytest.raises(KeyError):
        manager.get_character_variant("demo", "Alice", "battle")

    deleted = manager.delete_character_variant("demo", "Alice", variant_id)
    assert deleted["id"] == variant_id
    assert manager.list_character_variants("demo", "Alice") == []


def test_character_variant_rejects_duplicate_slug_and_unsafe_image(tmp_path: Path):
    manager = _manager(tmp_path)
    manager.create_character_variant("demo", "Alice", "battle")

    with pytest.raises(ValueError):
        manager.create_character_variant("demo", "Alice", "battle")

    with pytest.raises(ValueError):
        manager.create_character_variant("demo", "Alice", "safe", image_path="../outside.png")

    with pytest.raises(ValueError):
        manager.create_character_variant("demo", "Alice", "safe", status="unknown")


def test_character_variant_read_tolerates_malformed_legacy_entries(tmp_path: Path):
    manager = _manager(tmp_path)
    project = manager.load_project("demo")
    project["characters"]["Alice"]["variants"] = {
        "valid": {"id": "stable-id", "slug": "valid", "status": "ready"},
        "bad-slug": {"slug": "../escape"},
        "bad-shape": "not-an-object",
    }
    manager.save_project("demo", project)

    variants = manager.list_character_variants("demo", "Alice")

    assert variants == [
        {
            "id": "stable-id",
            "character_id": "Alice",
            "slug": "valid",
            "display_name": "valid",
            "description": "",
            "image_path": "",
            "status": "ready",
            "metadata": {},
        }
    ]


def test_character_variant_project_and_character_not_found(tmp_path: Path):
    manager = _manager(tmp_path)

    with pytest.raises(FileNotFoundError):
        manager.list_character_variants("missing", "Alice")
    with pytest.raises(KeyError):
        manager.list_character_variants("demo", "Missing")
    with pytest.raises(KeyError):
        manager.get_character_variant("demo", "Alice", "missing")


def test_character_variant_persists_in_project_json(tmp_path: Path):
    manager = _manager(tmp_path)
    manager.create_character_variant("demo", "Alice", "casual", description="日常")

    payload = json.loads((manager.get_project_path("demo") / "project.json").read_text(encoding="utf-8"))

    assert payload["characters"]["Alice"]["variants"]["casual"]["description"] == "日常"
