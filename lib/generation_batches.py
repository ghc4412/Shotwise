"""Durable-control-plane primitives for batches of generation tasks.

A batch deliberately owns no worker state. Existing generation tasks remain the
execution source of truth; this module validates a batch once, asks an adapter
to admit all of its tasks atomically, and derives a presentation status by
reading those tasks back.

The first implementation is storage-agnostic. A database-backed repository and
an atomic ``GenerationQueue`` admission adapter can replace the in-memory
adapters without changing ``BatchOrchestrator`` callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4


@dataclass(frozen=True)
class GenerationBatchItem:
    """One task request in a batch, identified independently of queue task IDs."""

    item_id: str
    task: Mapping[str, Any]


@dataclass(frozen=True)
class GenerationBatchRequest:
    """A project-scoped request to admit generation tasks as one batch."""

    project_name: str
    items: tuple[GenerationBatchItem, ...]


@dataclass(frozen=True)
class BatchValidationReport:
    """The complete pre-admission result; invalid batches never reach admission."""

    issues: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.issues


class BatchStatus(StrEnum):
    """Control-plane status derived from the task statuses."""

    ADMITTED = "admitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class GenerationBatch:
    """Persistable batch metadata; task execution state is intentionally absent."""

    batch_id: str
    project_name: str
    items: tuple[GenerationBatchItem, ...]
    task_ids: tuple[str, ...]
    cancel_requested: bool = False
    user_id: str = "default"
    admission_state: str = "admitted"
    error_message: str | None = None


class BatchAdmissionError(RuntimeError):
    """Raised when an otherwise valid batch cannot be admitted atomically."""


class BatchNotFoundError(LookupError):
    """Raised when an operation references an unknown batch."""


class GenerationBatchTaskAdapter(Protocol):
    """Adapter from the batch control plane to the existing task/queue plane.

    ``admit_all`` is an all-or-nothing operation. Production adapters must
    implement it in the same transaction as task persistence; sequential calls
    to ``GenerationQueue.enqueue_task`` do not meet this contract.
    """

    async def validate(self, task: Mapping[str, Any]) -> tuple[str, ...]: ...

    async def admit_all(self, tasks: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]: ...

    async def get_task(self, task_id: str) -> Mapping[str, Any] | None: ...

    async def cancel_task(self, task_id: str) -> Mapping[str, Any]: ...


@runtime_checkable
class PreparedGenerationBatchTaskAdapter(Protocol):
    """Production adapter that can normalize tasks before a DB transaction."""

    async def prepare_all(
        self,
        tasks: tuple[Mapping[str, Any], ...],
        *,
        user_id: str,
    ) -> tuple[Mapping[str, Any], ...]: ...


class GenerationBatchRepository(Protocol):
    """Persistence seam for batch metadata, separate from the Task repository."""

    async def save(self, batch: GenerationBatch) -> None: ...

    async def get(self, batch_id: str) -> GenerationBatch | None: ...

    async def begin_admission(self, batch: GenerationBatch) -> None: ...

    async def complete_admission(self, batch: GenerationBatch) -> None: ...

    async def fail_admission(self, batch: GenerationBatch, error_message: str) -> None: ...


@runtime_checkable
class AtomicGenerationBatchRepository(Protocol):
    """Repository operations that persist batch and task changes together."""

    async def admit_with_tasks(
        self,
        batch: GenerationBatch,
        tasks: tuple[Mapping[str, Any], ...],
    ) -> GenerationBatch: ...

    async def replace_tasks(
        self,
        batch: GenerationBatch,
        replacements: tuple[tuple[int, Mapping[str, Any]], ...],
    ) -> GenerationBatch: ...


class InMemoryGenerationBatchRepository:
    """Test/development placeholder until a durable batch repository is introduced."""

    def __init__(self) -> None:
        self._batches: dict[str, GenerationBatch] = {}

    async def save(self, batch: GenerationBatch) -> None:
        self._batches[batch.batch_id] = batch

    async def get(self, batch_id: str) -> GenerationBatch | None:
        return self._batches.get(batch_id)

    async def begin_admission(self, batch: GenerationBatch) -> None:
        self._batches[batch.batch_id] = replace(batch, admission_state="admitting")

    async def complete_admission(self, batch: GenerationBatch) -> None:
        self._batches[batch.batch_id] = replace(batch, admission_state="admitted")

    async def fail_admission(self, batch: GenerationBatch, error_message: str) -> None:
        self._batches[batch.batch_id] = replace(
            batch,
            admission_state="failed",
            error_message=error_message,
        )


class BatchOrchestrator:
    """Small public interface for batch admission and task-backed lifecycle."""

    def __init__(
        self,
        *,
        repository: GenerationBatchRepository,
        tasks: GenerationBatchTaskAdapter,
        user_id: str = "default",
    ) -> None:
        self._repository = repository
        self._tasks = tasks
        self._user_id = user_id

    async def validate(self, request: GenerationBatchRequest) -> BatchValidationReport:
        issues: list[str] = []
        if not request.project_name.strip():
            issues.append("project_name is required")
        if not request.items:
            issues.append("batch must contain at least one item")

        seen_item_ids: set[str] = set()
        for item in request.items:
            if not item.item_id.strip():
                issues.append("item_id is required")
            elif item.item_id in seen_item_ids:
                issues.append(f"duplicate item_id: {item.item_id}")
            seen_item_ids.add(item.item_id)

            task = item.task
            if task.get("project_name") not in (None, request.project_name):
                issues.append(f"item '{item.item_id}': project_name does not match batch")
            for field in ("task_type", "media_type", "resource_id"):
                if not str(task.get(field) or "").strip():
                    issues.append(f"item '{item.item_id}': {field} is required")
            for issue in await self._tasks.validate(task):
                issues.append(f"item '{item.item_id}': {issue}")

        return BatchValidationReport(issues=tuple(issues))

    async def admit(self, request: GenerationBatchRequest) -> GenerationBatch:
        report = await self.validate(request)
        if not report.is_valid:
            raise BatchAdmissionError("; ".join(report.issues))

        batch = GenerationBatch(
            batch_id=uuid4().hex,
            project_name=request.project_name,
            items=request.items,
            task_ids=(),
            user_id=self._user_id,
            admission_state="admitting",
        )
        if isinstance(self._repository, AtomicGenerationBatchRepository) and isinstance(
            self._tasks, PreparedGenerationBatchTaskAdapter
        ):
            try:
                prepared = await self._tasks.prepare_all(
                    tuple(item.task for item in request.items),
                    user_id=self._user_id,
                )
                if len(prepared) != len(request.items):
                    raise BatchAdmissionError("task adapter returned an unexpected number of prepared tasks")
                return await self._repository.admit_with_tasks(batch, prepared)
            except Exception as exc:
                if isinstance(exc, BatchAdmissionError):
                    raise
                raise BatchAdmissionError(str(exc)) from exc

        await self._repository.begin_admission(batch)
        try:
            task_ids = await self._tasks.admit_all(tuple(item.task for item in request.items))
            if len(task_ids) != len(request.items):
                raise BatchAdmissionError("task adapter returned an unexpected number of task IDs")
            admitted = replace(batch, task_ids=task_ids, admission_state="admitted")
            await self._repository.complete_admission(admitted)
            return admitted
        except Exception as exc:
            await self._repository.fail_admission(batch, str(exc))
            if isinstance(exc, BatchAdmissionError):
                raise
            raise BatchAdmissionError(str(exc)) from exc

    async def get_status(self, batch_id: str) -> BatchStatus:
        batch = await self._get_batch(batch_id)
        if batch.admission_state != "admitted":
            raise BatchAdmissionError("batch is not admitted")
        statuses = [await self._task_status(task_id) for task_id in batch.task_ids]
        return self._derive_status(statuses, cancel_requested=batch.cancel_requested)

    async def get_batch(self, batch_id: str) -> GenerationBatch:
        """Return scoped batch metadata for API projections."""

        return await self._get_batch(batch_id)

    async def get_task(self, task_id: str) -> Mapping[str, Any] | None:
        """Return one task through the configured execution adapter."""

        return await self._tasks.get_task(task_id)

    async def cancel(self, batch_id: str) -> BatchStatus:
        batch = await self._get_batch(batch_id)
        for task_id in batch.task_ids:
            task = await self._tasks.get_task(task_id)
            if task is not None and task.get("status") not in {"succeeded", "failed", "cancelled"}:
                await self._tasks.cancel_task(task_id)
        if not batch.cancel_requested:
            batch = replace(batch, cancel_requested=True)
            await self._repository.save(batch)
        return await self.get_status(batch_id)

    async def retry_failed(self, batch_id: str) -> GenerationBatch:
        batch = await self._get_batch(batch_id)
        failed_items: list[tuple[int, GenerationBatchItem]] = []
        for index, (item, task_id) in enumerate(zip(batch.items, batch.task_ids, strict=True)):
            task = await self._tasks.get_task(task_id)
            if task is not None and task.get("status") == "failed":
                failed_items.append((index, item))

        if not failed_items:
            return batch

        if isinstance(self._repository, AtomicGenerationBatchRepository) and isinstance(
            self._tasks, PreparedGenerationBatchTaskAdapter
        ):
            prepared = await self._tasks.prepare_all(
                tuple(item.task for _, item in failed_items),
                user_id=self._user_id,
            )
            if len(prepared) != len(failed_items):
                raise BatchAdmissionError("task adapter returned an unexpected number of prepared retry tasks")
            replacements = tuple((index, task) for (index, _item), task in zip(failed_items, prepared, strict=True))
            return await self._repository.replace_tasks(batch, replacements)

        replacement_ids = await self._tasks.admit_all(tuple(item.task for _, item in failed_items))
        if len(replacement_ids) != len(failed_items):
            raise BatchAdmissionError("task adapter returned an unexpected number of retry task IDs")

        replacement_by_item = dict(zip((item.item_id for _, item in failed_items), replacement_ids, strict=True))
        task_ids = tuple(
            replacement_by_item.get(item.item_id, task_id)
            for item, task_id in zip(batch.items, batch.task_ids, strict=True)
        )
        retried = replace(batch, task_ids=task_ids, cancel_requested=False)
        await self._repository.save(retried)
        return retried

    async def _get_batch(self, batch_id: str) -> GenerationBatch:
        batch = await self._repository.get(batch_id)
        if batch is None:
            raise BatchNotFoundError(f"batch not found: {batch_id}")
        return batch

    async def _task_status(self, task_id: str) -> str:
        task = await self._tasks.get_task(task_id)
        return str(task.get("status")) if task is not None else "failed"

    @staticmethod
    def _derive_status(statuses: list[str], *, cancel_requested: bool) -> BatchStatus:
        if not statuses:
            return BatchStatus.FAILED
        active = {"queued", "running", "cancelling"}
        if any(status in active for status in statuses):
            return BatchStatus.RUNNING
        succeeded = sum(status == "succeeded" for status in statuses)
        failed = sum(status == "failed" for status in statuses)
        cancelled = sum(status == "cancelled" for status in statuses)
        if succeeded == len(statuses):
            return BatchStatus.SUCCEEDED
        if cancelled == len(statuses) or (cancel_requested and succeeded == 0 and failed == 0):
            return BatchStatus.CANCELLED
        if succeeded > 0:
            return BatchStatus.PARTIALLY_SUCCEEDED
        return BatchStatus.FAILED
