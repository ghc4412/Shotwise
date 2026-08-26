"""Application service for semantic Creative Boards.

Creative Board data is intentionally independent from workflow execution. Its
edges describe content relationships, never node scheduling, ports, adapters,
or failure branches.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.creative_board import (
    CreativeBoard,
    CreativeBoardEdge,
    CreativeBoardItem,
    CreativeBoardVersion,
)

ALLOWED_ITEM_TYPES = frozenset(
    {
        "document",
        "character",
        "scene",
        "prop",
        "product",
        "media",
        "episode",
        "shot",
        "skill_action",
        "review",
        "final",
    }
)
ALLOWED_RELATIONS = frozenset({"reference", "derived_from", "belongs_to", "shot_order", "composite_input"})


class CreativeBoardValidationError(ValueError):
    """Raised when a board payload violates semantic-canvas constraints."""


class CreativeBoardNotFoundError(LookupError):
    """Raised when a board is absent or owned by another user."""


class CreativeBoardConflictError(RuntimeError):
    """Raised when a versioned board update targets an older board revision."""

    def __init__(self, *, current_revision: int, current_updated_at: datetime) -> None:
        super().__init__("creative board revision conflict")
        self.current_revision = current_revision
        self.current_updated_at = current_updated_at


def _json(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _owned_board(session: AsyncSession, board_id: str, user_id: str) -> CreativeBoard:
    board = await session.get(CreativeBoard, board_id)
    if board is None or board.user_id != user_id:
        raise CreativeBoardNotFoundError(board_id)
    return board


async def _raise_board_update_failure(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    expected_revision: int | None,
) -> None:
    # Roll back pending item/edge mutations before reading the authoritative
    # board revision.  This keeps a failed optimistic update atomic and makes
    # the follow-up read observe the committed state on both SQLite and
    # PostgreSQL.
    await session.rollback()
    current = await session.scalar(
        select(CreativeBoard)
        .where(CreativeBoard.id == board_id, CreativeBoard.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if current is None:
        raise CreativeBoardNotFoundError(board_id)
    current_revision = current.revision
    current_updated_at = current.updated_at
    if expected_revision is None:
        raise CreativeBoardNotFoundError(board_id)
    raise CreativeBoardConflictError(
        current_revision=current_revision,
        current_updated_at=current_updated_at,
    )


async def _board_payload(session: AsyncSession, board: CreativeBoard) -> dict[str, object]:
    items = (
        (
            await session.execute(
                select(CreativeBoardItem)
                .where(CreativeBoardItem.board_id == board.id)
                .order_by(CreativeBoardItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    edges = (
        (
            await session.execute(
                select(CreativeBoardEdge)
                .where(CreativeBoardEdge.board_id == board.id)
                .order_by(CreativeBoardEdge.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": board.id,
        "project_id": board.project_id,
        "name": board.name,
        "viewport": json.loads(board.viewport_json),
        "display_settings": json.loads(board.display_settings_json),
        "created_at": board.created_at.isoformat(),
        "updated_at": board.updated_at.isoformat(),
        "revision": board.revision,
        "items": [
            {
                "id": item.id,
                "item_type": item.item_type,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "position": {"x": item.position_x, "y": item.position_y},
                "size": {"width": item.width, "height": item.height},
                "group_id": item.group_id,
                "display_settings": json.loads(item.display_settings_json),
            }
            for item in items
        ],
        "edges": [
            {
                "id": edge.id,
                "source_item_id": edge.source_item_id,
                "target_item_id": edge.target_item_id,
                "relation": edge.relation,
                "ordinal": edge.ordinal,
                "metadata": json.loads(edge.metadata_json),
            }
            for edge in edges
        ],
    }


def _snapshot_from_board_payload(payload: Mapping[str, Any]) -> dict[str, object]:
    return {
        "name": payload["name"],
        "viewport": payload["viewport"],
        "display_settings": payload["display_settings"],
        "created_at": payload["created_at"],
        "items": payload["items"],
        "edges": payload["edges"],
    }


def _snapshot_created_at(value: Any, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CreativeBoardValidationError("snapshot created_at must be an ISO timestamp") from exc
    raise CreativeBoardValidationError("snapshot created_at must be an ISO timestamp")


def _normalise_snapshot(snapshot: Mapping[str, Any], *, fallback_created_at: datetime) -> dict[str, Any]:
    name = snapshot.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CreativeBoardValidationError("board name must not be empty")
    raw_items = snapshot.get("items", [])
    raw_edges = snapshot.get("edges", [])
    if not isinstance(raw_items, list) or not isinstance(raw_edges, list):
        raise CreativeBoardValidationError("snapshot items and edges must be lists")

    items: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            raise CreativeBoardValidationError("snapshot items must be objects")
        item_id = raw_item.get("id") or uuid.uuid4().hex
        if not isinstance(item_id, str) or not item_id.strip() or item_id in item_ids:
            raise CreativeBoardValidationError("snapshot item ids must be unique")
        item_type = raw_item.get("item_type")
        resource_type = raw_item.get("resource_type")
        resource_id = raw_item.get("resource_id")
        if item_type not in ALLOWED_ITEM_TYPES:
            raise CreativeBoardValidationError("unsupported board item type")
        if not isinstance(resource_type, str) or not resource_type.strip():
            raise CreativeBoardValidationError("resource_type must not be empty")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise CreativeBoardValidationError("resource_id must not be empty")
        position = raw_item.get("position") or {}
        size = raw_item.get("size") or {}
        if not isinstance(position, Mapping) or not isinstance(size, Mapping):
            raise CreativeBoardValidationError("snapshot item position and size must be objects")
        item_ids.add(item_id)
        items.append(
            {
                "id": item_id,
                "item_type": item_type,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "position": {"x": int(position.get("x", 0)), "y": int(position.get("y", 0))},
                "size": {
                    "width": max(1, int(size.get("width", 280))),
                    "height": max(1, int(size.get("height", 180))),
                },
                "group_id": raw_item.get("group_id"),
                "display_settings": dict(raw_item.get("display_settings") or {}),
            }
        )

    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    edge_ids: set[str] = set()
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Mapping):
            raise CreativeBoardValidationError("snapshot edges must be objects")
        source = raw_edge.get("source_item_id")
        target = raw_edge.get("target_item_id")
        relation = raw_edge.get("relation")
        edge_id = raw_edge.get("id") or uuid.uuid4().hex
        if not isinstance(source, str) or not isinstance(target, str) or source == target:
            raise CreativeBoardValidationError("board edge endpoints must differ")
        if source not in item_ids or target not in item_ids:
            raise CreativeBoardValidationError("board edge endpoints must belong to the board")
        if not isinstance(relation, str) or relation not in ALLOWED_RELATIONS:
            raise CreativeBoardValidationError("unsupported board edge relation")
        key = (source, target, relation)
        if key in edge_keys or not isinstance(edge_id, str) or edge_id in edge_ids:
            raise CreativeBoardValidationError("snapshot edge ids and relationships must be unique")
        edge_keys.add(key)
        edge_ids.add(edge_id)
        edges.append(
            {
                "id": edge_id,
                "source_item_id": source,
                "target_item_id": target,
                "relation": relation,
                "ordinal": raw_edge.get("ordinal"),
                "metadata": dict(raw_edge.get("metadata") or {}),
            }
        )
    return {
        "name": name.strip(),
        "viewport": dict(snapshot.get("viewport") or {}),
        "display_settings": dict(snapshot.get("display_settings") or {}),
        "created_at": _snapshot_created_at(snapshot.get("created_at"), fallback_created_at).isoformat(),
        "items": items,
        "edges": edges,
    }


def _version_payload(version: CreativeBoardVersion, *, include_snapshot: bool) -> dict[str, object]:
    result: dict[str, object] = {
        "id": version.id,
        "board_id": version.board_id,
        "version_number": version.version_number,
        "version_name": version.version_name,
        "created_at": version.created_at.isoformat(),
    }
    if include_snapshot:
        result["snapshot"] = json.loads(version.snapshot_json)
    return result


async def create_board(
    session: AsyncSession,
    *,
    user_id: str,
    project_id: str,
    name: str,
    viewport: Mapping[str, Any] | None = None,
    display_settings: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    now = utc_now()
    board = CreativeBoard(
        id=uuid.uuid4().hex,
        user_id=user_id,
        project_id=project_id,
        name=name.strip(),
        viewport_json=_json(viewport),
        display_settings_json=_json(display_settings),
        created_at=now,
        updated_at=now,
        revision=1,
    )
    if not board.name:
        raise CreativeBoardValidationError("board name must not be empty")
    session.add(board)
    await session.commit()
    return await _board_payload(session, board)


async def list_boards(session: AsyncSession, *, user_id: str, project_id: str) -> dict[str, object]:
    boards = (
        (
            await session.execute(
                select(CreativeBoard)
                .where(CreativeBoard.user_id == user_id, CreativeBoard.project_id == project_id)
                .order_by(CreativeBoard.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": board.id,
                "project_id": board.project_id,
                "name": board.name,
                "updated_at": board.updated_at.isoformat(),
                "revision": board.revision,
            }
            for board in boards
        ]
    }


async def get_board(session: AsyncSession, board_id: str, *, user_id: str) -> dict[str, object]:
    return await _board_payload(session, await _owned_board(session, board_id, user_id))


async def _advance_board_revision(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    now: datetime,
    expected_revision: int | None = None,
    values: Mapping[str, Any] | None = None,
) -> None:
    statement = update(CreativeBoard).where(CreativeBoard.id == board_id, CreativeBoard.user_id == user_id)
    if expected_revision is not None:
        statement = statement.where(CreativeBoard.revision == expected_revision)
    update_values: dict[str, Any] = {"updated_at": now, "revision": CreativeBoard.revision + 1}
    update_values.update(values or {})
    result = await session.execute(statement.values(**update_values))
    if getattr(result, "rowcount", None) != 1:
        await _raise_board_update_failure(
            session,
            board_id,
            user_id=user_id,
            expected_revision=expected_revision,
        )


async def update_board(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    name: str | None = None,
    viewport: Mapping[str, Any] | None = None,
    display_settings: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    now = utc_now()
    values: dict[str, Any] = {"updated_at": now, "revision": CreativeBoard.revision + 1}
    if name is not None:
        if not name.strip():
            raise CreativeBoardValidationError("board name must not be empty")
        values["name"] = name.strip()
    if viewport is not None:
        values["viewport_json"] = _json(viewport)
    if display_settings is not None:
        values["display_settings_json"] = _json(display_settings)

    statement = update(CreativeBoard).where(CreativeBoard.id == board.id, CreativeBoard.user_id == user_id)
    if expected_revision is not None:
        statement = statement.where(CreativeBoard.revision == expected_revision)
    result = await session.execute(statement.values(**values))
    if getattr(result, "rowcount", None) != 1:
        await _raise_board_update_failure(
            session,
            board_id,
            user_id=user_id,
            expected_revision=expected_revision,
        )
    await session.commit()
    await session.refresh(board)
    return await _board_payload(session, board)


async def add_item(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    item_type: str,
    resource_type: str,
    resource_id: str,
    position: Mapping[str, Any] | None = None,
    size: Mapping[str, Any] | None = None,
    group_id: str | None = None,
    display_settings: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    if item_type not in ALLOWED_ITEM_TYPES:
        raise CreativeBoardValidationError("unsupported board item type")
    if not resource_id.strip():
        raise CreativeBoardValidationError("resource_id must not be empty")
    position = position or {}
    size = size or {}
    now = utc_now()
    item = CreativeBoardItem(
        id=uuid.uuid4().hex,
        board_id=board.id,
        item_type=item_type,
        resource_type=resource_type,
        resource_id=resource_id,
        position_x=int(position.get("x", 0)),
        position_y=int(position.get("y", 0)),
        width=max(1, int(size.get("width", 280))),
        height=max(1, int(size.get("height", 180))),
        group_id=group_id,
        display_settings_json=_json(display_settings),
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    await _advance_board_revision(session, board.id, user_id=user_id, now=now, expected_revision=expected_revision)
    await session.commit()
    await session.refresh(board)
    return {
        "id": item.id,
        "item_type": item.item_type,
        "resource_type": item.resource_type,
        "resource_id": item.resource_id,
        "revision": board.revision,
        "updated_at": board.updated_at.isoformat(),
    }


async def update_item(
    session: AsyncSession,
    board_id: str,
    item_id: str,
    *,
    user_id: str,
    position: Mapping[str, Any] | None = None,
    size: Mapping[str, Any] | None = None,
    group_id: str | None = None,
    update_group_id: bool = False,
    display_settings: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    item = await session.scalar(
        select(CreativeBoardItem).where(CreativeBoardItem.id == item_id, CreativeBoardItem.board_id == board.id)
    )
    if item is None:
        raise CreativeBoardNotFoundError(item_id)
    if position is not None:
        item.position_x = int(position.get("x", item.position_x))
        item.position_y = int(position.get("y", item.position_y))
    if size is not None:
        item.width = max(1, int(size.get("width", item.width)))
        item.height = max(1, int(size.get("height", item.height)))
    if group_id is not None or update_group_id:
        item.group_id = group_id
    if display_settings is not None:
        item.display_settings_json = _json(display_settings)
    item.updated_at = utc_now()
    await _advance_board_revision(
        session,
        board.id,
        user_id=user_id,
        now=item.updated_at,
        expected_revision=expected_revision,
    )
    await session.commit()
    await session.refresh(board)
    return await _board_payload(session, board)


async def delete_item(
    session: AsyncSession,
    board_id: str,
    item_id: str,
    *,
    user_id: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    item = await session.scalar(
        select(CreativeBoardItem).where(CreativeBoardItem.id == item_id, CreativeBoardItem.board_id == board.id)
    )
    if item is None:
        raise CreativeBoardNotFoundError(item_id)
    await session.execute(
        delete(CreativeBoardEdge).where(
            CreativeBoardEdge.board_id == board.id,
            (CreativeBoardEdge.source_item_id == item.id) | (CreativeBoardEdge.target_item_id == item.id),
        )
    )
    await session.delete(item)
    now = utc_now()
    await _advance_board_revision(
        session,
        board.id,
        user_id=user_id,
        now=now,
        expected_revision=expected_revision,
    )
    await session.commit()
    await session.refresh(board)
    return {
        "deleted": True,
        "item_id": item_id,
        "revision": board.revision,
        "updated_at": board.updated_at.isoformat(),
    }


async def add_edge(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    source_item_id: str,
    target_item_id: str,
    relation: str,
    ordinal: int | None = None,
    metadata: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    if relation not in ALLOWED_RELATIONS:
        raise CreativeBoardValidationError("unsupported board edge relation")
    if source_item_id == target_item_id:
        raise CreativeBoardValidationError("board edge endpoints must differ")
    item_ids = set(
        (await session.execute(select(CreativeBoardItem.id).where(CreativeBoardItem.board_id == board.id)))
        .scalars()
        .all()
    )
    if {source_item_id, target_item_id} - item_ids:
        raise CreativeBoardValidationError("board edge endpoints must belong to the board")
    existing = await session.scalar(
        select(CreativeBoardEdge).where(
            CreativeBoardEdge.board_id == board.id,
            CreativeBoardEdge.source_item_id == source_item_id,
            CreativeBoardEdge.target_item_id == target_item_id,
            CreativeBoardEdge.relation == relation,
        )
    )
    if existing is not None:
        if expected_revision is not None and board.revision != expected_revision:
            await _raise_board_update_failure(
                session,
                board.id,
                user_id=user_id,
                expected_revision=expected_revision,
            )
        return {
            "id": existing.id,
            "source_item_id": existing.source_item_id,
            "target_item_id": existing.target_item_id,
            "relation": existing.relation,
            "revision": board.revision,
            "updated_at": board.updated_at.isoformat(),
        }
    now = utc_now()
    edge = CreativeBoardEdge(
        id=uuid.uuid4().hex,
        board_id=board.id,
        source_item_id=source_item_id,
        target_item_id=target_item_id,
        relation=relation,
        ordinal=ordinal,
        metadata_json=_json(metadata),
        created_at=now,
    )
    session.add(edge)
    await _advance_board_revision(session, board.id, user_id=user_id, now=now, expected_revision=expected_revision)
    await session.commit()
    await session.refresh(board)
    return {
        "id": edge.id,
        "source_item_id": edge.source_item_id,
        "target_item_id": edge.target_item_id,
        "relation": edge.relation,
        "revision": board.revision,
        "updated_at": board.updated_at.isoformat(),
    }


async def delete_edge(
    session: AsyncSession,
    board_id: str,
    edge_id: str,
    *,
    user_id: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    edge = await session.scalar(
        select(CreativeBoardEdge).where(CreativeBoardEdge.id == edge_id, CreativeBoardEdge.board_id == board.id)
    )
    if edge is None:
        raise CreativeBoardNotFoundError(edge_id)
    await session.delete(edge)
    now = utc_now()
    await _advance_board_revision(
        session,
        board.id,
        user_id=user_id,
        now=now,
        expected_revision=expected_revision,
    )
    await session.commit()
    await session.refresh(board)
    return {
        "deleted": True,
        "edge_id": edge_id,
        "revision": board.revision,
        "updated_at": board.updated_at.isoformat(),
    }


async def delete_board(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    revision = board.revision
    updated_at = board.updated_at
    await session.execute(delete(CreativeBoardEdge).where(CreativeBoardEdge.board_id == board.id))
    await session.execute(delete(CreativeBoardItem).where(CreativeBoardItem.board_id == board.id))
    statement = delete(CreativeBoard).where(CreativeBoard.id == board.id, CreativeBoard.user_id == user_id)
    if expected_revision is not None:
        statement = statement.where(CreativeBoard.revision == expected_revision)
    result = await session.execute(statement)
    if getattr(result, "rowcount", None) != 1:
        await _raise_board_update_failure(
            session,
            board_id,
            user_id=user_id,
            expected_revision=expected_revision,
        )
    await session.commit()
    return {
        "deleted": True,
        "board_id": board_id,
        "revision": revision,
        "updated_at": updated_at.isoformat(),
    }


async def replace_board_snapshot(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    snapshot: Mapping[str, Any],
    expected_revision: int | None,
) -> dict[str, object]:
    """Atomically replace the complete board snapshot and advance its revision."""
    board = await _owned_board(session, board_id, user_id)
    normalised = _normalise_snapshot(snapshot, fallback_created_at=board.created_at)
    now = utc_now()
    await session.execute(delete(CreativeBoardEdge).where(CreativeBoardEdge.board_id == board.id))
    await session.execute(delete(CreativeBoardItem).where(CreativeBoardItem.board_id == board.id))
    session.add_all(
        [
            CreativeBoardItem(
                id=item["id"],
                board_id=board.id,
                item_type=item["item_type"],
                resource_type=item["resource_type"],
                resource_id=item["resource_id"],
                position_x=item["position"]["x"],
                position_y=item["position"]["y"],
                width=item["size"]["width"],
                height=item["size"]["height"],
                group_id=item["group_id"],
                display_settings_json=_json(item["display_settings"]),
                created_at=now,
                updated_at=now,
            )
            for item in normalised["items"]
        ]
    )
    session.add_all(
        [
            CreativeBoardEdge(
                id=edge["id"],
                board_id=board.id,
                source_item_id=edge["source_item_id"],
                target_item_id=edge["target_item_id"],
                relation=edge["relation"],
                ordinal=edge["ordinal"],
                metadata_json=_json(edge["metadata"]),
                created_at=now,
            )
            for edge in normalised["edges"]
        ]
    )
    await _advance_board_revision(
        session,
        board.id,
        user_id=user_id,
        now=now,
        expected_revision=expected_revision,
        values={
            "name": normalised["name"],
            "viewport_json": _json(normalised["viewport"]),
            "display_settings_json": _json(normalised["display_settings"]),
            "created_at": _snapshot_created_at(normalised["created_at"], board.created_at),
        },
    )
    await session.commit()
    await session.refresh(board)
    return await _board_payload(session, board)


async def create_version(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    version_name: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    if expected_revision is not None and board.revision != expected_revision:
        await _raise_board_update_failure(session, board_id, user_id=user_id, expected_revision=expected_revision)
    if not version_name.strip():
        raise CreativeBoardValidationError("version name must not be empty")
    latest = await session.scalar(
        select(CreativeBoardVersion)
        .where(CreativeBoardVersion.board_id == board.id)
        .order_by(CreativeBoardVersion.version_number.desc())
        .limit(1)
    )
    snapshot = _snapshot_from_board_payload(await _board_payload(session, board))
    version = CreativeBoardVersion(
        id=uuid.uuid4().hex,
        board_id=board.id,
        version_number=(latest.version_number + 1 if latest else 1),
        version_name=version_name.strip(),
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        created_at=utc_now(),
    )
    session.add(version)
    await session.commit()
    return _version_payload(version, include_snapshot=True)


async def list_versions(session: AsyncSession, board_id: str, *, user_id: str) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    versions = (
        (
            await session.execute(
                select(CreativeBoardVersion)
                .where(CreativeBoardVersion.board_id == board.id)
                .order_by(CreativeBoardVersion.created_at.desc(), CreativeBoardVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_version_payload(version, include_snapshot=False) for version in versions]}


async def get_version(session: AsyncSession, board_id: str, version_id: str, *, user_id: str) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    version = await session.scalar(
        select(CreativeBoardVersion).where(
            CreativeBoardVersion.id == version_id, CreativeBoardVersion.board_id == board.id
        )
    )
    if version is None:
        raise CreativeBoardNotFoundError(version_id)
    return _version_payload(version, include_snapshot=True)


async def restore_version(
    session: AsyncSession,
    board_id: str,
    version_id: str,
    *,
    user_id: str,
    expected_revision: int,
) -> dict[str, object]:
    version = await get_version(session, board_id, version_id, user_id=user_id)
    snapshot = cast(Mapping[str, Any], version["snapshot"])
    return await replace_board_snapshot(
        session,
        board_id,
        user_id=user_id,
        snapshot=snapshot,
        expected_revision=expected_revision,
    )


async def copy_board(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    name: str | None = None,
    version_id: str | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    if version_id is None:
        source = _snapshot_from_board_payload(await _board_payload(session, board))
    else:
        version = await get_version(session, board_id, version_id, user_id=user_id)
        source = cast(Mapping[str, Any], version["snapshot"])
    copy_name = name.strip() if name is not None else f"{source['name']} copy"
    if not copy_name:
        raise CreativeBoardValidationError("board name must not be empty")
    normalised = _normalise_snapshot(source, fallback_created_at=board.created_at)
    now = utc_now()
    new_board = CreativeBoard(
        id=uuid.uuid4().hex,
        user_id=user_id,
        project_id=board.project_id,
        name=copy_name,
        viewport_json=_json(normalised["viewport"]),
        display_settings_json=_json(normalised["display_settings"]),
        created_at=now,
        updated_at=now,
        revision=1,
    )
    session.add(new_board)
    item_ids: dict[str, str] = {}
    for item in normalised["items"]:
        item_ids[item["id"]] = uuid.uuid4().hex
        session.add(
            CreativeBoardItem(
                id=item_ids[item["id"]],
                board_id=new_board.id,
                item_type=item["item_type"],
                resource_type=item["resource_type"],
                resource_id=item["resource_id"],
                position_x=item["position"]["x"],
                position_y=item["position"]["y"],
                width=item["size"]["width"],
                height=item["size"]["height"],
                group_id=item["group_id"],
                display_settings_json=_json(item["display_settings"]),
                created_at=now,
                updated_at=now,
            )
        )
    for edge in normalised["edges"]:
        session.add(
            CreativeBoardEdge(
                id=uuid.uuid4().hex,
                board_id=new_board.id,
                source_item_id=item_ids[edge["source_item_id"]],
                target_item_id=item_ids[edge["target_item_id"]],
                relation=edge["relation"],
                ordinal=edge["ordinal"],
                metadata_json=_json(edge["metadata"]),
                created_at=now,
            )
        )
    await session.commit()
    await session.refresh(new_board)
    return await _board_payload(session, new_board)
