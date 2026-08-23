"""Application service for semantic Creative Boards.

Creative Board data is intentionally independent from workflow execution. Its
edges describe content relationships, never node scheduling, ports, adapters,
or failure branches.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.creative_board import CreativeBoard, CreativeBoardEdge, CreativeBoardItem

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


def _json(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def _owned_board(session: AsyncSession, board_id: str, user_id: str) -> CreativeBoard:
    board = await session.get(CreativeBoard, board_id)
    if board is None or board.user_id != user_id:
        raise CreativeBoardNotFoundError(board_id)
    return board


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
            }
            for board in boards
        ]
    }


async def get_board(session: AsyncSession, board_id: str, *, user_id: str) -> dict[str, object]:
    return await _board_payload(session, await _owned_board(session, board_id, user_id))


async def update_board(
    session: AsyncSession,
    board_id: str,
    *,
    user_id: str,
    name: str | None = None,
    viewport: Mapping[str, Any] | None = None,
    display_settings: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    if name is not None:
        if not name.strip():
            raise CreativeBoardValidationError("board name must not be empty")
        board.name = name.strip()
    if viewport is not None:
        board.viewport_json = _json(viewport)
    if display_settings is not None:
        board.display_settings_json = _json(display_settings)
    board.updated_at = utc_now()
    await session.commit()
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
    board.updated_at = now
    await session.commit()
    return {
        "id": item.id,
        "item_type": item.item_type,
        "resource_type": item.resource_type,
        "resource_id": item.resource_id,
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
    display_settings: Mapping[str, Any] | None = None,
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
    if group_id is not None:
        item.group_id = group_id
    if display_settings is not None:
        item.display_settings_json = _json(display_settings)
    item.updated_at = utc_now()
    board.updated_at = item.updated_at
    await session.commit()
    return await _board_payload(session, board)


async def delete_item(session: AsyncSession, board_id: str, item_id: str, *, user_id: str) -> dict[str, object]:
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
    board.updated_at = utc_now()
    await session.commit()
    return {"deleted": True, "item_id": item_id}


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
        return {
            "id": existing.id,
            "source_item_id": existing.source_item_id,
            "target_item_id": existing.target_item_id,
            "relation": existing.relation,
        }
    edge = CreativeBoardEdge(
        id=uuid.uuid4().hex,
        board_id=board.id,
        source_item_id=source_item_id,
        target_item_id=target_item_id,
        relation=relation,
        ordinal=ordinal,
        metadata_json=_json(metadata),
        created_at=utc_now(),
    )
    session.add(edge)
    board.updated_at = utc_now()
    await session.commit()
    return {
        "id": edge.id,
        "source_item_id": edge.source_item_id,
        "target_item_id": edge.target_item_id,
        "relation": edge.relation,
    }


async def delete_edge(session: AsyncSession, board_id: str, edge_id: str, *, user_id: str) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    edge = await session.scalar(
        select(CreativeBoardEdge).where(CreativeBoardEdge.id == edge_id, CreativeBoardEdge.board_id == board.id)
    )
    if edge is None:
        raise CreativeBoardNotFoundError(edge_id)
    await session.delete(edge)
    board.updated_at = utc_now()
    await session.commit()
    return {"deleted": True, "edge_id": edge_id}


async def delete_board(session: AsyncSession, board_id: str, *, user_id: str) -> dict[str, object]:
    board = await _owned_board(session, board_id, user_id)
    await session.execute(delete(CreativeBoardEdge).where(CreativeBoardEdge.board_id == board.id))
    await session.execute(delete(CreativeBoardItem).where(CreativeBoardItem.board_id == board.id))
    await session.delete(board)
    await session.commit()
    return {"deleted": True, "board_id": board_id}
