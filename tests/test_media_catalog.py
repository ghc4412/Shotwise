from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import json
from pathlib import Path

from lib.media_catalog import MediaCatalog, classify_media_path
from server.services.media_indexing import (
    audit_project_media_assets,
    legacy_media_asset_references,
    legacy_media_references,
)


def test_backfill_is_idempotent_and_does_not_change_media_file(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    source = root / "characters" / "hero.png"
    source.parent.mkdir(parents=True)
    content = b"fixture-media"
    source.write_bytes(content)
    catalog = MediaCatalog(root / ".media-assets.json")

    first = catalog.backfill(project_id="demo", project_root=root, relative_paths=["characters/hero.png"])
    second = catalog.backfill(project_id="demo", project_root=root, relative_paths=["characters/hero.png"])

    assert len(first) == len(second) == 1
    assert first[0].id == second[0].id
    assert source.read_bytes() == content
    assert first[0].physical_path == str(source)


def test_media_asset_bindings_and_derivations_are_queryable(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    image = root / "uploads" / "reference.webp"
    video = root / "generated" / "clip.mp4"
    image.parent.mkdir(parents=True)
    video.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    video.write_bytes(b"video")
    catalog = MediaCatalog(root / ".media-assets.json")
    parent = catalog.register(project_id="demo", path=image, origin="upload")
    child = catalog.register(project_id="demo", path=video, origin="generated", workflow_run_id="run-1")
    assert parent is not None and child is not None

    binding = catalog.bind(
        parent.id, project_id="demo", binding_kind="character", target_id="hero", purpose="reference"
    )
    derivation = catalog.derive(parent.id, child.id, "generated")

    assert catalog.get(parent.id) == parent
    assert catalog.bindings_for(parent.id) == [binding]
    assert catalog.derivations_for(child.id) == [derivation]


def test_backfill_reports_missing_and_escaping_paths_without_deleting_anything(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    catalog = MediaCatalog(root / ".media-assets.json")

    assert (
        catalog.backfill(project_id="demo", project_root=root, relative_paths=["missing.mp4", "../outside.png"]) == []
    )
    assert {item.code for item in catalog._load().diagnostics} == {"missing_file", "invalid_reference"}


def test_register_reports_unreadable_file_without_raising(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    path = root / "broken.png"
    path.write_bytes(b"image")
    catalog = MediaCatalog(root / ".media-assets.json")

    monkeypatch.setattr("lib.media_catalog._fingerprint", lambda _path: (_ for _ in ()).throw(OSError("denied")))

    assert catalog.register(project_id="demo", path=path, origin="imported") is None
    diagnostics = catalog.diagnostics()
    assert diagnostics[-1].code == "unreadable_file"
    assert "denied" in diagnostics[-1].detail


def test_legacy_media_reference_scan_does_not_treat_documents_as_media(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    (root / "scripts").mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"characters": {"Hero": {"sheet": "characters/hero.png"}}, "source": "source/book.pdf"}),
        encoding="utf-8",
    )
    (root / "scripts" / "episode_1.json").write_text(
        json.dumps({"scenes": [{"generated_assets": {"video_clip": "videos/shot.mp4"}}]}), encoding="utf-8"
    )

    assert legacy_media_references(root) == {"characters/hero.png", "videos/shot.mp4"}
    assert classify_media_path("source/book.pdf") is None


def test_legacy_reference_lookup_reports_references_and_manifest_errors(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    source = root / "characters" / "hero.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"hero")
    (root / "project.json").write_text(json.dumps({"hero": "characters/hero.png"}), encoding="utf-8")

    references, errors = legacy_media_asset_references(root, str(source))
    assert references == ["characters/hero.png"]
    assert errors == []

    (root / "scripts").mkdir()
    (root / "scripts" / "broken.json").write_text("{", encoding="utf-8")
    references, errors = legacy_media_asset_references(root, str(source))
    assert references == ["characters/hero.png"]
    assert errors and "broken.json" in errors[0]


def test_media_audit_is_dry_run_and_reports_candidates(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SHOTWISE_MEDIA_ASSET_INDEX", raising=False)
    root = tmp_path / "demo"
    (root / "uploads").mkdir(parents=True)
    (root / "uploads" / "note.txt").write_text("not media", encoding="utf-8")
    (root / "uploads" / "image.png").write_bytes(b"image")
    (root / "project.json").write_text(json.dumps({"missing": "uploads/missing.mp4"}), encoding="utf-8")

    report = audit_project_media_assets("demo", root)

    assert report["dry_run"] is True
    assert report["enabled"] is False
    assert report["would_index_count"] == 1
    assert {item["code"] for item in report["diagnostics"]} >= {"missing_file", "unsupported_media"}
    assert not (root / ".media-assets.json").exists()
