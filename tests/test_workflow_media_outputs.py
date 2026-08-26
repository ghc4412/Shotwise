from __future__ import annotations

from pathlib import Path

import pytest

from lib.media_catalog import project_media_catalog
from server.services.media_assets import index_workflow_outputs, register_media_asset
from server.services.workflow_execution import AssetRef

pytestmark = pytest.mark.unit


def test_workflow_output_is_indexed_bound_derived_and_keeps_legacy_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")
    source = tmp_path / "images" / "source.png"
    output = tmp_path / "videos" / "result.mp4"
    source.parent.mkdir()
    output.parent.mkdir()
    source.write_bytes(b"source")
    output.write_bytes(b"result")
    parent = register_media_asset(
        project_id="project-1",
        project_root=tmp_path,
        relative_path="images/source.png",
        origin="upload",
    )
    assert parent is not None
    refs = {"video": [AssetRef(kind="video", path="videos/result.mp4", label="shot-1")]}
    indexed = index_workflow_outputs(
        project_id="project-1",
        project_root=tmp_path,
        workflow_run_id="run-1",
        workflow_node_key="video",
        outputs=refs,
        parent_media_asset_ids=[parent.id],
    )
    output_ref = indexed["video"][0]
    assert output_ref.path == "videos/result.mp4"
    assert output_ref.media_asset_id
    catalog = project_media_catalog(tmp_path)
    assert catalog.bindings_for(output_ref.media_asset_id)
    derivations = catalog.derivations_for(output_ref.media_asset_id)
    assert derivations and derivations[0].parent_media_asset_id == parent.id


def test_workflow_output_registration_failure_is_reconciled_without_deleting_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")
    output = tmp_path / "videos" / "result.mp4"
    output.parent.mkdir()
    output.write_bytes(b"result")

    def fail_registration(**_kwargs):
        raise OSError("index unavailable")

    monkeypatch.setattr("server.services.media_assets.register_media_asset", fail_registration)
    refs = {"video": [AssetRef(kind="video", path="videos/result.mp4")]}
    indexed = index_workflow_outputs(
        project_id="project-1",
        project_root=tmp_path,
        workflow_run_id="run-1",
        workflow_node_key="video",
        outputs=refs,
    )
    assert indexed["video"][0].path == "videos/result.mp4"
    assert indexed["video"][0].media_asset_id is None
    assert output.exists()
    catalog = project_media_catalog(tmp_path)
    assert len(catalog.reconciliation_items()) == 1


def test_workflow_binding_failure_retries_against_registered_asset(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")
    output = tmp_path / "videos" / "result.mp4"
    output.parent.mkdir()
    output.write_bytes(b"result")
    original_bind = type(project_media_catalog(tmp_path)).bind
    calls = 0

    def fail_once(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("binding unavailable")
        return original_bind(self, *args, **kwargs)

    monkeypatch.setattr("lib.media_catalog.MediaCatalog.bind", fail_once)
    refs = {"video": [AssetRef(kind="video", path="videos/result.mp4")]}
    indexed = index_workflow_outputs(
        project_id="project-1",
        project_root=tmp_path,
        workflow_run_id="run-1",
        workflow_node_key="video",
        outputs=refs,
    )
    asset_id = indexed["video"][0].media_asset_id
    assert asset_id
    catalog = project_media_catalog(tmp_path)
    pending = catalog.reconciliation_items()
    assert len(pending) == 1
    assert pending[0].operation == "binding"
    assert pending[0].media_asset_id == asset_id

    monkeypatch.setattr("lib.media_catalog.MediaCatalog.bind", original_bind)
    repaired = catalog.retry_reconciliation(project_root=tmp_path)
    assert [asset.id for asset in repaired] == [asset_id]
    assert catalog.reconciliation_items() == []
    assert catalog.bindings_for(asset_id)
