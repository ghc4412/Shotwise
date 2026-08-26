from __future__ import annotations

from typing import Any, cast

import pytest

from server.services import creative_boards as service

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_board_keeps_semantic_edges_separate_from_execution(async_session):
    board = await service.create_board(
        async_session,
        user_id="user-1",
        project_id="project-1",
        name="Episode references",
        viewport={"x": 10, "y": 20, "zoom": 0.8},
    )
    first = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="character",
        resource_type="media_asset",
        resource_id="asset-character",
    )
    second = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="shot",
        resource_type="shot",
        resource_id="shot-1",
    )
    edge = await service.add_edge(
        async_session,
        str(board["id"]),
        user_id="user-1",
        source_item_id=str(first["id"]),
        target_item_id=str(second["id"]),
        relation="reference",
    )
    loaded = cast(dict[str, Any], await service.get_board(async_session, str(board["id"]), user_id="user-1"))
    assert loaded["viewport"] == {"x": 10, "y": 20, "zoom": 0.8}
    assert loaded["edges"][0]["relation"] == "reference"
    assert "executor_id" not in loaded["edges"][0]
    assert edge["relation"] == "reference"


@pytest.mark.asyncio
async def test_board_rejects_execution_edges_and_does_not_cross_user_boundary(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    with pytest.raises(service.CreativeBoardValidationError):
        await service.add_item(
            async_session,
            str(board["id"]),
            user_id="user-1",
            item_type="unknown_node",
            resource_type="workflow",
            resource_id="run-1",
        )
    with pytest.raises(service.CreativeBoardNotFoundError):
        await service.get_board(async_session, str(board["id"]), user_id="user-2")


@pytest.mark.asyncio
async def test_deleting_board_item_only_removes_board_data(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    item = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="media",
        resource_type="media_asset",
        resource_id="asset-1",
    )
    result = await service.delete_item(async_session, str(board["id"]), str(item["id"]), user_id="user-1")
    assert result["deleted"] is True
    loaded = await service.get_board(async_session, str(board["id"]), user_id="user-1")
    assert loaded["items"] == []


@pytest.mark.asyncio
async def test_board_update_with_expected_revision_advances_revision(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")

    updated = await service.update_board(
        async_session,
        str(board["id"]),
        user_id="user-1",
        name="Renamed board",
        viewport={"x": 12, "y": 24, "zoom": 1.2},
        display_settings={"theme": "dark"},
        expected_revision=board["revision"],
    )

    assert updated["name"] == "Renamed board"
    assert updated["viewport"] == {"x": 12, "y": 24, "zoom": 1.2}
    assert updated["display_settings"] == {"theme": "dark"}
    assert updated["revision"] == board["revision"] + 1
    assert updated["updated_at"]


@pytest.mark.asyncio
async def test_board_update_rejects_stale_revision_without_overwriting(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    first_update = await service.update_board(
        async_session,
        str(board["id"]),
        user_id="user-1",
        name="Newer name",
        expected_revision=board["revision"],
    )

    with pytest.raises(service.CreativeBoardConflictError) as error:
        await service.update_board(
            async_session,
            str(board["id"]),
            user_id="user-1",
            name="Stale name",
            expected_revision=board["revision"],
        )

    assert error.value.current_revision == first_update["revision"]
    assert error.value.current_updated_at.isoformat() == first_update["updated_at"]
    current = await service.get_board(async_session, str(board["id"]), user_id="user-1")
    assert current["name"] == "Newer name"
    assert current["revision"] == first_update["revision"]


@pytest.mark.asyncio
async def test_board_update_without_revision_remains_backward_compatible(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")

    updated = await service.update_board(
        async_session,
        str(board["id"]),
        user_id="user-1",
        name="Legacy client update",
    )

    assert updated["name"] == "Legacy client update"
    assert updated["revision"] == board["revision"] + 1
    assert updated["updated_at"]


@pytest.mark.asyncio
async def test_item_update_rejects_stale_board_revision(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    item = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="media",
        resource_type="media_asset",
        resource_id="asset-1",
        expected_revision=board["revision"],
    )
    current = await service.get_board(async_session, str(board["id"]), user_id="user-1")
    await service.update_board(
        async_session,
        str(board["id"]),
        user_id="user-1",
        name="Newer name",
        expected_revision=current["revision"],
    )

    with pytest.raises(service.CreativeBoardConflictError):
        await service.update_item(
            async_session,
            str(board["id"]),
            str(item["id"]),
            user_id="user-1",
            position={"x": 99, "y": 99},
            expected_revision=item["revision"],
        )

    loaded = await service.get_board(async_session, str(board["id"]), user_id="user-1")
    assert loaded["name"] == "Newer name"
    assert loaded["items"][0]["position"] == {"x": 0, "y": 0}


@pytest.mark.asyncio
async def test_board_update_revision_conflict_is_returned_as_http_409(async_session):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from server.routers.creative_boards import BoardUpdateRequest
    from server.routers.creative_boards import update_board as update_board_route

    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    current = await service.update_board(
        async_session,
        str(board["id"]),
        user_id="user-1",
        name="Newer name",
        expected_revision=board["revision"],
    )

    with pytest.raises(HTTPException) as error:
        await update_board_route(
            str(board["id"]),
            BoardUpdateRequest(name="Stale name", expected_revision=board["revision"]),
            SimpleNamespace(id="user-1"),
            async_session,
        )

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "creative_board_revision_conflict",
        "current_revision": current["revision"],
        "current_updated_at": current["updated_at"],
    }


@pytest.mark.asyncio
async def test_item_group_id_can_be_set_and_cleared_with_revision(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    item = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="scene",
        resource_type="scene",
        resource_id="scene-1",
        expected_revision=board["revision"],
    )

    grouped = await service.update_item(
        async_session,
        str(board["id"]),
        str(item["id"]),
        user_id="user-1",
        group_id="group-1",
        update_group_id=True,
        expected_revision=item["revision"],
    )
    assert grouped["revision"] == item["revision"] + 1
    assert grouped["items"][0]["group_id"] == "group-1"

    cleared = await service.update_item(
        async_session,
        str(board["id"]),
        str(item["id"]),
        user_id="user-1",
        group_id=None,
        update_group_id=True,
        expected_revision=grouped["revision"],
    )
    assert cleared["revision"] == grouped["revision"] + 1
    assert cleared["items"][0]["group_id"] is None


@pytest.mark.asyncio
async def test_delete_item_stale_revision_rolls_back(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    item = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="scene",
        resource_type="scene",
        resource_id="scene-1",
        expected_revision=board["revision"],
    )

    with pytest.raises(service.CreativeBoardConflictError) as conflict:
        await service.delete_item(
            async_session,
            str(board["id"]),
            str(item["id"]),
            user_id="user-1",
            expected_revision=board["revision"],
        )

    assert conflict.value.current_revision == item["revision"]
    unchanged = await service.get_board(async_session, str(board["id"]), user_id="user-1")
    assert unchanged["revision"] == item["revision"]
    assert len(unchanged["items"]) == 1

    deleted = await service.delete_item(
        async_session,
        str(board["id"]),
        str(item["id"]),
        user_id="user-1",
        expected_revision=item["revision"],
    )
    assert deleted["revision"] == item["revision"] + 1


@pytest.mark.asyncio
async def test_delete_edge_stale_revision_rolls_back(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    first = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="scene",
        resource_type="scene",
        resource_id="scene-1",
        expected_revision=board["revision"],
    )
    second = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="scene",
        resource_type="scene",
        resource_id="scene-2",
        expected_revision=first["revision"],
    )
    edge = await service.add_edge(
        async_session,
        str(board["id"]),
        user_id="user-1",
        source_item_id=str(first["id"]),
        target_item_id=str(second["id"]),
        relation="reference",
        expected_revision=second["revision"],
    )

    with pytest.raises(service.CreativeBoardConflictError) as conflict:
        await service.delete_edge(
            async_session,
            str(board["id"]),
            str(edge["id"]),
            user_id="user-1",
            expected_revision=second["revision"],
        )

    assert conflict.value.current_revision == edge["revision"]
    unchanged = await service.get_board(async_session, str(board["id"]), user_id="user-1")
    assert unchanged["revision"] == edge["revision"]
    assert len(unchanged["edges"]) == 1

    deleted = await service.delete_edge(
        async_session,
        str(board["id"]),
        str(edge["id"]),
        user_id="user-1",
        expected_revision=edge["revision"],
    )
    assert deleted["revision"] == edge["revision"] + 1


async def test_revision_conflict_rolls_back_item_insert_and_reports_current_revision():
    import pytest
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from lib.db.base import Base
    from server.services import creative_boards as service

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            created = await service.create_board(session, user_id="user", project_id="project", name="Board")
            board_id = str(created["id"])
            await service.update_board(session, board_id, user_id="user", name="Renamed", expected_revision=1)

            with pytest.raises(service.CreativeBoardConflictError) as conflict:
                await service.add_item(
                    session,
                    board_id,
                    user_id="user",
                    item_type="scene",
                    resource_type="scene",
                    resource_id="scene-1",
                    expected_revision=1,
                )

            assert conflict.value.current_revision == 2
            current = await service.get_board(session, board_id, user_id="user")
            assert current["revision"] == 2
            assert current["items"] == []
    finally:
        await engine.dispose()


async def test_delete_item_expected_revision_is_atomic_and_advances_revision():
    import pytest
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from lib.db.base import Base
    from server.services import creative_boards as service

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            created = await service.create_board(session, user_id="user", project_id="project", name="Board")
            board_id = str(created["id"])
            item = await service.add_item(
                session,
                board_id,
                user_id="user",
                item_type="scene",
                resource_type="scene",
                resource_id="scene-1",
                expected_revision=1,
            )
            item_id = str(item["id"])

            with pytest.raises(service.CreativeBoardConflictError) as conflict:
                await service.delete_item(session, board_id, item_id, user_id="user", expected_revision=1)

            assert conflict.value.current_revision == 2
            unchanged = await service.get_board(session, board_id, user_id="user")
            assert unchanged["revision"] == 2
            assert len(unchanged["items"]) == 1

            deleted = await service.delete_item(session, board_id, item_id, user_id="user", expected_revision=2)
            assert deleted["revision"] == 3
            assert (await service.get_board(session, board_id, user_id="user"))["items"] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_version_snapshot_is_immutable_and_versions_are_listed_newest_first(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    first = await service.create_version(async_session, str(board["id"]), user_id="user-1", version_name="First")
    second = await service.create_version(async_session, str(board["id"]), user_id="user-1", version_name="Second")

    first["snapshot"]["name"] = "mutated in caller"
    loaded = await service.get_version(async_session, str(board["id"]), str(first["id"]), user_id="user-1")
    versions = await service.list_versions(async_session, str(board["id"]), user_id="user-1")

    assert loaded["snapshot"]["name"] == "Board"
    assert [item["version_number"] for item in versions["items"]] == [2, 1]
    assert versions["items"][0]["id"] == second["id"]


@pytest.mark.asyncio
async def test_restore_version_restores_complete_canvas_and_keeps_history(async_session):
    board = await service.create_board(
        async_session,
        user_id="user-1",
        project_id="project-1",
        name="Original",
        viewport={"x": 10, "y": 20, "zoom": 0.8},
    )
    first = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="scene",
        resource_type="scene",
        resource_id="scene-1",
        group_id="group-a",
        expected_revision=board["revision"],
    )
    second = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="shot",
        resource_type="shot",
        resource_id="shot-1",
        expected_revision=first["revision"],
    )
    await service.add_edge(
        async_session,
        str(board["id"]),
        user_id="user-1",
        source_item_id=str(first["id"]),
        target_item_id=str(second["id"]),
        relation="reference",
        expected_revision=second["revision"],
    )
    current = await service.get_board(async_session, str(board["id"]), user_id="user-1")
    version = await service.create_version(
        async_session,
        str(board["id"]),
        user_id="user-1",
        version_name="Before edit",
        expected_revision=current["revision"],
    )
    changed = await service.replace_board_snapshot(
        async_session,
        str(board["id"]),
        user_id="user-1",
        snapshot={
            "name": "Changed",
            "viewport": {"x": 0, "y": 0, "zoom": 2},
            "display_settings": {"grid": False},
            "items": [],
            "edges": [],
        },
        expected_revision=current["revision"],
    )

    restored = await service.restore_version(
        async_session,
        str(board["id"]),
        str(version["id"]),
        user_id="user-1",
        expected_revision=changed["revision"],
    )
    history = await service.get_version(async_session, str(board["id"]), str(version["id"]), user_id="user-1")

    assert restored["name"] == "Original"
    assert restored["viewport"] == {"x": 10, "y": 20, "zoom": 0.8}
    assert restored["items"][0]["group_id"] == "group-a"
    assert restored["edges"][0]["source_item_id"] == first["id"]
    assert restored["revision"] == changed["revision"] + 1
    assert history["snapshot"]["name"] == "Original"


@pytest.mark.asyncio
async def test_copy_creates_new_board_and_item_rows_but_keeps_resource_references(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Source")
    item = await service.add_item(
        async_session,
        str(board["id"]),
        user_id="user-1",
        item_type="media",
        resource_type="media_asset",
        resource_id="asset-1",
        group_id="group-a",
        expected_revision=board["revision"],
    )
    copy = await service.copy_board(async_session, str(board["id"]), user_id="user-1", name="Copy")

    assert copy["id"] != board["id"]
    assert copy["project_id"] == board["project_id"]
    assert copy["items"][0]["id"] != item["id"]
    assert copy["items"][0]["resource_id"] == "asset-1"
    assert copy["items"][0]["group_id"] == "group-a"


@pytest.mark.asyncio
async def test_snapshot_revision_conflict_rolls_back_everything(async_session):
    board = await service.create_board(async_session, user_id="user-1", project_id="project-1", name="Board")
    current = await service.update_board(
        async_session, str(board["id"]), user_id="user-1", name="Newer", expected_revision=board["revision"]
    )

    with pytest.raises(service.CreativeBoardConflictError):
        await service.replace_board_snapshot(
            async_session,
            str(board["id"]),
            user_id="user-1",
            snapshot={
                "name": "Stale",
                "viewport": {"zoom": 9},
                "items": [
                    {
                        "id": "stale-item",
                        "item_type": "scene",
                        "resource_type": "scene",
                        "resource_id": "scene-stale",
                    }
                ],
                "edges": [],
            },
            expected_revision=board["revision"],
        )

    unchanged = await service.get_board(async_session, str(board["id"]), user_id="user-1")
    assert unchanged["name"] == "Newer"
    assert unchanged["revision"] == current["revision"]
    assert unchanged["items"] == []
