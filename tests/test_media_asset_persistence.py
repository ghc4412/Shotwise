from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import lib.db.models  # noqa: F401
from lib.db.base import Base
from lib.db.models.media_asset import MediaAsset as MediaAssetRow
from lib.db.models.media_asset import MediaBinding as MediaBindingRow
from lib.db.models.media_asset import MediaDerivation as MediaDerivationRow
from lib.media_catalog import MediaCatalog
from server.services.media_assets import sync_project_media_catalog

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_media_catalog_sync_to_database_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")
    root = tmp_path / "project"
    root.mkdir(parents=True)
    image = root / "images" / "hero.png"
    video = root / "videos" / "hero.mp4"
    image.parent.mkdir(parents=True)
    video.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    video.write_bytes(b"video")
    catalog = MediaCatalog(root / ".media-assets.json")
    parent = catalog.register(project_id="project-1", path=image, origin="upload")
    child = catalog.register(project_id="project-1", path=video, origin="generated", workflow_run_id="run-1")
    assert parent is not None and child is not None
    catalog.bind(parent.id, project_id="project-1", binding_kind="character", target_id="hero", purpose="reference")
    catalog.derive(parent.id, child.id, "generated")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        first = await sync_project_media_catalog(session=session, project_id="project-1", project_root=root)
        second = await sync_project_media_catalog(session=session, project_id="project-1", project_root=root)
        assert first == second == {"enabled": True, "assets": 2, "bindings": 1, "derivations": 1}
        assert len((await session.execute(select(MediaAssetRow))).scalars().all()) == 2
        assert len((await session.execute(select(MediaBindingRow))).scalars().all()) == 1
        assert len((await session.execute(select(MediaDerivationRow))).scalars().all()) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_media_catalog_sync_is_project_scoped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")
    root = tmp_path / "project"
    root.mkdir(parents=True)
    first_path = root / "first.png"
    second_path = root / "second.png"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    catalog = MediaCatalog(root / ".media-assets.json")
    first = catalog.register(project_id="project-1", path=first_path, origin="upload")
    second = catalog.register(project_id="project-2", path=second_path, origin="upload")
    assert first is not None and second is not None

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await sync_project_media_catalog(session=session, project_id="project-1", project_root=root)
        assert result["assets"] == 1
        rows = (await session.execute(select(MediaAssetRow))).scalars().all()
        assert [row.id for row in rows] == [first.id]
    await engine.dispose()


@pytest.mark.asyncio
async def test_database_sync_failure_keeps_reconciliation_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SHOTWISE_MEDIA_ASSET_INDEX", "1")
    root = tmp_path / "project"
    root.mkdir(parents=True)

    class FailingSession:
        async def commit(self):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await sync_project_media_catalog(session=FailingSession(), project_id="project-1", project_root=root)

    items = MediaCatalog(root / ".media-assets.json").reconciliation_items()
    assert len(items) == 1
    assert items[0].operation == "database_sync"
    assert "database unavailable" in items[0].reason
