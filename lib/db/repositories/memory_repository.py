"""Async repository for user- and project-scoped Agent memories."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select, update

from lib.db.base import DEFAULT_USER_ID, dt_to_iso, utc_now
from lib.db.models.memory import MemoryCandidate, MemoryEntry
from lib.db.repositories.base import BaseRepository, rowcount


def _entry_to_dict(row: MemoryEntry | MemoryCandidate) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "scope": row.scope,
        "project_name": row.project_name,
        "category": row.category,
        "content": row.content,
        "source": row.source,
        "confirmed": row.confirmed,
        "source_session_id": row.source_session_id,
        "source_message_id": row.source_message_id,
        "metadata": row.metadata_json or {},
        "created_at": dt_to_iso(row.created_at),
        "updated_at": dt_to_iso(row.updated_at),
    }


def _candidate_to_dict(row: MemoryCandidate) -> dict[str, Any]:
    result = _entry_to_dict(row)  # MemoryCandidate shares the public fields.
    result["status"] = row.status
    return result


class MemoryRepository(BaseRepository):
    """Persistence primitives; every query is explicitly scoped by user id."""

    @staticmethod
    def _entry_scope(stmt, *, user_id: str, scope: str | None = None, project_name: str | None = None):
        stmt = stmt.where(MemoryEntry.user_id == user_id)
        if scope is not None:
            stmt = stmt.where(MemoryEntry.scope == scope)
        if project_name is not None:
            stmt = stmt.where(MemoryEntry.project_name == project_name)
        return stmt

    @staticmethod
    def _candidate_scope(stmt, *, user_id: str, scope: str | None = None, project_name: str | None = None):
        stmt = stmt.where(MemoryCandidate.user_id == user_id)
        if scope is not None:
            stmt = stmt.where(MemoryCandidate.scope == scope)
        if project_name is not None:
            stmt = stmt.where(MemoryCandidate.project_name == project_name)
        return stmt

    async def list_entries(
        self,
        *,
        user_id: str = DEFAULT_USER_ID,
        scope: str | None = None,
        project_name: str | None = None,
        confirmed_only: bool = True,
    ) -> list[dict[str, Any]]:
        stmt = select(MemoryEntry)
        stmt = self._entry_scope(stmt, user_id=user_id, scope=scope, project_name=project_name)
        if confirmed_only:
            stmt = stmt.where(MemoryEntry.confirmed.is_(True))
        stmt = stmt.order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id.desc())
        result = await self.session.execute(stmt)
        return [_entry_to_dict(row) for row in result.scalars().all()]

    async def get_entry(self, memory_id: str, *, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        stmt = self._entry_scope(select(MemoryEntry), user_id=user_id).where(MemoryEntry.id == memory_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return _entry_to_dict(row) if row else None

    async def create_entry(
        self,
        *,
        scope: str,
        project_name: str | None,
        category: str,
        content: str,
        source: str,
        user_id: str = DEFAULT_USER_ID,
        confirmed: bool = True,
        source_session_id: str | None = None,
        source_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        row = MemoryEntry(
            id=str(uuid.uuid4()),
            user_id=user_id,
            scope=scope,
            project_name=project_name,
            category=category,
            content=content,
            source=source,
            confirmed=confirmed,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            metadata_json=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        return _entry_to_dict(row)

    async def update_entry(
        self,
        memory_id: str,
        *,
        user_id: str = DEFAULT_USER_ID,
        category: str | None = None,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {"updated_at": utc_now()}
        if category is not None:
            values["category"] = category
        if content is not None:
            values["content"] = content
        if metadata is not None:
            values["metadata_json"] = metadata
        stmt = update(MemoryEntry).where(MemoryEntry.id == memory_id, MemoryEntry.user_id == user_id).values(**values)
        result = await self.session.execute(stmt)
        if rowcount(result) == 0:
            return None
        return await self.get_entry(memory_id, user_id=user_id)

    async def delete_entry(self, memory_id: str, *, user_id: str = DEFAULT_USER_ID) -> bool:
        stmt = delete(MemoryEntry).where(MemoryEntry.id == memory_id, MemoryEntry.user_id == user_id)
        result = await self.session.execute(stmt)
        return rowcount(result) > 0

    async def clear_entries(
        self, *, user_id: str = DEFAULT_USER_ID, scope: str, project_name: str | None = None
    ) -> int:
        stmt = delete(MemoryEntry).where(MemoryEntry.user_id == user_id, MemoryEntry.scope == scope)
        if project_name is not None:
            stmt = stmt.where(MemoryEntry.project_name == project_name)
        result = await self.session.execute(stmt)
        return rowcount(result)

    async def find_duplicate(
        self,
        *,
        user_id: str,
        scope: str,
        project_name: str | None,
        category: str,
        content: str,
    ) -> dict[str, Any] | None:
        stmt = self._entry_scope(select(MemoryEntry), user_id=user_id, scope=scope, project_name=project_name)
        stmt = stmt.where(MemoryEntry.category == category, MemoryEntry.content == content)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return _entry_to_dict(row) if row else None

    async def list_candidates(
        self,
        *,
        user_id: str = DEFAULT_USER_ID,
        scope: str | None = None,
        project_name: str | None = None,
        status: str | None = "pending",
    ) -> list[dict[str, Any]]:
        stmt = self._candidate_scope(select(MemoryCandidate), user_id=user_id, scope=scope, project_name=project_name)
        if status is not None:
            stmt = stmt.where(MemoryCandidate.status == status)
        stmt = stmt.order_by(MemoryCandidate.updated_at.desc(), MemoryCandidate.id.desc())
        result = await self.session.execute(stmt)
        return [_candidate_to_dict(row) for row in result.scalars().all()]

    async def get_candidate(self, candidate_id: str, *, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        stmt = self._candidate_scope(select(MemoryCandidate), user_id=user_id).where(MemoryCandidate.id == candidate_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return _candidate_to_dict(row) if row else None

    async def create_candidate(
        self,
        *,
        scope: str,
        project_name: str | None,
        category: str,
        content: str,
        user_id: str = DEFAULT_USER_ID,
        source: str = "agent",
        source_session_id: str | None = None,
        source_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        row = MemoryCandidate(
            id=str(uuid.uuid4()),
            user_id=user_id,
            scope=scope,
            project_name=project_name,
            category=category,
            content=content,
            source=source,
            confirmed=False,
            status="pending",
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            metadata_json=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        return _candidate_to_dict(row)

    async def set_candidate_status(
        self, candidate_id: str, *, user_id: str = DEFAULT_USER_ID, status: str, confirmed: bool
    ) -> dict[str, Any] | None:
        stmt = (
            update(MemoryCandidate)
            .where(MemoryCandidate.id == candidate_id, MemoryCandidate.user_id == user_id)
            .values(status=status, confirmed=confirmed, updated_at=utc_now())
        )
        result = await self.session.execute(stmt)
        if rowcount(result) == 0:
            return None
        return await self.get_candidate(candidate_id, user_id=user_id)

    async def clear_candidates(
        self, *, user_id: str = DEFAULT_USER_ID, scope: str | None = None, project_name: str | None = None
    ) -> int:
        stmt = delete(MemoryCandidate).where(MemoryCandidate.user_id == user_id)
        if scope is not None:
            stmt = stmt.where(MemoryCandidate.scope == scope)
        if project_name is not None:
            stmt = stmt.where(MemoryCandidate.project_name == project_name)
        result = await self.session.execute(stmt)
        return rowcount(result)


__all__ = ["MemoryRepository"]
