"""Persistence service for versioned media assembly plans."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.assembly_plan import AssemblyPlan, AssemblyPlanRevision
from lib.db.repositories.assembly_plan_repository import AssemblyPlanRepository
from lib.media_assembly.plan import (
    AssemblyPlanTransitionError,
    AssemblyPlanValidationError,
    assert_transition,
    is_running_status,
    source_fingerprint,
    validate_plan_document,
)
from lib.media_assembly.source_snapshot import build_source_snapshot


class AssemblyPlanNotFoundError(LookupError):
    """Raised when a plan is absent or owned by another user."""


class AssemblyPlanConflictError(RuntimeError):
    """Raised when the requested operation conflicts with the plan state."""

    def __init__(self, code: str, *, status: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str) -> Any:
    return json.loads(value)


def _revision_payload(revision: AssemblyPlanRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "plan_id": revision.plan_id,
        "version_number": revision.version_number,
        "source_fingerprint": revision.source_fingerprint,
        "source_snapshot": _loads(revision.source_snapshot_json),
        "timeline": _loads(revision.timeline_json),
        "audio": _loads(revision.audio_json),
        "subtitle": _loads(revision.subtitle_json),
        "packaging": _loads(revision.packaging_json),
        "output_profile": _loads(revision.output_profile_json),
        "validation": _loads(revision.validation_json),
        "created_by": revision.created_by,
        "created_at": revision.created_at.isoformat(),
    }


def _plan_payload(plan: AssemblyPlan, revision: AssemblyPlanRevision | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": plan.id,
        "user_id": plan.user_id,
        "project_name": plan.project_name,
        "scope": plan.scope,
        "episode_number": plan.episode_number,
        "name": plan.name,
        "status": plan.status,
        "current_revision_number": plan.current_revision_number,
        "current_source_fingerprint": plan.current_source_fingerprint,
        "preview_revision_number": plan.preview_revision_number,
        "preview_ready_at": plan.preview_ready_at.isoformat() if plan.preview_ready_at else None,
        "preview_confirmed_by": plan.preview_confirmed_by,
        "preview_confirmed_at": plan.preview_confirmed_at.isoformat() if plan.preview_confirmed_at else None,
        "render_confirmed_by": plan.render_confirmed_by,
        "render_confirmed_at": plan.render_confirmed_at.isoformat() if plan.render_confirmed_at else None,
        "created_at": plan.created_at.isoformat(),
        "updated_at": plan.updated_at.isoformat(),
    }
    if revision is not None:
        payload["current_revision"] = _revision_payload(revision)
    return payload


async def _owned_plan(repository: AssemblyPlanRepository, plan_id: str, user_id: str) -> AssemblyPlan:
    plan = await repository.get_owned(plan_id, user_id=user_id)
    if plan is None:
        raise AssemblyPlanNotFoundError(plan_id)
    return plan


async def _current_revision(repository: AssemblyPlanRepository, plan: AssemblyPlan) -> AssemblyPlanRevision:
    revision = await repository.get_current_revision(plan)
    if revision is None:
        raise AssemblyPlanConflictError("current_revision_missing", status=plan.status)
    return revision


def _resolve_source_snapshot(
    *,
    project_name: str,
    source_manifest: Mapping[str, Any] | None,
    source_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve the canonical source snapshot at the service boundary.

    New callers provide a live source manifest. ``source_snapshot`` remains a
    compatibility input for the HTTP contract, but is normalized through the
    same builder and is never required by the Agent MCP adapter.
    """
    if source_manifest is not None:
        return build_source_snapshot(project_name=project_name, source_manifest=source_manifest)
    if source_snapshot is not None:
        return build_source_snapshot(project_name=project_name, source_manifest=source_snapshot)
    return build_source_snapshot(project_name=project_name, source_manifest={})


def _validate_payload(
    *,
    source_snapshot: Mapping[str, Any],
    timeline: Sequence[Mapping[str, Any]],
    audio: Mapping[str, Any],
    subtitle: Mapping[str, Any],
    packaging: Mapping[str, Any],
    output_profile: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    validation = validate_plan_document(
        source_snapshot=source_snapshot,
        timeline=timeline,
        audio=audio,
        subtitle=subtitle,
        packaging=packaging,
        output_profile=output_profile,
    )
    return source_fingerprint(source_snapshot), validation


async def create_plan(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    name: str,
    scope: str,
    episode_number: int | None,
    source_snapshot: Mapping[str, Any] | None = None,
    source_manifest: Mapping[str, Any] | None = None,
    timeline: Sequence[Mapping[str, Any]] = (),
    audio: Mapping[str, Any] | None = None,
    subtitle: Mapping[str, Any] | None = None,
    packaging: Mapping[str, Any] | None = None,
    output_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_snapshot = _resolve_source_snapshot(
        project_name=project_name, source_manifest=source_manifest, source_snapshot=source_snapshot
    )
    audio = audio or {}
    subtitle = subtitle or {}
    packaging = packaging or {}
    output_profile = output_profile or {"format": "mp4"}
    fingerprint, validation = _validate_payload(
        source_snapshot=resolved_snapshot,
        timeline=timeline,
        audio=audio,
        subtitle=subtitle,
        packaging=packaging,
        output_profile=output_profile,
    )
    repository = AssemblyPlanRepository(session)
    now = utc_now()
    plan = AssemblyPlan(
        id=str(uuid.uuid4()),
        user_id=user_id,
        project_name=project_name,
        scope=scope,
        episode_number=episode_number,
        name=name,
        status="draft",
        current_revision_number=1,
        current_source_fingerprint=fingerprint,
        preview_revision_number=None,
        preview_ready_at=None,
        preview_confirmed_by=None,
        preview_confirmed_at=None,
        render_confirmed_by=None,
        render_confirmed_at=None,
        created_at=now,
        updated_at=now,
    )
    revision = _new_revision(
        plan_id=plan.id,
        version_number=1,
        user_id=user_id,
        created_at=now,
        source_snapshot=resolved_snapshot,
        timeline=timeline,
        audio=audio,
        subtitle=subtitle,
        packaging=packaging,
        output_profile=output_profile,
        fingerprint=fingerprint,
        validation=validation,
    )
    await repository.add_plan(plan, revision)
    return _plan_payload(plan, revision)


def _new_revision(
    *,
    plan_id: str,
    version_number: int,
    user_id: str,
    created_at: datetime,
    source_snapshot: Mapping[str, Any],
    timeline: Sequence[Mapping[str, Any]],
    audio: Mapping[str, Any],
    subtitle: Mapping[str, Any],
    packaging: Mapping[str, Any],
    output_profile: Mapping[str, Any],
    fingerprint: str,
    validation: Mapping[str, Any],
) -> AssemblyPlanRevision:
    return AssemblyPlanRevision(
        id=str(uuid.uuid4()),
        plan_id=plan_id,
        version_number=version_number,
        source_fingerprint=fingerprint,
        source_snapshot_json=_json(source_snapshot),
        timeline_json=_json(timeline),
        audio_json=_json(audio),
        subtitle_json=_json(subtitle),
        packaging_json=_json(packaging),
        output_profile_json=_json(output_profile),
        validation_json=_json(validation),
        created_by=user_id,
        created_at=created_at,
    )


async def list_plans(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
) -> list[dict[str, Any]]:
    repository = AssemblyPlanRepository(session)
    plans = await repository.list_by_project(user_id=user_id, project_name=project_name)
    return [_plan_payload(plan) for plan in plans]


async def get_plan(session: AsyncSession, plan_id: str, *, user_id: str) -> dict[str, Any]:
    repository = AssemblyPlanRepository(session)
    plan = await _owned_plan(repository, plan_id, user_id)
    revision = await _current_revision(repository, plan)
    return _plan_payload(plan, revision)


async def create_revision(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    source_snapshot: Mapping[str, Any] | None = None,
    source_manifest: Mapping[str, Any] | None = None,
    timeline: Sequence[Mapping[str, Any]] = (),
    audio: Mapping[str, Any] | None = None,
    subtitle: Mapping[str, Any] | None = None,
    packaging: Mapping[str, Any] | None = None,
    output_profile: Mapping[str, Any] | None = None,
    validation_metadata: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    repository = AssemblyPlanRepository(session)
    plan = await _owned_plan(repository, plan_id, user_id)
    resolved_snapshot = _resolve_source_snapshot(
        project_name=plan.project_name, source_manifest=source_manifest, source_snapshot=source_snapshot
    )
    audio = audio or {}
    subtitle = subtitle or {}
    packaging = packaging or {}
    output_profile = output_profile or {"format": "mp4"}
    if expected_revision is not None and plan.current_revision_number != expected_revision:
        raise AssemblyPlanConflictError("revision_conflict", status=plan.status)
    if is_running_status(plan.status):
        raise AssemblyPlanConflictError("plan_busy", status=plan.status)
    fingerprint, validation = _validate_payload(
        source_snapshot=resolved_snapshot,
        timeline=timeline,
        audio=audio,
        subtitle=subtitle,
        packaging=packaging,
        output_profile=output_profile,
    )
    if validation_metadata is not None:
        validation = dict(validation_metadata)
    now = utc_now()
    revision = _new_revision(
        plan_id=plan.id,
        version_number=plan.current_revision_number + 1,
        user_id=user_id,
        created_at=now,
        source_snapshot=resolved_snapshot,
        timeline=timeline,
        audio=audio,
        subtitle=subtitle,
        packaging=packaging,
        output_profile=output_profile,
        fingerprint=fingerprint,
        validation=validation,
    )
    await repository.add_revision(revision)
    if not await repository.advance_revision(
        plan,
        expected_revision=plan.current_revision_number,
        new_fingerprint=fingerprint,
        updated_at=now,
    ):
        raise AssemblyPlanConflictError("revision_conflict", status=plan.status)
    # A new immutable revision invalidates any approval tied to the old preview.
    plan.preview_confirmed_by = None
    plan.preview_confirmed_at = None
    await repository.flush()
    return _plan_payload(plan, revision)


async def transition_plan(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    target_status: str,
) -> dict[str, Any]:
    repository = AssemblyPlanRepository(session)
    plan = await _owned_plan(repository, plan_id, user_id)
    try:
        assert_transition(plan.status, target_status)
    except AssemblyPlanTransitionError as exc:
        raise AssemblyPlanConflictError("invalid_status_transition", status=plan.status) from exc
    if target_status == "preview_ready":
        raise AssemblyPlanConflictError("preview_task_required", status=plan.status)
    if target_status in {"render_pending", "rendering"}:
        raise AssemblyPlanConflictError("render_confirmation_required", status=plan.status)
    plan.status = target_status
    plan.updated_at = utc_now()
    await repository.flush()
    return await get_plan(session, plan_id, user_id=user_id)


async def mark_preview_ready(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    revision_number: int,
) -> dict[str, Any]:
    """Mark a successfully completed preview for exactly one immutable revision."""
    repository = AssemblyPlanRepository(session)
    plan = await _owned_plan(repository, plan_id, user_id)
    if plan.current_revision_number != revision_number:
        raise AssemblyPlanConflictError("revision_conflict", status=plan.status)
    if plan.status != "preview_pending":
        raise AssemblyPlanConflictError("preview_pending_required", status=plan.status)
    now = utc_now()
    plan.preview_revision_number = revision_number
    plan.preview_ready_at = now
    plan.status = "preview_ready"
    plan.updated_at = now
    await repository.flush()
    return await get_plan(session, plan_id, user_id=user_id)


async def confirm_preview(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    revision_number: int,
) -> dict[str, Any]:
    """Record the authenticated user's approval of one ready preview revision."""
    repository = AssemblyPlanRepository(session)
    plan = await _owned_plan(repository, plan_id, user_id)
    if plan.current_revision_number != revision_number or plan.preview_revision_number != revision_number:
        raise AssemblyPlanConflictError("revision_conflict", status=plan.status)
    if plan.status != "preview_ready":
        raise AssemblyPlanConflictError("preview_ready_required", status=plan.status)

    now = utc_now()
    result = await session.execute(
        update(AssemblyPlan)
        .where(
            AssemblyPlan.id == plan_id,
            AssemblyPlan.user_id == user_id,
            AssemblyPlan.status == "preview_ready",
            AssemblyPlan.current_revision_number == revision_number,
            AssemblyPlan.preview_revision_number == revision_number,
        )
        .values(preview_confirmed_by=user_id, preview_confirmed_at=now, updated_at=now)
    )
    if int(getattr(result, "rowcount", 0)) != 1:
        raise AssemblyPlanConflictError("preview_confirmation_conflict", status=plan.status)
    plan.preview_confirmed_by = user_id
    plan.preview_confirmed_at = now
    plan.updated_at = now
    return await get_plan(session, plan_id, user_id=user_id)


async def confirm_render(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    revision_number: int,
) -> dict[str, Any]:
    """Record authenticated user approval before a final render is queued."""
    repository = AssemblyPlanRepository(session)
    plan = await _owned_plan(repository, plan_id, user_id)
    if plan.status != "preview_ready" or plan.preview_revision_number != revision_number:
        raise AssemblyPlanConflictError("preview_revision_required", status=plan.status)
    if plan.current_revision_number != revision_number:
        raise AssemblyPlanConflictError("revision_conflict", status=plan.status)
    if plan.preview_confirmed_by is None or plan.preview_confirmed_at is None:
        raise AssemblyPlanConflictError("preview_confirmation_required", status=plan.status)

    now = utc_now()
    result = await session.execute(
        update(AssemblyPlan)
        .where(
            AssemblyPlan.id == plan_id,
            AssemblyPlan.user_id == user_id,
            AssemblyPlan.status == "preview_ready",
            AssemblyPlan.current_revision_number == revision_number,
            AssemblyPlan.preview_revision_number == revision_number,
            AssemblyPlan.preview_confirmed_by.is_not(None),
            AssemblyPlan.preview_confirmed_at.is_not(None),
        )
        .values(render_confirmed_by=user_id, render_confirmed_at=now, status="render_pending", updated_at=now)
    )
    if int(getattr(result, "rowcount", 0)) != 1:
        raise AssemblyPlanConflictError("render_confirmation_conflict", status=plan.status)
    plan.render_confirmed_by = user_id
    plan.render_confirmed_at = now
    plan.status = "render_pending"
    plan.updated_at = now
    return await get_plan(session, plan_id, user_id=user_id)


async def check_stale(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    current_source_snapshot: Mapping[str, Any] | None = None,
    current_source_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    repository = AssemblyPlanRepository(session)
    plan = await _owned_plan(repository, plan_id, user_id)
    resolved_snapshot = _resolve_source_snapshot(
        project_name=plan.project_name,
        source_manifest=current_source_manifest,
        source_snapshot=current_source_snapshot,
    )
    current_fingerprint = source_fingerprint(resolved_snapshot)
    stale = current_fingerprint != plan.current_source_fingerprint
    if stale and plan.status != "stale":
        plan.status = "stale"
        plan.updated_at = utc_now()
        await repository.flush()
    payload = await get_plan(session, plan_id, user_id=user_id)
    payload["stale"] = stale
    payload["current_source_fingerprint"] = current_fingerprint
    return payload


__all__ = [
    "AssemblyPlanConflictError",
    "AssemblyPlanNotFoundError",
    "AssemblyPlanValidationError",
    "check_stale",
    "confirm_preview",
    "confirm_render",
    "create_plan",
    "create_revision",
    "get_plan",
    "list_plans",
    "mark_preview_ready",
    "transition_plan",
]
