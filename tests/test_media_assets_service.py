from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from pathlib import Path

from lib.media_catalog import MediaAssetReferencedError, MediaCatalog
from server.services.media_assets import delete_project_media_asset, register_media_asset


def test_registration_is_disabled_without_feature_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SHOTWISE_MEDIA_ASSET_INDEX", raising=False)
    root = tmp_path / "demo"
    path = root / "uploads" / "image.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"image")

    assert (
        register_media_asset(project_id="demo", project_root=root, relative_path="uploads/image.png", origin="upload")
        is None
    )
    assert not (root / ".media-assets.json").exists()


def test_registration_preserves_existing_path_when_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")
    root = tmp_path / "demo"
    path = root / "generated" / "clip.mp4"
    path.parent.mkdir(parents=True)
    original = b"video"
    path.write_bytes(original)

    asset = register_media_asset(
        project_id="demo",
        project_root=root,
        relative_path="generated/clip.mp4",
        origin="generated",
        workflow_run_id="run-1",
    )

    assert asset is not None
    assert asset.physical_path == str(path)
    assert asset.workflow_run_id == "run-1"
    assert path.read_bytes() == original


def test_registration_rejects_path_escape(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")

    try:
        register_media_asset(project_id="demo", project_root=tmp_path, relative_path="../outside.png", origin="upload")
    except ValueError as exc:
        assert "inside the project root" in str(exc)
    else:
        raise AssertionError("path traversal must be rejected")


def test_delete_rejects_legacy_project_reference(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    path = root / "uploads" / "image.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"image")
    (root / "project.json").write_text('{"reference": "uploads/image.png"}', encoding="utf-8")
    asset = MediaCatalog(root / ".media-assets.json").register(project_id="demo", path=path, origin="upload")
    assert asset is not None

    with pytest.raises(MediaAssetReferencedError, match="legacy_reference"):
        delete_project_media_asset(project_root=root, media_asset_id=asset.id)
    assert path.read_bytes() == b"image"
