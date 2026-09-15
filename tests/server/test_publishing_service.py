from __future__ import annotations

import base64
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from lib.db.base import utc_now
from lib.db.models.publish import PublishJob
from lib.db.models.render_job import RenderArtifact, RenderJob, RenderReviewSnapshot
from server.services import media_assembly, publishing
from server.services.publishing_adapters import PublishStatus
from server.services.publishing_crypto import KEY_ENV
from tests.lib.test_media_assembly_plan import _document

pytestmark = pytest.mark.integration


def _configure_test_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, base64.urlsafe_b64encode(b"k" * 32).decode("ascii"))


async def _confirmed_final_artifact(async_session, *, user_id: str = "user-1") -> tuple[str, str, str]:
    created = await media_assembly.create_plan(
        async_session,
        user_id=user_id,
        project_name="demo",
        name="Publish",
        scope="episode",
        episode_number=1,
        **_document(),
    )
    plan_id = created["id"]
    source_fingerprint = created["current_source_fingerprint"]
    now = utc_now()
    render_job = RenderJob(
        id="render-job-1" if user_id == "user-1" else f"render-job-{user_id}",
        plan_id=plan_id,
        project_name="demo",
        user_id=user_id,
        revision_number=1,
        kind="final",
        status="succeeded",
        attempt=1,
        max_attempts=3,
        input_fingerprint=source_fingerprint,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    artifact = RenderArtifact(
        id="artifact-1" if user_id == "user-1" else f"artifact-{user_id}",
        render_job_id=render_job.id,
        plan_id=plan_id,
        project_name="demo",
        user_id=user_id,
        revision_number=1,
        kind="final",
        relative_path="render_artifacts/final.mp4",
        mime_type="video/mp4",
        size_bytes=10,
        duration_seconds=8.0,
        width=1080,
        height=1920,
        fingerprint="artifact-fingerprint",
        created_at=now,
    )
    snapshot = RenderReviewSnapshot(
        id="review-1" if user_id == "user-1" else f"review-{user_id}",
        artifact_id=artifact.id,
        plan_id=plan_id,
        project_name="demo",
        user_id=user_id,
        revision_number=1,
        source_fingerprint=source_fingerprint,
        artifact_fingerprint=artifact.fingerprint,
        status="ready",
        checks_json='{"blocking_reasons": [], "audio": {"has_audio": true}}',
        created_at=now,
        confirmed_by=user_id,
        confirmed_at=now,
    )
    async_session.add_all([render_job, artifact, snapshot])
    await async_session.flush()
    return plan_id, artifact.id, snapshot.id


async def test_create_binds_final_artifact_review_revision_and_fingerprints(async_session) -> None:
    plan_id, artifact_id, review_id = await _confirmed_final_artifact(async_session)

    result = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="publish-1",
        destination={"account": "placeholder"},
        max_attempts=2,
        user_id="user-1",
    )

    assert result["status"] == "queued"
    assert result["plan_id"] == plan_id
    assert result["artifact_id"] == artifact_id
    assert result["review_snapshot_id"] == review_id
    assert result["revision_number"] == 1
    assert result["source_fingerprint"]
    assert result["artifact_fingerprint"] == "artifact-fingerprint"
    assert result["destination"] == {"account": "placeholder"}


@pytest.mark.parametrize(
    ("field", "expected_code"),
    [("confirmed_by", "review_confirmation_required"), ("source_fingerprint", "source_fingerprint_mismatch")],
)
async def test_create_rejects_untrusted_or_stale_review_binding(async_session, field: str, expected_code: str) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    from sqlalchemy import select

    snapshot = await async_session.scalar(select(RenderReviewSnapshot).where(RenderReviewSnapshot.id == review_id))
    assert snapshot is not None
    if field == "confirmed_by":
        snapshot.confirmed_by = None
        snapshot.confirmed_at = None
    else:
        snapshot.source_fingerprint = "stale-source"

    with pytest.raises(publishing.PublishConflictError) as exc_info:
        await publishing.create_publish_job(
            async_session,
            artifact_id,
            review_snapshot_id=review_id,
            platform="generic",
            idempotency_key=f"publish-{field}",
            user_id="user-1",
        )
    assert exc_info.value.code == expected_code


async def test_create_rejects_preview_artifact_and_cross_user_access(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    from sqlalchemy import select

    artifact = await async_session.scalar(select(RenderArtifact).where(RenderArtifact.id == artifact_id))
    assert artifact is not None
    artifact.kind = "preview"
    with pytest.raises(publishing.PublishConflictError) as exc_info:
        await publishing.create_publish_job(
            async_session,
            artifact_id,
            review_snapshot_id=review_id,
            platform="generic",
            idempotency_key="preview",
            user_id="user-1",
        )
    assert exc_info.value.code == "final_artifact_required"

    with pytest.raises(publishing.PublishJobNotFoundError):
        await publishing.create_publish_job(
            async_session,
            artifact_id,
            review_snapshot_id=review_id,
            platform="generic",
            idempotency_key="other-user",
            user_id="other-user",
        )


async def test_idempotency_replays_same_job_and_rejects_payload_change(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    first = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="same-key",
        destination={"title": "one"},
        user_id="user-1",
    )
    second = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="same-key",
        destination={"title": "one"},
        user_id="user-1",
    )
    assert second["id"] == first["id"]

    with pytest.raises(publishing.PublishConflictError) as exc_info:
        await publishing.create_publish_job(
            async_session,
            artifact_id,
            review_snapshot_id=review_id,
            platform="other-platform",
            idempotency_key="same-key",
            user_id="user-1",
        )
    assert exc_info.value.code == "idempotency_key_reused"


async def test_default_adapter_fails_without_external_platform_and_retry_is_bounded(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="retry-key",
        max_attempts=2,
        user_id="user-1",
    )
    failed = await publishing.run_publish_job(async_session, created["id"], user_id="user-1")
    assert failed["status"] == "failed"
    assert failed["attempt"] == 1
    assert failed["error_code"] == "platform_adapter_not_connected"

    queued = await publishing.retry_publish_job(async_session, created["id"], user_id="user-1")
    assert queued["status"] == "queued"
    failed_again = await publishing.run_publish_job(async_session, created["id"], user_id="user-1")
    assert failed_again["status"] == "failed"
    assert failed_again["attempt"] == 2
    with pytest.raises(publishing.PublishConflictError) as exc_info:
        await publishing.retry_publish_job(async_session, created["id"], user_id="user-1")
    assert exc_info.value.code == "retry_limit_reached"


async def test_successful_adapter_transitions_job_to_succeeded(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="success-key",
        user_id="user-1",
    )
    adapter = AsyncMock()
    result = await publishing.run_publish_job(async_session, created["id"], user_id="user-1", adapter=adapter)
    assert result["status"] == "succeeded"
    assert result["attempt"] == 1
    adapter.assert_awaited_once()


async def test_retry_revalidates_current_revision(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="stale-retry",
        user_id="user-1",
    )
    await publishing.run_publish_job(async_session, created["id"], user_id="user-1")
    from sqlalchemy import select

    snapshot = await async_session.scalar(select(RenderReviewSnapshot).where(RenderReviewSnapshot.id == review_id))
    assert snapshot is not None
    snapshot.artifact_fingerprint = "replaced-artifact"
    with pytest.raises(publishing.PublishConflictError) as exc_info:
        await publishing.retry_publish_job(async_session, created["id"], user_id="user-1")
    assert exc_info.value.code == "artifact_fingerprint_mismatch"


async def test_publish_job_is_user_scoped(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="owner-key",
        user_id="user-1",
    )
    with pytest.raises(publishing.PublishJobNotFoundError):
        await publishing.get_publish_job(async_session, created["id"], user_id="other-user")


async def test_publishing_account_is_user_scoped_and_revoke_deletes_credentials(
    async_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_test_encryption_key(monkeypatch)
    created = await publishing.create_publishing_account(
        async_session,
        user_id="user-1",
        platform="douyin",
        platform_account_id="douyin-account-1",
        account_name="Creator",
        access_token="access-token",
        refresh_token="refresh-token",
        scopes=["video.publish", "video.publish"],
    )
    assert created["scopes"] == ["video.publish"]
    assert "access_token" not in created
    assert "refresh_token" not in created

    with pytest.raises(publishing.PublishJobNotFoundError):
        await publishing.get_publishing_account(async_session, created["id"], user_id="other-user")

    revoked = await publishing.revoke_publishing_account(async_session, created["id"], user_id="user-1")
    assert revoked["status"] == "revoked"
    account = await publishing._owned_account(async_session, created["id"], "user-1")
    assert account.encrypted_access_token is None
    assert account.encrypted_refresh_token is None


async def test_create_rejects_account_from_another_platform(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_test_encryption_key(monkeypatch)
    account = await publishing.create_publishing_account(
        async_session,
        user_id="user-1",
        platform="douyin",
        platform_account_id="douyin-account-2",
        account_name="Creator",
        access_token="access-token",
    )
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)

    with pytest.raises(publishing.PublishConflictError) as exc_info:
        await publishing.create_publish_job(
            async_session,
            artifact_id,
            review_snapshot_id=review_id,
            platform="hongguo",
            account_id=account["id"],
            idempotency_key="platform-mismatch",
            user_id="user-1",
        )
    assert exc_info.value.code == "account_platform_mismatch"


async def test_poll_transitions_processing_and_schedules_next_poll(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="poll-processing",
        user_id="user-1",
    )

    job = await async_session.scalar(select(PublishJob).where(PublishJob.id == created["id"]))
    assert job is not None
    job.status = "submitted"
    job.attempt = 1
    adapter = AsyncMock()
    adapter.poll.return_value = PublishStatus(external_status="processing")

    result = await publishing.poll_publish_job(async_session, job.id, user_id="user-1", adapter=adapter)

    assert result["status"] == "processing"
    assert result["external_status"] == "processing"
    assert result["next_poll_at"] is not None
    adapter.poll.assert_awaited_once_with(job)


async def test_poll_failure_uses_retryable_status_and_backoff(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="poll-failure",
        user_id="user-1",
    )

    job = await async_session.scalar(select(PublishJob).where(PublishJob.id == created["id"]))
    assert job is not None
    job.status = "processing"
    job.attempt = 1
    adapter = AsyncMock()
    adapter.poll.side_effect = TimeoutError("provider timeout")

    result = await publishing.poll_publish_job(async_session, job.id, user_id="user-1", adapter=adapter)

    assert result["status"] == "failed_retryable"
    assert result["error_code"] == "poll_failed"
    assert result["next_poll_at"] is not None
    assert result["last_polled_at"] is not None


async def test_list_publish_jobs_is_user_scoped_and_newest_first(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    first = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="history-first",
        user_id="user-1",
    )
    second = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="history-second",
        user_id="user-1",
    )
    other_plan, other_artifact, other_review = await _confirmed_final_artifact(async_session, user_id="other-user")
    await publishing.create_publish_job(
        async_session,
        other_artifact,
        review_snapshot_id=other_review,
        platform="generic",
        idempotency_key="history-other",
        user_id="other-user",
    )
    result = await publishing.list_publish_jobs(async_session, user_id="user-1", limit=1, offset=0)
    assert result["total"] == 2
    assert result["limit"] == 1
    assert result["offset"] == 0
    assert [item["id"] for item in result["items"]] == [second["id"]]
    paged = await publishing.list_publish_jobs(async_session, user_id="user-1", limit=20, offset=1)
    assert [item["id"] for item in paged["items"]] == [first["id"]]


async def test_list_publish_jobs_clamps_pagination(async_session) -> None:
    result = await publishing.list_publish_jobs(async_session, user_id="user-1", limit=1000, offset=-10)
    assert result["limit"] == 100
    assert result["offset"] == 0


async def test_poll_without_adapter_raises_deterministic_unavailable_error(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="poll-no-adapter",
        user_id="user-1",
    )

    job = await async_session.scalar(select(PublishJob).where(PublishJob.id == created["id"]))
    assert job is not None
    job.status = "submitted"

    with pytest.raises(publishing.PublishAdapterUnavailableError, match="platform_adapter_not_connected"):
        await publishing.poll_publish_job(async_session, job.id, user_id="user-1", adapter=None)
    assert job.status == "submitted"


async def test_retract_transitions_to_retracted_with_adapter(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="retract-success",
        user_id="user-1",
    )

    job = await async_session.scalar(select(PublishJob).where(PublishJob.id == created["id"]))
    assert job is not None
    job.status = "published"
    monkeypatch.setattr(
        publishing,
        "get_platform_capabilities",
        lambda _: SimpleNamespace(supports_retract=True),
    )
    adapter = AsyncMock()

    result = await publishing.retract_publish_job(async_session, job.id, user_id="user-1", adapter=adapter)

    assert result["status"] == "retracted"
    assert result["external_status"] == "retracted"
    adapter.retract.assert_awaited_once_with(job)


async def test_retract_without_adapter_raises_without_mutating_state(
    async_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="retract-no-adapter",
        user_id="user-1",
    )

    job = await async_session.scalar(select(PublishJob).where(PublishJob.id == created["id"]))
    assert job is not None
    job.status = "published"
    monkeypatch.setattr(
        publishing,
        "get_platform_capabilities",
        lambda _: SimpleNamespace(supports_retract=True),
    )

    with pytest.raises(publishing.PublishAdapterUnavailableError, match="platform_adapter_not_connected"):
        await publishing.retract_publish_job(async_session, job.id, user_id="user-1", adapter=None)
    assert job.status == "published"


async def test_poll_and_retract_are_user_scoped(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="poll-owner",
        user_id="user-1",
    )

    job = await async_session.scalar(select(PublishJob).where(PublishJob.id == created["id"]))
    assert job is not None
    job.status = "submitted"
    with pytest.raises(publishing.PublishJobNotFoundError):
        await publishing.poll_publish_job(async_session, job.id, user_id="other-user", adapter=AsyncMock())

    job.status = "published"
    monkeypatch.setattr(
        publishing,
        "get_platform_capabilities",
        lambda _: SimpleNamespace(supports_retract=True),
    )
    with pytest.raises(publishing.PublishJobNotFoundError):
        await publishing.retract_publish_job(async_session, job.id, user_id="other-user", adapter=AsyncMock())


@pytest.mark.parametrize(
    "status", ["queued", "publishing", "submitted", "processing", "publish_pending", "failed_retryable"]
)
async def test_cancel_active_publish_job_clears_lease_and_marks_user_cancelled(async_session, status: str) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key=f"cancel-{status}",
        user_id="user-1",
    )
    job = await async_session.scalar(select(PublishJob).where(PublishJob.id == created["id"]))
    assert job is not None
    job.status = status
    job.worker_id = "worker-1"
    job.lease_until = utc_now() + timedelta(minutes=5)

    result = await publishing.cancel_publish_job(async_session, job.id, user_id="user-1")

    assert result["status"] == "canceled"
    assert result["error_code"] == "canceled_by_user"
    assert job.worker_id is None
    assert job.lease_until is None
    assert job.next_poll_at is None
    assert job.completed_at is not None


async def test_cancel_published_publish_job_is_rejected(async_session) -> None:
    _, artifact_id, review_id = await _confirmed_final_artifact(async_session)
    created = await publishing.create_publish_job(
        async_session,
        artifact_id,
        review_snapshot_id=review_id,
        platform="generic",
        idempotency_key="cancel-published",
        user_id="user-1",
    )
    job = await async_session.scalar(select(PublishJob).where(PublishJob.id == created["id"]))
    assert job is not None
    job.status = "published"

    with pytest.raises(publishing.PublishConflictError) as exc_info:
        await publishing.cancel_publish_job(async_session, job.id, user_id="user-1")

    assert exc_info.value.code == "cancel_requires_active"
    assert exc_info.value.status == "published"
