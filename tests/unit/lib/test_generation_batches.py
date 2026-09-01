from __future__ import annotations

import pytest

from lib.generation_batches import (
    BatchAdmissionError,
    BatchOrchestrator,
    BatchStatus,
    GenerationBatchItem,
    GenerationBatchRequest,
    InMemoryGenerationBatchRepository,
)


class _FakeTaskAdapter:
    def __init__(self, *, validation_issues: dict[str, tuple[str, ...]] | None = None) -> None:
        self.validation_issues = validation_issues or {}
        self.tasks: dict[str, dict[str, object]] = {}
        self.admitted_requests: list[tuple[dict[str, object], ...]] = []
        self.cancelled: list[str] = []
        self._next_id = 1

    async def validate(self, task: dict[str, object]) -> tuple[str, ...]:
        return self.validation_issues.get(str(task["resource_id"]), ())

    async def admit_all(self, tasks: tuple[dict[str, object], ...]) -> tuple[str, ...]:
        self.admitted_requests.append(tuple(dict(task) for task in tasks))
        task_ids = []
        for task in tasks:
            task_id = f"task-{self._next_id}"
            self._next_id += 1
            self.tasks[task_id] = {**task, "status": "queued"}
            task_ids.append(task_id)
        return tuple(task_ids)

    async def get_task(self, task_id: str) -> dict[str, object] | None:
        return self.tasks.get(task_id)

    async def cancel_task(self, task_id: str) -> dict[str, object]:
        self.cancelled.append(task_id)
        task = self.tasks[task_id]
        if task["status"] not in {"succeeded", "failed", "cancelled"}:
            task["status"] = "cancelled"
        return task


@pytest.fixture
def batch_request() -> GenerationBatchRequest:
    return GenerationBatchRequest(
        project_name="demo",
        items=(
            GenerationBatchItem(
                item_id="first", task={"resource_id": "first", "task_type": "image", "media_type": "image"}
            ),
            GenerationBatchItem(
                item_id="second", task={"resource_id": "second", "task_type": "video", "media_type": "video"}
            ),
        ),
    )


def _orchestrator(tasks: _FakeTaskAdapter) -> BatchOrchestrator:
    return BatchOrchestrator(repository=InMemoryGenerationBatchRepository(), tasks=tasks)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_validate_rejects_empty_batch_without_admitting_tasks() -> None:
    tasks = _FakeTaskAdapter()
    report = await _orchestrator(tasks).validate(GenerationBatchRequest(project_name="demo", items=()))

    assert report.is_valid is False
    assert report.issues == ("batch must contain at least one item",)
    assert tasks.admitted_requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_validate_checks_every_item_and_reports_all_issues() -> None:
    tasks = _FakeTaskAdapter(validation_issues={"second": ("unsupported provider",)})
    request = GenerationBatchRequest(
        project_name="demo",
        items=(
            GenerationBatchItem(
                item_id="first", task={"resource_id": "first", "task_type": "image", "media_type": "image"}
            ),
            GenerationBatchItem(
                item_id="second", task={"resource_id": "second", "task_type": "video", "media_type": "video"}
            ),
        ),
    )

    report = await _orchestrator(tasks).validate(request)

    assert report.is_valid is False
    assert report.issues == ("item 'second': unsupported provider",)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admit_valid_batch_calls_adapter_once_and_persists_control_metadata(batch_request) -> None:
    tasks = _FakeTaskAdapter()
    orchestrator = _orchestrator(tasks)

    batch = await orchestrator.admit(batch_request)

    assert len(batch.batch_id) == 32
    assert batch.project_name == "demo"
    assert batch.task_ids == ("task-1", "task-2")
    assert len(tasks.admitted_requests) == 1
    assert (await orchestrator.get_status(batch.batch_id)) is BatchStatus.RUNNING


@pytest.mark.unit
@pytest.mark.asyncio
async def test_admit_invalid_batch_is_all_or_nothing() -> None:
    tasks = _FakeTaskAdapter(validation_issues={"second": ("bad input",)})
    orchestrator = _orchestrator(tasks)

    with pytest.raises(BatchAdmissionError, match="item 'second': bad input"):
        await orchestrator.admit(
            GenerationBatchRequest(
                project_name="demo",
                items=(
                    GenerationBatchItem(
                        item_id="first", task={"resource_id": "first", "task_type": "image", "media_type": "image"}
                    ),
                    GenerationBatchItem(
                        item_id="second", task={"resource_id": "second", "task_type": "video", "media_type": "video"}
                    ),
                ),
            )
        )

    assert tasks.admitted_requests == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (("succeeded", "succeeded"), BatchStatus.SUCCEEDED),
        (("succeeded", "failed"), BatchStatus.PARTIALLY_SUCCEEDED),
        (("failed", "failed"), BatchStatus.FAILED),
        (("cancelled", "cancelled"), BatchStatus.CANCELLED),
        (("succeeded", "running"), BatchStatus.RUNNING),
    ],
)
async def test_get_status_derives_batch_status_from_task_source_of_truth(batch_request, statuses, expected) -> None:
    tasks = _FakeTaskAdapter()
    orchestrator = _orchestrator(tasks)
    batch = await orchestrator.admit(batch_request)
    for task_id, status in zip(batch.task_ids, statuses, strict=True):
        tasks.tasks[task_id]["status"] = status

    assert await orchestrator.get_status(batch.batch_id) is expected


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancel_forwards_each_active_task_and_does_not_touch_completed_tasks(batch_request) -> None:
    tasks = _FakeTaskAdapter()
    orchestrator = _orchestrator(tasks)
    batch = await orchestrator.admit(batch_request)
    tasks.tasks[batch.task_ids[0]]["status"] = "succeeded"
    tasks.tasks[batch.task_ids[1]]["status"] = "running"

    status = await orchestrator.cancel(batch.batch_id)

    assert tasks.cancelled == [batch.task_ids[1]]
    assert status is BatchStatus.PARTIALLY_SUCCEEDED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_failed_replaces_only_failed_task_ids(batch_request) -> None:
    tasks = _FakeTaskAdapter()
    orchestrator = _orchestrator(tasks)
    batch = await orchestrator.admit(batch_request)
    tasks.tasks[batch.task_ids[0]]["status"] = "succeeded"
    tasks.tasks[batch.task_ids[1]]["status"] = "failed"

    retried = await orchestrator.retry_failed(batch.batch_id)

    assert retried.task_ids == (batch.task_ids[0], "task-3")
    assert tasks.admitted_requests[-1] == (batch_request.items[1].task,)
    assert await orchestrator.get_status(batch.batch_id) is BatchStatus.RUNNING
