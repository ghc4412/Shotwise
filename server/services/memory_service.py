"""Business rules for user- and project-scoped Agent memories."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from lib.api_errors import BadRequestError, ConflictError, NotFoundError
from lib.db.repositories.memory_repository import MemoryRepository

MEMORY_MAX_LENGTH = 8_000
MEMORY_CATEGORY_MAX_LENGTH = 32
MEMORY_SOURCE_MAX_LENGTH = 32
MEMORY_SCOPES = frozenset(("user", "project"))
MEMORY_CATEGORIES = frozenset(("preference", "style", "world", "terminology", "workflow", "other"))

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret)\b", re.I),
    re.compile(r"\b(?:authorization|bearer)\s*[:=]", re.I),
    re.compile(r"\b(?:password|passwd|secret)\s*[:=]", re.I),
    re.compile(r"(?:^|[\\/])(?:users?|home|\.ssh|\.env)(?:[\\/]|$)", re.I),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\b(?:system|developer)\s+(?:message|prompt|instruction)s?\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(?:a|an)\b", re.I),
    re.compile(r"\b(?:override|bypass)\s+(?:the\s+)?(?:system|safety|security)\b", re.I),
    re.compile(r"<\s*/?\s*(?:system|developer|tool)\b", re.I),
)


class MemoryService:
    """Validate and coordinate memory persistence operations."""

    def __init__(self, session: AsyncSession):
        self.repo = MemoryRepository(session)

    @staticmethod
    def _validate_scope(scope: str, project_name: str | None) -> tuple[str, str | None]:
        if scope not in MEMORY_SCOPES:
            raise BadRequestError("memory_scope_invalid")
        if scope == "project":
            if not project_name:
                raise BadRequestError("memory_project_required")
            project_name = project_name.strip()
            if not project_name or len(project_name) > 200:
                raise BadRequestError("memory_project_invalid")
            return scope, project_name
        return scope, None

    @staticmethod
    def _validate_category(category: str) -> str:
        category = category.strip().lower()
        if not category or len(category) > MEMORY_CATEGORY_MAX_LENGTH:
            raise BadRequestError("memory_category_invalid")
        if category not in MEMORY_CATEGORIES:
            raise BadRequestError("memory_category_invalid")
        return category

    @staticmethod
    def _validate_source(source: str) -> str:
        source = source.strip().lower()
        if not source or len(source) > MEMORY_SOURCE_MAX_LENGTH or not re.fullmatch(r"[a-z0-9_-]+", source):
            raise BadRequestError("memory_source_invalid")
        return source

    @staticmethod
    def sanitize_content(content: str) -> str:
        """Normalize memory text and reject secrets or instruction-shaped content.

        Memory is reference material. Rejecting unsafe text at write time prevents a
        later prompt renderer from accidentally turning secrets or injected commands
        into durable context. This intentionally does not attempt to redact values.
        """
        if not isinstance(content, str):
            raise BadRequestError("memory_content_invalid")
        content = unicodedata.normalize("NFC", content).replace("\r\n", "\n").replace("\r", "\n")
        content = _CONTROL_CHARS.sub("", content).strip()
        if not content:
            raise BadRequestError("memory_content_empty")
        if len(content) > MEMORY_MAX_LENGTH:
            raise BadRequestError("memory_content_too_long", max_length=MEMORY_MAX_LENGTH)
        if any(pattern.search(content) for pattern in _SENSITIVE_PATTERNS):
            raise BadRequestError("memory_sensitive_content")
        if any(pattern.search(content) for pattern in _PROMPT_INJECTION_PATTERNS):
            raise BadRequestError("memory_prompt_injection")
        return content

    @classmethod
    def _validate_record(
        cls,
        *,
        scope: str,
        project_name: str | None,
        category: str,
        content: str,
        source: str,
    ) -> tuple[str, str | None, str, str, str]:
        scope, project_name = cls._validate_scope(scope, project_name)
        return (
            scope,
            project_name,
            cls._validate_category(category),
            cls.sanitize_content(content),
            cls._validate_source(source),
        )

    async def list_memories(self, *, user_id: str, scope: str, project_name: str | None = None) -> list[dict[str, Any]]:
        scope, project_name = self._validate_scope(scope, project_name)
        return await self.repo.list_entries(user_id=user_id, scope=scope, project_name=project_name)

    async def create_memory(
        self,
        *,
        user_id: str,
        scope: str,
        project_name: str | None,
        category: str,
        content: str,
        source: str = "user",
        source_session_id: str | None = None,
        source_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope, project_name, category, content, source = self._validate_record(
            scope=scope, project_name=project_name, category=category, content=content, source=source
        )
        duplicate = await self.repo.find_duplicate(
            user_id=user_id, scope=scope, project_name=project_name, category=category, content=content
        )
        if duplicate is not None:
            raise ConflictError("memory_duplicate")
        return await self.repo.create_entry(
            user_id=user_id,
            scope=scope,
            project_name=project_name,
            category=category,
            content=content,
            source=source,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            metadata=metadata,
        )

    async def update_memory(
        self,
        *,
        user_id: str,
        memory_id: str,
        category: str | None = None,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if category is None and content is None and metadata is None:
            raise BadRequestError("memory_update_empty")
        if category is not None:
            category = self._validate_category(category)
        if content is not None:
            content = self.sanitize_content(content)
        row = await self.repo.update_entry(
            memory_id, user_id=user_id, category=category, content=content, metadata=metadata
        )
        if row is None:
            raise NotFoundError("memory_not_found")
        return row

    async def delete_memory(self, *, user_id: str, memory_id: str) -> None:
        if not await self.repo.delete_entry(memory_id, user_id=user_id):
            raise NotFoundError("memory_not_found")

    async def clear_memories(self, *, user_id: str, scope: str, project_name: str | None = None) -> int:
        scope, project_name = self._validate_scope(scope, project_name)
        return await self.repo.clear_entries(user_id=user_id, scope=scope, project_name=project_name)

    async def create_candidate(
        self,
        *,
        user_id: str,
        scope: str,
        project_name: str | None,
        category: str,
        content: str,
        source_session_id: str | None = None,
        source_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope, project_name, category, content, _ = self._validate_record(
            scope=scope, project_name=project_name, category=category, content=content, source="agent"
        )
        return await self.repo.create_candidate(
            user_id=user_id,
            scope=scope,
            project_name=project_name,
            category=category,
            content=content,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            metadata=metadata,
        )

    async def list_candidates(
        self, *, user_id: str, scope: str | None = None, project_name: str | None = None
    ) -> list[dict[str, Any]]:
        if scope is not None:
            scope, project_name = self._validate_scope(scope, project_name)
        elif project_name is not None:
            raise BadRequestError("memory_scope_required")
        return await self.repo.list_candidates(user_id=user_id, scope=scope, project_name=project_name)

    async def accept_candidate(self, *, user_id: str, candidate_id: str) -> dict[str, Any]:
        candidate = await self.repo.get_candidate(candidate_id, user_id=user_id)
        if candidate is None:
            raise NotFoundError("memory_candidate_not_found")
        if candidate["status"] != "pending":
            raise ConflictError("memory_candidate_resolved")
        duplicate = await self.repo.find_duplicate(
            user_id=user_id,
            scope=candidate["scope"],
            project_name=candidate["project_name"],
            category=candidate["category"],
            content=candidate["content"],
        )
        if duplicate is None:
            memory = await self.repo.create_entry(
                user_id=user_id,
                scope=candidate["scope"],
                project_name=candidate["project_name"],
                category=candidate["category"],
                content=candidate["content"],
                source="agent_confirmed",
                source_session_id=candidate["source_session_id"],
                source_message_id=candidate["source_message_id"],
                metadata=candidate["metadata"],
            )
        else:
            memory = duplicate
        await self.repo.set_candidate_status(candidate_id, user_id=user_id, status="accepted", confirmed=True)
        return {"memory": memory, "candidate_id": candidate_id, "status": "accepted"}

    async def reject_candidate(self, *, user_id: str, candidate_id: str) -> dict[str, Any]:
        candidate = await self.repo.get_candidate(candidate_id, user_id=user_id)
        if candidate is None:
            raise NotFoundError("memory_candidate_not_found")
        if candidate["status"] != "pending":
            raise ConflictError("memory_candidate_resolved")
        await self.repo.set_candidate_status(candidate_id, user_id=user_id, status="rejected", confirmed=False)
        return {"candidate_id": candidate_id, "status": "rejected"}

    async def export_memories(self, *, user_id: str, project_name: str | None = None) -> dict[str, Any]:
        user_memories = await self.repo.list_entries(user_id=user_id, scope="user")
        project_memories: list[dict[str, Any]] = []
        if project_name is not None:
            project_memories = await self.repo.list_entries(user_id=user_id, scope="project", project_name=project_name)
        return {
            "format": "shotwise-agent-memory",
            "version": 1,
            "user_memories": user_memories,
            "project_memories": project_memories,
        }

    async def import_memories(self, *, user_id: str, payload: Any, project_name: str | None = None) -> dict[str, int]:
        """Import an explicit memory export additively, without overwriting records.

        User memories retain their global scope. Project memories are mapped to
        the explicitly selected destination project rather than trusting a source
        project field from the imported file. Project archive imports use the
        narrower ``import_project_memories`` method below.
        """
        if not isinstance(payload, dict):
            raise BadRequestError("memory_import_invalid")
        user_entries = payload.get("user_memories", [])
        project_entries = payload.get("project_memories", payload.get("entries", []))
        if not isinstance(user_entries, list) or not isinstance(project_entries, list):
            raise BadRequestError("memory_import_invalid")
        if project_entries and not project_name:
            raise BadRequestError("memory_project_required")

        imported = 0
        skipped = 0
        for scope, entries in (("user", user_entries), ("project", project_entries)):
            destination_project = project_name if scope == "project" else None
            for raw in entries:
                if not isinstance(raw, dict):
                    raise BadRequestError("memory_import_invalid")
                try:
                    _, _, category, content, _ = self._validate_record(
                        scope=scope,
                        project_name=destination_project,
                        category=str(raw.get("category", "other")),
                        content=raw.get("content", ""),
                        source="import",
                    )
                except (TypeError, ValueError):
                    raise BadRequestError("memory_import_invalid") from None
                duplicate = await self.repo.find_duplicate(
                    user_id=user_id,
                    scope=scope,
                    project_name=destination_project,
                    category=category,
                    content=content,
                )
                if duplicate is not None:
                    skipped += 1
                    continue
                await self.repo.create_entry(
                    user_id=user_id,
                    scope=scope,
                    project_name=destination_project,
                    category=category,
                    content=content,
                    source="import",
                    metadata={"imported": True},
                )
                imported += 1
        return {"imported": imported, "skipped": skipped}

    async def import_project_memories(self, *, user_id: str, project_name: str, payload: Any) -> dict[str, int]:
        if not isinstance(payload, dict):
            raise BadRequestError("memory_import_invalid")
        raw_entries = payload.get("project_memories", payload.get("entries"))
        if not isinstance(raw_entries, list):
            raise BadRequestError("memory_import_invalid")
        imported = 0
        skipped = 0
        for raw in raw_entries:
            if not isinstance(raw, dict):
                raise BadRequestError("memory_import_invalid")
            # Import is intentionally project-only. Source project/user fields are
            # ignored so an archive can never write another user's global memory.
            try:
                _, _, category, content, source = self._validate_record(
                    scope="project",
                    project_name=project_name,
                    category=str(raw.get("category", "other")),
                    content=raw.get("content", ""),
                    source="import",
                )
            except (TypeError, ValueError):
                raise BadRequestError("memory_import_invalid") from None
            duplicate = await self.repo.find_duplicate(
                user_id=user_id,
                scope="project",
                project_name=project_name,
                category=category,
                content=content,
            )
            if duplicate is not None:
                skipped += 1
                continue
            await self.repo.create_entry(
                user_id=user_id,
                scope="project",
                project_name=project_name,
                category=category,
                content=content,
                source=source,
                metadata={"imported": True},
            )
            imported += 1
        return {"imported": imported, "skipped": skipped}


__all__ = ["MemoryService", "MEMORY_MAX_LENGTH"]
