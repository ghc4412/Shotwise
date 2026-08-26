from __future__ import annotations

from pathlib import Path

import pytest

from lib.media_catalog import MediaAssetReferencedError, MediaCatalog
from server.services.media_assets import list_project_media_assets

pytestmark = pytest.mark.unit


def _asset(catalog: MediaCatalog, root: Path, name: str = "image.png"):
    path = root / name
    path.write_bytes(b"image")
    return catalog.register(project_id="project-1", path=path, origin="generated")


def test_media_library_filters_and_keeps_semantic_references(tmp_path: Path):
    catalog = MediaCatalog(tmp_path / "media-index.json")
    first = _asset(catalog, tmp_path, "first.png")
    second = _asset(catalog, tmp_path, "second.png")
    catalog.bind(
        media_asset_id=first.id,
        project_id="project-1",
        binding_kind="shot",
        target_id="shot-1",
        purpose="storyboard",
    )

    assert [asset.id for asset in catalog.list_assets(kind="image")] == [second.id, first.id]
    with pytest.raises(MediaAssetReferencedError):
        catalog.delete(first.id)
    deleted = catalog.delete(second.id)
    assert deleted.id == second.id
    assert second.id not in {asset.id for asset in catalog.list_assets()}


def test_register_same_path_and_content_is_idempotent(tmp_path: Path):
    catalog = MediaCatalog(tmp_path / "media-index.json")
    first = _asset(catalog, tmp_path, "same.png")
    second = _asset(catalog, tmp_path, "same.png")

    assert second.id == first.id
    assert [asset.id for asset in catalog.list_assets(kind="image")] == [first.id]


def test_binding_cannot_cross_project_boundary(tmp_path: Path):
    catalog = MediaCatalog(tmp_path / "media-index.json")
    asset = _asset(catalog, tmp_path)

    with pytest.raises(KeyError):
        catalog.bind(
            asset.id,
            project_id="other-project",
            binding_kind="shot",
            target_id="shot-1",
            purpose="storyboard",
        )

    assert catalog.bindings_for(asset.id) == []


def test_media_library_list_is_scoped_to_project_id(tmp_path: Path):
    catalog = MediaCatalog(tmp_path / ".media-assets.json")
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    first = catalog.register(project_id="project-1", path=first_path, origin="upload")
    second = catalog.register(project_id="project-2", path=second_path, origin="upload")
    assert first is not None and second is not None

    result = list_project_media_assets(project_id="project-1", project_root=tmp_path)

    assert [item["id"] for item in result["items"]] == [first.id]
