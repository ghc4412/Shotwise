from __future__ import annotations

import pytest
from sqlalchemy import select

from lib.db.models.assembly_plan import AssemblyPlanRevision
from server.services import media_assembly as service
from tests.lib.test_media_assembly_plan import _document

pytestmark = pytest.mark.integration


async def _create(session, *, user_id: str = "user-1") -> dict:
    return await service.create_plan(
        session,
        user_id=user_id,
        project_name="demo",
        name="Episode assembly",
        scope="episode",
        episode_number=1,
        **_document(),
    )


async def test_create_plan_persists_first_revision_and_revision_is_immutable(async_session) -> None:
    created = await _create(async_session)
    assert created["status"] == "draft"
    assert created["current_revision_number"] == 1
    assert created["current_revision"]["version_number"] == 1

    revised_doc = _document()
    revised_doc["source_snapshot"] = {"episode": 1, "units": [{"id": "unit-1", "version": 3}]}
    revised = await service.create_revision(
        async_session,
        created["id"],
        user_id="user-1",
        **revised_doc,
    )
    assert revised["current_revision_number"] == 2
    assert revised["status"] == "draft"

    rows = (
        (
            await async_session.execute(
                select(AssemblyPlanRevision)
                .where(AssemblyPlanRevision.plan_id == created["id"])
                .order_by(AssemblyPlanRevision.version_number)
            )
        )
        .scalars()
        .all()
    )
    assert [row.version_number for row in rows] == [1, 2]
    assert '"version":2' in rows[0].source_snapshot_json
    assert '"version":3' in rows[1].source_snapshot_json


async def test_plan_access_is_scoped_to_owner(async_session) -> None:
    created = await _create(async_session, user_id="owner")
    with pytest.raises(service.AssemblyPlanNotFoundError):
        await service.get_plan(async_session, created["id"], user_id="other")


async def test_running_plan_rejects_new_revision(async_session) -> None:
    created = await _create(async_session)
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="confirmed")
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="preview_pending")
    with pytest.raises(service.AssemblyPlanConflictError) as exc_info:
        await service.create_revision(async_session, created["id"], user_id="user-1", **_document())
    assert exc_info.value.code == "plan_busy"


async def test_stale_check_marks_changed_source_and_preserves_matching_source(async_session) -> None:
    created = await _create(async_session)
    same = await service.check_stale(
        async_session, created["id"], user_id="user-1", current_source_snapshot=_document()["source_snapshot"]
    )
    assert same["stale"] is False
    assert same["status"] == "draft"

    changed = {"episode": 1, "units": [{"id": "unit-1", "version": 9}]}
    stale = await service.check_stale(async_session, created["id"], user_id="user-1", current_source_snapshot=changed)
    assert stale["stale"] is True
    assert stale["status"] == "stale"


async def test_source_manifest_is_normalized_and_stale_check_uses_automatic_fingerprint(async_session) -> None:
    manifest = {
        "contract_version": "episode-media-manifest/v1",
        "script": "episode_1.json",
        "episode": 1,
        "project_manifest": {"name": "demo"},
        "items": [
            {
                "order": 1,
                "unit_id": "unit-1",
                "source": {"kind": "generated_video", "path": "videos/unit-1.mp4"},
                "version": 2,
                "file_fingerprint": {"exists": True, "size": 12, "mtime_ns": 1, "sha256": "abc"},
                "media_probe": {"has_video_stream": True, "duration_seconds": 8},
            }
        ],
    }
    document = _document()
    document["source_manifest"] = manifest
    created = await service.create_plan(
        async_session,
        user_id="user-1",
        project_name="demo",
        name="Manifest assembly",
        scope="episode",
        episode_number=1,
        **document,
    )
    snapshot = created["current_revision"]["source_snapshot"]
    assert snapshot["project"]["name"] == "demo"
    assert snapshot["script"] == "episode_1.json"
    assert snapshot["items"][0]["source"]["path"] == "videos/unit-1.mp4"
    assert snapshot["items"][0]["file_fingerprint"]["sha256"] == "abc"
    assert snapshot["items"][0]["version"] == 2

    changed_manifest = {**manifest, "items": [{**manifest["items"][0], "version": 3}]}
    stale = await service.check_stale(
        async_session,
        created["id"],
        user_id="user-1",
        current_source_manifest=changed_manifest,
    )
    assert stale["stale"] is True
    assert stale["status"] == "stale"


async def test_render_requires_preview_ready(async_session) -> None:
    created = await _create(async_session)
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="confirmed")
    with pytest.raises(service.AssemblyPlanConflictError) as exc_info:
        await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="render_pending")
    assert exc_info.value.code == "invalid_status_transition"

    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="preview_pending")
    preview = await service.mark_preview_ready(
        async_session, created["id"], user_id="user-1", revision_number=created["current_revision_number"]
    )
    assert preview["status"] == "preview_ready"
    confirmed_preview = await service.confirm_preview(
        async_session, created["id"], user_id="user-1", revision_number=created["current_revision_number"]
    )
    assert confirmed_preview["preview_confirmed_by"] == "user-1"
    ready = await service.confirm_render(
        async_session,
        created["id"],
        user_id="user-1",
        revision_number=created["current_revision_number"],
    )
    assert ready["status"] == "render_pending"
    assert ready["render_confirmed_by"] == "user-1"


async def test_preview_ready_requires_pending_status_and_current_revision(async_session) -> None:
    created = await _create(async_session)

    with pytest.raises(service.AssemblyPlanConflictError) as exc_info:
        await service.mark_preview_ready(
            async_session,
            created["id"],
            user_id="user-1",
            revision_number=created["current_revision_number"],
        )
    assert exc_info.value.code == "preview_pending_required"
    draft = await service.get_plan(async_session, created["id"], user_id="user-1")
    assert draft["status"] == "draft"
    assert draft["preview_revision_number"] is None
    assert draft["preview_ready_at"] is None

    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="confirmed")
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="preview_pending")
    with pytest.raises(service.AssemblyPlanConflictError) as exc_info:
        await service.mark_preview_ready(
            async_session,
            created["id"],
            user_id="user-1",
            revision_number=created["current_revision_number"] + 1,
        )
    assert exc_info.value.code == "revision_conflict"
    pending = await service.get_plan(async_session, created["id"], user_id="user-1")
    assert pending["status"] == "preview_pending"
    assert pending["preview_revision_number"] is None
    assert pending["preview_ready_at"] is None


async def test_new_revision_invalidates_preview_and_old_render_confirmation(async_session) -> None:
    created = await _create(async_session)
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="confirmed")
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="preview_pending")
    await service.mark_preview_ready(
        async_session,
        created["id"],
        user_id="user-1",
        revision_number=1,
    )

    revised_document = _document()
    revised_document["source_snapshot"] = {"episode": 1, "units": [{"id": "unit-1", "version": 3}]}
    revised = await service.create_revision(
        async_session,
        created["id"],
        user_id="user-1",
        expected_revision=1,
        **revised_document,
    )
    assert revised["current_revision_number"] == 2
    assert revised["status"] == "draft"
    assert revised["preview_revision_number"] is None
    assert revised["preview_ready_at"] is None
    assert revised["preview_confirmed_by"] is None
    assert revised["preview_confirmed_at"] is None
    assert revised["render_confirmed_by"] is None
    assert revised["render_confirmed_at"] is None

    with pytest.raises(service.AssemblyPlanConflictError) as exc_info:
        await service.confirm_render(
            async_session,
            created["id"],
            user_id="user-1",
            revision_number=1,
        )
    assert exc_info.value.code == "preview_revision_required"


async def test_render_confirmation_records_server_timestamp_for_matching_revision(async_session, monkeypatch) -> None:
    from datetime import UTC, datetime

    created = await _create(async_session)
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="confirmed")
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="preview_pending")
    await service.mark_preview_ready(
        async_session,
        created["id"],
        user_id="user-1",
        revision_number=1,
    )
    await service.confirm_preview(async_session, created["id"], user_id="user-1", revision_number=1)

    server_now = datetime(2026, 9, 13, 12, 34, 56, tzinfo=UTC)
    monkeypatch.setattr(service, "utc_now", lambda: server_now)
    confirmed = await service.confirm_render(
        async_session,
        created["id"],
        user_id="user-1",
        revision_number=1,
    )
    assert confirmed["render_confirmed_by"] == "user-1"
    assert confirmed["render_confirmed_at"] == server_now.isoformat()


async def test_preview_confirmation_and_render_confirmation_derive_identity_from_owner(async_session) -> None:
    created = await _create(async_session)
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="confirmed")
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="preview_pending")
    await service.mark_preview_ready(
        async_session,
        created["id"],
        user_id="user-1",
        revision_number=1,
    )

    confirmed = await service.confirm_preview(async_session, created["id"], user_id="user-1", revision_number=1)
    assert confirmed["preview_confirmed_by"] == "user-1"
    rendered = await service.confirm_render(async_session, created["id"], user_id="user-1", revision_number=1)
    assert rendered["render_confirmed_by"] == "user-1"


async def test_render_confirmation_requires_preview_confirmation(async_session) -> None:
    created = await _create(async_session)
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="confirmed")
    await service.transition_plan(async_session, created["id"], user_id="user-1", target_status="preview_pending")
    await service.mark_preview_ready(async_session, created["id"], user_id="user-1", revision_number=1)

    with pytest.raises(service.AssemblyPlanConflictError) as exc_info:
        await service.confirm_render(async_session, created["id"], user_id="user-1", revision_number=1)
    assert exc_info.value.code == "preview_confirmation_required"
