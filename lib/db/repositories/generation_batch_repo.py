"""Durable repository for generation batch metadata and admission."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.generation_batch import GenerationBatchRecord
from lib.db.models.task import Task
from lib.generation_batches import (
    BatchAdmissionError,
    GenerationBatch,
    GenerationBatchItem,
)
from lib.prompt_preview import PROMPT_PREVIEW_PAYLOAD_KEY, build_enqueue_prompt_preview


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str) -> Any:
    return json.loads(value)


def _serialize_items(items: Sequence[GenerationBatchItem]) -> str:
    return _dumps([{"item_id": item.item_id, "task": dict(item.task)} for item in items])


def _deserialize_items(value: str) -> tuple[GenerationBatchItem, ...]:
    raw = _loads(value)
    if not isinstance(raw, list):
        raise ValueError("generation batch items must be a list")
    items: list[GenerationBatchItem] = []
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("task"), dict):
            raise ValueError("generation batch item is invalid")
        items.append(GenerationBatchItem(item_id=str(entry.get("item_id") or ""), task=dict(entry["task"])))
    return tuple(items)


def _deserialize_task_ids(value: str) -> tuple[str, ...]:
    raw = _loads(value)
    if not isinstance(raw, list) or not all(isinstance(task_id, str) for task_id in raw):
        raise ValueError("generation batch task IDs are invalid")
    return tuple(raw)


def _to_domain(row: GenerationBatchRecord) -> GenerationBatch:
    return GenerationBatch(
        batch_id=row.batch_id,
        project_name=row.project_name,
        items=_deserialize_items(row.items_json),
        task_ids=_deserialize_task_ids(row.task_ids_json),
        cancel_requested=row.cancel_requested,
        user_id=row.user_id,
        admission_state=row.admission_state,
        error_message=row.error_message,
    )


class GenerationBatchRepository:
    """User/project-scoped persistence for durable generation batches."""

    def __init__(self, session: AsyncSession, *, user_id: str, project_name: str) -> None:
        self.session = session
        self.user_id = user_id
        self.project_name = project_name

    def _scope(self):
        return (
            GenerationBatchRecord.user_id == self.user_id,
            GenerationBatchRecord.project_name == self.project_name,
        )

    async def _get_row(self, batch_id: str) -> GenerationBatchRecord | None:
        result = await self.session.execute(
            select(GenerationBatchRecord).where(GenerationBatchRecord.batch_id == batch_id, *self._scope())
        )
        return result.scalar_one_or_none()

    async def get(self, batch_id: str) -> GenerationBatch | None:
        row = await self._get_row(batch_id)
        return _to_domain(row) if row is not None else None

    async def save(self, batch: GenerationBatch) -> None:
        self._ensure_scope(batch)
        row = await self._get_row(batch.batch_id)
        if row is None:
            raise BatchAdmissionError("batch is outside the current user or project scope")
        self._copy_to_row(row, batch)
        await self.session.commit()

    async def begin_admission(self, batch: GenerationBatch) -> None:
        self._ensure_scope(batch)
        now = utc_now()
        self.session.add(
            GenerationBatchRecord(
                batch_id=batch.batch_id,
                project_name=batch.project_name,
                admission_state="admitting",
                items_json=_serialize_items(batch.items),
                task_ids_json="[]",
                cancel_requested=False,
                error_message=None,
                user_id=batch.user_id,
                created_at=now,
                updated_at=now,
            )
        )
        await self.session.commit()

    async def complete_admission(self, batch: GenerationBatch) -> None:
        await self.save(replace(batch, admission_state="admitted", error_message=None))

    async def fail_admission(self, batch: GenerationBatch, error_message: str) -> None:
        await self.save(replace(batch, admission_state="failed", error_message=error_message))

    async def admit_with_tasks(
        self,
        batch: GenerationBatch,
        tasks: tuple[Mapping[str, Any], ...],
    ) -> GenerationBatch:
        self._ensure_scope(batch)
        if len(tasks) != len(batch.items):
            raise BatchAdmissionError("batch item and task counts do not match")

        now = utc_now()
        task_rows = self._task_rows(tasks, now=now)
        admitted = replace(
            batch,
            task_ids=tuple(row.task_id for row in task_rows),
            admission_state="admitted",
            error_message=None,
        )
        batch_row = GenerationBatchRecord(
            batch_id=admitted.batch_id,
            project_name=admitted.project_name,
            admission_state=admitted.admission_state,
            items_json=_serialize_items(admitted.items),
            task_ids_json=_dumps(admitted.task_ids),
            cancel_requested=admitted.cancel_requested,
            error_message=None,
            user_id=admitted.user_id,
            created_at=now,
            updated_at=now,
        )
        try:
            self.session.add_all([batch_row, *task_rows])
            await self.session.flush()
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return admitted

    async def replace_tasks(
        self,
        batch: GenerationBatch,
        replacements: tuple[tuple[int, Mapping[str, Any]], ...],
    ) -> GenerationBatch:
        self._ensure_scope(batch)
        row = await self._get_row(batch.batch_id)
        if row is None:
            raise BatchAdmissionError("batch is outside the current user or project scope")
        current = _to_domain(row)
        if current.task_ids != batch.task_ids:
            raise BatchAdmissionError("batch tasks changed while retrying")

        now = utc_now()
        replacement_rows = self._task_rows(tuple(spec for _, spec in replacements), now=now)
        task_ids = list(current.task_ids)
        for (index, _spec), task_row in zip(replacements, replacement_rows, strict=True):
            if index < 0 or index >= len(task_ids):
                raise BatchAdmissionError("replacement task index is invalid")
            task_ids[index] = task_row.task_id

        retried = replace(current, task_ids=tuple(task_ids), cancel_requested=False, error_message=None)
        self._copy_to_row(row, retried)
        try:
            self.session.add_all(replacement_rows)
            await self.session.flush()
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return retried

    def _task_rows(self, tasks: tuple[Mapping[str, Any], ...], *, now) -> list[Task]:
        rows: list[Task] = []
        for spec in tasks:
            required = ("project_name", "task_type", "media_type", "resource_id")
            missing = [field for field in required if not str(spec.get(field) or "").strip()]
            if missing:
                raise BatchAdmissionError(f"batch task missing required fields: {', '.join(missing)}")
            if str(spec["project_name"]) != self.project_name:
                raise BatchAdmissionError("batch task project does not match repository scope")

            raw_payload = spec.get("payload")
            if raw_payload is None:
                payload: dict[str, Any] = {}
            elif isinstance(raw_payload, Mapping):
                payload = dict(raw_payload)
            else:
                raise BatchAdmissionError("batch task payload must be an object")
            task_type = str(spec["task_type"])
            media_type = str(spec["media_type"])
            resource_id = str(spec["resource_id"])
            payload[PROMPT_PREVIEW_PAYLOAD_KEY] = build_enqueue_prompt_preview(
                project_name=self.project_name,
                task_type=task_type,
                media_type=media_type,
                resource_id=resource_id,
                script_file=spec.get("script_file"),
                provider_id=spec.get("provider_id"),
                payload=payload,
            )
            rows.append(
                Task(
                    task_id=uuid.uuid4().hex,
                    project_name=self.project_name,
                    task_type=task_type,
                    media_type=media_type,
                    resource_id=resource_id,
                    script_file=spec.get("script_file"),
                    resource_type=spec.get("resource_type"),
                    payload_json=_dumps(payload),
                    status="queued",
                    source=str(spec.get("source") or "webui"),
                    dependency_task_id=spec.get("dependency_task_id"),
                    dependency_group=spec.get("dependency_group"),
                    dependency_index=spec.get("dependency_index"),
                    provider_id=spec.get("provider_id"),
                    queued_at=now,
                    updated_at=now,
                    user_id=self.user_id,
                )
            )
        return rows

    def _copy_to_row(self, row: GenerationBatchRecord, batch: GenerationBatch) -> None:
        row.admission_state = batch.admission_state
        row.items_json = _serialize_items(batch.items)
        row.task_ids_json = _dumps(batch.task_ids)
        row.cancel_requested = batch.cancel_requested
        row.error_message = batch.error_message
        row.updated_at = utc_now()

    def _ensure_scope(self, batch: GenerationBatch) -> None:
        if batch.user_id != self.user_id or batch.project_name != self.project_name:
            raise BatchAdmissionError("batch is outside the current user or project scope")


__all__ = ["GenerationBatchRepository"]
