"""Application adapter for compiling Creation Plans from Project data."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.config.registry import PROVIDER_REGISTRY, model_info_for
from lib.config.resolver import VideoBucketCapabilityError
from lib.creation_plan import CreationPlan, CreationPlanError, ProjectContextSnapshot
from lib.creation_skills import (
    OFFICIAL_CREATION_SKILLS,
    CreationSkillDefinition,
    CreationSkillVersion,
    compatibility_report,
)
from lib.db.base import utc_now
from lib.db.models.creation_plan import CreationCompatibilityEvent, CreationPlanRecord
from lib.db.models.workflow import WorkflowNode, WorkflowRevision, WorkflowRun
from server.services import workflows as workflow_service
from server.services.generation_context import (
    AudioLaneRequest,
    ImageLaneRequest,
    VideoLaneRequest,
    resolve_generation_context,
)


@dataclass(frozen=True, slots=True)
class CreationPlanPreview:
    """User-facing preview; it is intentionally separate from starting a run."""

    plan: CreationPlan
    resource_ids: tuple[str, ...]
    parameters: dict[str, object]
    estimated_cost: float
    steps: tuple[str, ...]
    review_points: tuple[str, ...]
    resource_mapping: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        result = self.plan.to_dict()
        result.update(
            {
                "content_mode_snapshot": self.plan.project_context.content_mode,
                "generation_mode_snapshot": self.plan.project_context.generation_mode,
                "grid_storyboard_snapshot": self.plan.project_context.grid_storyboard,
                "aspect_ratio_snapshot": self.plan.project_context.aspect_ratio,
                "style_snapshot": self.plan.project_context.style,
                "model_config_snapshot": self.plan.project_context.to_dict()["model_config"],
                "resource_ids": list(self.resource_ids),
                "resource_mapping": [dict(item) for item in self.resource_mapping],
                "parameters": dict(self.parameters),
                "estimated_cost": self.estimated_cost,
                "steps": list(self.steps),
                "review_points": list(self.review_points),
            }
        )
        return result


_FORBIDDEN_OVERRIDES = frozenset({"generation_mode_override", "content_mode_override", "grid_storyboard_override"})


class CreationPlanNotFoundError(LookupError):
    """The requested plan is not visible to the current user."""


class CreationPlanStartError(ValueError):
    """A plan cannot start without creating a WorkflowRun."""

    def __init__(self, code: str, *, report: Mapping[str, object] | None = None):
        self.code = code
        self.report = dict(report or {})
        super().__init__(code)


async def _creation_plan_capability_preflight(
    project_id: str,
    project: Mapping[str, object],
    revision_nodes: Sequence[WorkflowNode],
) -> dict[str, object]:
    """Resolve executable provider/model lanes before a plan is persisted or started."""

    required: set[str] = set()
    for node in revision_nodes:
        try:
            values = json.loads(node.required_capabilities_json or "[]")
        except json.JSONDecodeError:
            return {"compatible": False, "code": "workflow_capabilities_invalid", "required": []}
        if isinstance(values, list):
            required.update(str(value).strip() for value in values if str(value).strip())

    needs_image = bool(required & {"image", "t2i", "i2i", "text_to_image", "image_to_image"})
    needs_video = bool(required & {"video", "i2v", "r2v", "t2v"})
    needs_audio = bool(required & {"audio", "tts", "text_to_speech"})
    image_capability = "i2i" if required & {"i2i", "image_to_image"} else "t2i"
    video_capability = "r2v" if "r2v" in required else "i2v" if required & {"i2v", "t2v", "video"} else None

    if not (needs_image or needs_video or needs_audio):
        return {"compatible": True, "required": [], "resolved": {}}

    try:
        context = await resolve_generation_context(
            project_id,
            None,
            project=dict(project),
            image=ImageLaneRequest(capability=image_capability) if needs_image else None,
            video=VideoLaneRequest(capability=video_capability) if needs_video else None,
            audio=AudioLaneRequest() if needs_audio else None,
        )
    except (ValueError, LookupError, VideoBucketCapabilityError) as exc:
        return {
            "compatible": False,
            "code": "provider_model_capability_unavailable",
            "message": str(exc),
            "required": sorted(required),
        }
    except Exception as exc:
        return {
            "compatible": False,
            "code": "generation_configuration_incomplete",
            "message": str(exc),
            "required": sorted(required),
        }

    resolved: dict[str, object] = {}
    if context.image_lane is not None:
        resolved["image"] = {
            "provider": context.image_lane.provider_model.provider_id,
            "model": context.image_lane.provider_model.model_id,
            "capability": image_capability,
        }
    if context.video_lane is not None:
        resolved["video"] = {
            "provider": context.video_lane.provider_model.provider_id,
            "model": context.video_lane.provider_model.model_id,
            "capability": video_capability,
            "supported_durations": list(context.video_lane.supported_durations),
            "max_duration": context.video_lane.max_duration,
            "max_reference_images": context.video_lane.max_reference_images,
        }
    if context.audio_lane is not None:
        resolved["audio"] = {
            "provider": context.audio_lane.provider_model.provider_id,
            "model": context.audio_lane.provider_model.model_id,
        }
    unavailable = []
    for lane in resolved.values():
        if not isinstance(lane, Mapping):
            continue
        provider = str(lane.get("provider", ""))
        model = str(lane.get("model", ""))
        if provider in PROVIDER_REGISTRY and model_info_for(provider, model) is None:
            unavailable.append(f"{provider}/{model}")
    if unavailable:
        return {
            "compatible": False,
            "code": "provider_model_unavailable",
            "models": unavailable,
            "required": sorted(required),
        }
    return {"compatible": True, "required": sorted(required), "resolved": resolved}


def list_creation_resources(project: Mapping[str, object]) -> list[dict[str, object]]:
    """Expose selectable project entities without sending their creative payloads."""

    result: list[dict[str, object]] = []
    fields = (
        ("document", ("documents", "source_files", "sourceFiles")),
        ("character", ("characters",)),
        ("scene", ("scenes",)),
        ("prop", ("props",)),
        ("product", ("products",)),
        ("episode", ("episodes",)),
    )
    for resource_type, names in fields:
        value: object = None
        for name in names:
            if name in project:
                value = project[name]
                break
        if isinstance(value, Mapping):
            items = value.items()
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            items = ((str(index), item) for index, item in enumerate(value))
        else:
            continue
        for key, item in items:
            if isinstance(item, Mapping):
                resource_id = str(item.get("id") or item.get("file_id") or key)
                label = str(item.get("name") or item.get("title") or item.get("filename") or resource_id)
            else:
                resource_id = str(key)
                label = str(item) if item is not None else resource_id
            if resource_id.strip():
                result.append({"id": resource_id, "label": label, "type": resource_type})
    return result


def get_creation_skill_version(skill_version_id: str) -> tuple[CreationSkillDefinition, CreationSkillVersion]:
    for skill in OFFICIAL_CREATION_SKILLS:
        if skill.latest_version.id == skill_version_id:
            return skill, skill.latest_version
    raise CreationPlanError(f"unknown creation_skill_version_id: {skill_version_id}")


async def resolve_creation_skill_version(
    session: AsyncSession, skill_version_id: str
) -> tuple[CreationSkillDefinition, CreationSkillVersion]:
    """Resolve the requested release from the persisted official catalog."""

    from server.services.creation_skill_catalog import (
        get_persisted_creation_skill_version,
        sync_official_creation_skills,
    )

    resolved = await get_persisted_creation_skill_version(session, skill_version_id)
    if resolved is None:
        await sync_official_creation_skills(session)
        resolved = await get_persisted_creation_skill_version(session, skill_version_id)
    if resolved is None:
        raise CreationPlanError(f"unknown or unavailable creation_skill_version_id: {skill_version_id}")
    return resolved


async def _resolve_workflow_revision(
    session: AsyncSession,
    *,
    skill_version: CreationSkillVersion,
    requested_revision: str | None,
) -> str:
    """Resolve a concrete published revision, never a Skill id/version alias."""

    bound_revision = str(skill_version.workflow_revision_id or "").strip()
    if not bound_revision or bound_revision.startswith("official:"):
        raise CreationPlanError("CreationSkillVersion has no bound Workflow Revision")
    candidate = bound_revision
    if candidate == skill_version.id or candidate == skill_version.skill_id:
        raise CreationPlanError("CreationPlan requires a concrete Workflow Revision id")
    if requested_revision and requested_revision != candidate:
        raise CreationPlanError("requested workflow_revision does not match the Skill Version binding")
    revision = await session.get(WorkflowRevision, candidate)
    if revision is None:
        raise CreationPlanError("Workflow Revision was not found")
    if revision.status != "published":
        raise CreationPlanError("Workflow Revision must be published")
    return candidate


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _plan_response(record: CreationPlanRecord, *, deduped: bool) -> dict[str, object]:
    response = json.loads(record.preview_json)
    response.update(
        {
            "status": record.status,
            "workflow_run_id": record.workflow_run_id,
            "created_at": record.created_at.isoformat(),
            "deduped": deduped,
        }
    )
    return response


def _alternative_skill_ids(
    skill: CreationSkillDefinition, project: Mapping[str, object], available_inputs: set[str]
) -> tuple[str, ...]:
    return tuple(
        other.id
        for other in OFFICIAL_CREATION_SKILLS
        if other.id != skill.id
        and other.active
        and other.latest_version.compatibility.check(project, available_inputs) is None
    )


def _normalize_resource_mapping(
    resource_mapping: Sequence[Mapping[str, object]] | None,
    resource_ids: Sequence[str],
    resource_types: Iterable[str],
) -> tuple[dict[str, str], ...]:
    seen: set[tuple[str, str, str]] = set()
    normalized: list[dict[str, str]] = []
    for item in resource_mapping or ():
        resource_id = str(item.get("id", "")).strip()
        resource_type = str(item.get("type", "")).strip()
        source = str(item.get("source", "")).strip()
        if not resource_id or not resource_type:
            continue
        key = (resource_id, resource_type, source)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"id": resource_id, "type": resource_type, **({"source": source} if source else {})})
    if normalized:
        return tuple(normalized)
    fallback_type = next(iter(sorted({str(value).strip() for value in resource_types if str(value).strip()})), "")
    return tuple(
        {"id": str(resource_id).strip(), "type": fallback_type}
        for resource_id in resource_ids
        if str(resource_id).strip() and fallback_type
    )


async def create_creation_plan_preview(
    session: AsyncSession,
    *,
    user_id: str,
    workspace_id: str,
    project_id: str,
    creation_skill_version_id: str,
    project: Mapping[str, object],
    resource_ids: Sequence[str],
    resource_types: Iterable[str],
    resource_mapping: Sequence[Mapping[str, object]] | None = None,
    parameters: Mapping[str, object],
    workflow_revision: str | None,
    estimated_cost: float | None,
    steps: Sequence[str] | None,
    review_points: Sequence[str] | None,
    idempotency_key: str,
) -> dict[str, object]:
    """Persist a deterministic, preview-only plan with no generation side effect."""

    existing = (
        await session.execute(
            select(CreationPlanRecord).where(
                CreationPlanRecord.user_id == user_id,
                CreationPlanRecord.project_id == project_id,
                CreationPlanRecord.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _plan_response(existing, deduped=True)

    available_inputs = {str(value) for value in resource_types}
    normalized_resource_ids = tuple(dict.fromkeys(str(value).strip() for value in resource_ids if str(value).strip()))
    if not normalized_resource_ids:
        raise CreationPlanError("at least one real resource must be selected")
    normalized_mapping = _normalize_resource_mapping(resource_mapping, normalized_resource_ids, available_inputs)
    if normalized_mapping:
        normalized_resource_ids = tuple(item["id"] for item in normalized_mapping)
        available_inputs = {item["type"] for item in normalized_mapping}
    skill, skill_version = await resolve_creation_skill_version(session, creation_skill_version_id)
    workflow_revision = await _resolve_workflow_revision(
        session, skill_version=skill_version, requested_revision=workflow_revision
    )
    if estimated_cost is not None and (not math.isfinite(estimated_cost) or estimated_cost < 0):
        raise CreationPlanError("estimated_cost must be finite and non-negative")
    effective_steps = tuple(str(value) for value in (steps or ()))
    effective_review_points = tuple(str(value) for value in (review_points or ()))
    effective_cost = estimated_cost
    revision_nodes = (
        (await session.execute(select(WorkflowNode).where(WorkflowNode.revision_id == workflow_revision)))
        .scalars()
        .all()
    )
    if revision_nodes:
        if not effective_steps:
            effective_steps = tuple(node.node_key for node in revision_nodes)
        if not effective_review_points:
            effective_review_points = tuple(
                node.node_key
                for node in revision_nodes
                if node.approval_policy_json and node.approval_policy_json != "{}"
            )
        # The published Workflow Revision is the source of truth for cost.  A
        # client-supplied estimate must not make a persisted plan look cheaper
        # or more expensive than the executable graph.
        effective_cost = sum(float(node.estimated_cost) for node in revision_nodes)
    preview = compile_creation_plan_preview(
        creation_skill_version=skill_version,
        project_id=project_id,
        project=project,
        resource_ids=normalized_resource_ids,
        resource_types=available_inputs,
        resource_mapping=normalized_mapping,
        parameters=parameters,
        workflow_revision=workflow_revision,
        estimated_cost=0.0 if effective_cost is None else effective_cost,
        steps=effective_steps,
        review_points=effective_review_points,
    )
    report = compatibility_report(
        skill,
        project,
        available_inputs,
        alternatives=_alternative_skill_ids(skill, project, available_inputs),
    )
    compatibility_event_id: str | None = None
    if not preview.plan.is_compatible:
        compatibility_event_id = uuid.uuid4().hex
        report["event_id"] = compatibility_event_id
    response = preview.to_dict()
    response["compatibility_report"] = report
    response["workflow_revision"] = workflow_revision
    response["required_capabilities"] = sorted(
        {
            str(capability)
            for node in revision_nodes
            for capability in json.loads(node.required_capabilities_json or "[]")
            if str(capability).strip()
        }
    )
    capability_report = await _creation_plan_capability_preflight(project_id, project, revision_nodes)
    response["capability_report"] = capability_report
    if not capability_report.get("compatible", False):
        report["compatible"] = False
        report["capability"] = capability_report
    now = utc_now()
    record = CreationPlanRecord(
        id=preview.plan.plan_id,
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=project_id,
        creation_skill_version_id=creation_skill_version_id,
        skill_id=skill.id,
        workflow_revision=workflow_revision,
        fingerprint=preview.plan.fingerprint,
        idempotency_key=idempotency_key,
        project_snapshot_json=_json(preview.plan.project_context.to_dict()),
        resource_ids_json=_json(list(preview.resource_ids)),
        parameters_json=_json(preview.parameters),
        preview_json=_json(response),
        estimated_cost=preview.estimated_cost,
        status="previewed",
        created_by=user_id,
        created_at=now,
    )
    session.add(record)
    if not preview.plan.is_compatible:
        session.add(
            CreationCompatibilityEvent(
                id=compatibility_event_id,
                creation_skill_version_id=creation_skill_version_id,
                project_content_mode=str(project.get("content_mode", "")),
                project_generation_mode=str(project.get("generation_mode", "")),
                resource_types_json=_json(sorted(available_inputs)),
                reason=preview.plan.compatibility.reasons[0],
                outcome="unresolved",
                created_at=now,
            )
        )
    await session.commit()
    return _plan_response(record, deduped=False)


async def get_creation_plan(session: AsyncSession, plan_id: str, *, user_id: str) -> dict[str, object]:
    result = await session.execute(select(CreationPlanRecord).where(CreationPlanRecord.id == plan_id).with_for_update())
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise CreationPlanNotFoundError(plan_id)
    if record.workflow_run_id:
        run = await session.get(WorkflowRun, record.workflow_run_id)
        if run is not None:
            projected_status = {
                "succeeded": "succeeded",
                "failed": "failed",
                "cancelled": "cancelled",
            }.get(run.status)
            if projected_status and record.status != projected_status:
                record.status = projected_status
                await session.commit()
    return _plan_response(record, deduped=False)


async def compatibility_metrics(session: AsyncSession) -> dict[str, object]:
    """Aggregate anonymous incompatibility events for rollout decisions."""

    rows = (
        await session.execute(
            select(
                CreationCompatibilityEvent.creation_skill_version_id,
                CreationCompatibilityEvent.project_generation_mode,
                CreationCompatibilityEvent.reason,
                CreationCompatibilityEvent.outcome,
                func.count().label("count"),
            )
            .group_by(
                CreationCompatibilityEvent.creation_skill_version_id,
                CreationCompatibilityEvent.project_generation_mode,
                CreationCompatibilityEvent.reason,
                CreationCompatibilityEvent.outcome,
            )
            .order_by(CreationCompatibilityEvent.creation_skill_version_id)
        )
    ).all()
    return {
        "items": [
            {
                "creation_skill_version_id": skill_version_id,
                "project_generation_mode": generation_mode,
                "reason": reason,
                "outcome": outcome,
                "count": count,
            }
            for skill_version_id, generation_mode, reason, outcome, count in rows
        ]
    }


_COMPATIBILITY_OUTCOMES = frozenset({"cancelled", "alternative_skill", "new_project"})


async def record_compatibility_outcome(
    session: AsyncSession,
    event_id: str,
    *,
    outcome: str,
) -> dict[str, object]:
    """Record only the user's coarse follow-up choice, never creative content."""

    if outcome not in _COMPATIBILITY_OUTCOMES:
        raise ValueError("invalid compatibility outcome")
    event = await session.get(CreationCompatibilityEvent, event_id)
    if event is None:
        raise CreationPlanNotFoundError(event_id)
    event.outcome = outcome
    await session.commit()
    return {
        "event_id": event.id,
        "creation_skill_version_id": event.creation_skill_version_id,
        "project_generation_mode": event.project_generation_mode,
        "outcome": event.outcome,
    }


async def start_creation_plan(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    project: Mapping[str, object],
    mode: str = "hybrid",
    script_revision_id: str | None = None,
    episode_id: str | None = None,
    budget_limit: float | None = None,
    cost_confirmed: bool = False,
    review_confirmed: bool = False,
) -> dict[str, object]:
    """Start exactly one WorkflowRun after rechecking the Project snapshot."""

    result = await session.execute(select(CreationPlanRecord).where(CreationPlanRecord.id == plan_id).with_for_update())
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise CreationPlanNotFoundError(plan_id)
    if record.status == "cancelled":
        raise CreationPlanStartError("creation_plan_cancelled")
    if record.status == "invalidated":
        raise CreationPlanStartError("creation_plan_invalidated")
    if record.workflow_run_id:
        existing_run = await session.get(WorkflowRun, record.workflow_run_id)
        if existing_run is None:
            raise CreationPlanStartError("workflow_run_missing")
        run_status = existing_run.status
        if run_status == "planned":
            transitioned = await workflow_service.transition_workflow_run(
                session,
                run_id=existing_run.id,
                target="running",
                expected_version=existing_run.version,
                actor_id=user_id,
            )
            run_status = str(transitioned.get("status") or "running")
        if run_status == "running":
            record.status = "running"
            record.started_at = record.started_at or utc_now()
            await session.commit()
        dispatch = await workflow_service.request_workflow_run_execution(
            session, run_id=record.workflow_run_id, actor_id=user_id
        )
        return {
            "plan_id": record.id,
            "workflow_run_id": record.workflow_run_id,
            "status": record.status,
            "deduped": True,
            "run_status": run_status,
            "dispatch_status": dispatch["dispatch_status"],
        }

    current_snapshot = ProjectContextSnapshot.from_project(record.project_id, project).to_dict()
    expected_snapshot = json.loads(record.project_snapshot_json)
    if current_snapshot != expected_snapshot:
        raise CreationPlanStartError("project_snapshot_changed")

    revision = await session.get(WorkflowRevision, record.workflow_revision)
    if revision is None or revision.status != "published":
        raise CreationPlanStartError("workflow_revision_unavailable")

    preview = json.loads(record.preview_json)
    report = preview.get("compatibility_report", {})
    if not report.get("compatible", False):
        raise CreationPlanStartError("creation_skill_incompatible", report=report)
    estimated_cost = float(preview.get("estimated_cost") or 0.0)
    review_points = preview.get("review_points")
    if budget_limit is not None and estimated_cost > budget_limit:
        raise CreationPlanStartError(
            "creation_plan_budget_exceeded",
            report={"estimated_cost": estimated_cost, "budget_limit": budget_limit},
        )
    if estimated_cost > 0 and not cost_confirmed:
        raise CreationPlanStartError(
            "creation_plan_cost_confirmation_required",
            report={"estimated_cost": estimated_cost},
        )
    if isinstance(review_points, list) and review_points and not review_confirmed:
        raise CreationPlanStartError(
            "creation_plan_review_confirmation_required",
            report={"review_points": review_points},
        )
    existing_run = await workflow_service.find_workflow_run_for_creation_plan(
        session,
        creation_plan_id=record.id,
        project_id=record.project_id,
        actor_id=user_id,
    )
    if existing_run is not None:
        run_id = str(existing_run["id"])
        run_status = str(existing_run.get("status") or "planned")
        if run_status == "planned":
            transitioned = await workflow_service.transition_workflow_run(
                session,
                run_id=run_id,
                target="running",
                expected_version=int(existing_run["version"]),
                actor_id=user_id,
            )
            run_status = str(transitioned.get("status") or "running")
        record.workflow_run_id = run_id
        record.status = "running" if run_status == "running" else "started"
        record.started_at = record.started_at or utc_now()
        await session.commit()
        dispatch = await workflow_service.request_workflow_run_execution(session, run_id=run_id, actor_id=user_id)
        return {
            "plan_id": record.id,
            "workflow_run_id": run_id,
            "status": record.status,
            "run_status": run_status,
            "deduped": True,
            "dispatch_status": dispatch["dispatch_status"],
        }
    run = await workflow_service.plan_run(
        session,
        revision_id=record.workflow_revision,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        script_revision_id=script_revision_id,
        mode=mode,
        input_snapshot={"creation_plan_id": record.id, "creation_plan": preview},
        actor_id=user_id,
        episode_id=episode_id,
        budget_limit=budget_limit,
    )
    run_status = str(run.get("status") or "planned")
    if run_status == "planned" and isinstance(run.get("version"), int):
        transitioned = await workflow_service.transition_workflow_run(
            session,
            run_id=str(run["id"]),
            target="running",
            expected_version=int(run["version"]),
            actor_id=user_id,
        )
        run_status = str(transitioned.get("status") or "running")
    record.workflow_run_id = str(run["id"])
    record.status = "running" if run_status == "running" else "started"
    record.started_at = utc_now()
    await session.commit()
    run_id = str(record.workflow_run_id)
    dispatch = await workflow_service.request_workflow_run_execution(session, run_id=run_id, actor_id=user_id)
    return {
        "plan_id": record.id,
        "workflow_run_id": run_id,
        "status": record.status,
        "deduped": bool(run.get("deduped", False)),
        "run_status": run_status,
        "dispatch_status": dispatch["dispatch_status"],
    }


async def cancel_creation_plan(session: AsyncSession, plan_id: str, *, user_id: str) -> dict[str, object]:
    result = await session.execute(select(CreationPlanRecord).where(CreationPlanRecord.id == plan_id).with_for_update())
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise CreationPlanNotFoundError(plan_id)
    if record.workflow_run_id:
        run = await session.get(WorkflowRun, record.workflow_run_id)
        if run is not None and run.status not in {"succeeded", "failed", "cancelled"}:
            await workflow_service.transition_workflow_run(
                session,
                run_id=run.id,
                target="cancelled",
                expected_version=run.version,
                actor_id=user_id,
            )
        record.status = "cancelled"
        record.cancelled_at = utc_now()
        await session.commit()
    elif record.status != "cancelled":
        record.status = "cancelled"
        record.cancelled_at = utc_now()
        await session.commit()
    return _plan_response(record, deduped=False)


async def invalidate_creation_plan(session: AsyncSession, plan_id: str, *, user_id: str) -> dict[str, object]:
    result = await session.execute(select(CreationPlanRecord).where(CreationPlanRecord.id == plan_id).with_for_update())
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise CreationPlanNotFoundError(plan_id)
    if record.workflow_run_id:
        raise CreationPlanStartError("creation_plan_already_started")
    if record.status not in {"cancelled", "invalidated"}:
        record.status = "invalidated"
        await session.commit()
    return _plan_response(record, deduped=False)


async def recompile_creation_plan(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    project: Mapping[str, object],
) -> dict[str, object]:
    """Compile a fresh immutable plan from the current Project snapshot."""

    result = await session.execute(select(CreationPlanRecord).where(CreationPlanRecord.id == plan_id).with_for_update())
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise CreationPlanNotFoundError(plan_id)
    if record.workflow_run_id:
        raise CreationPlanStartError("creation_plan_already_started")

    preview = json.loads(record.preview_json)
    skill_inputs = preview.get("skill_inputs", {})
    resource_types = skill_inputs.get("resource_types", []) if isinstance(skill_inputs, Mapping) else []
    resource_mapping = preview.get("resource_mapping", [])
    if not isinstance(resource_types, list):
        resource_types = []
    resource_ids = json.loads(record.resource_ids_json)
    parameters = json.loads(record.parameters_json)
    if not isinstance(resource_ids, list) or not isinstance(parameters, dict) or not isinstance(resource_mapping, list):
        raise CreationPlanStartError("creation_plan_snapshot_invalid")

    current_snapshot = ProjectContextSnapshot.from_project(record.project_id, project).to_dict()
    snapshot_key = hashlib.sha256(_json(current_snapshot).encode("utf-8")).hexdigest()
    result = await create_creation_plan_preview(
        session,
        user_id=user_id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        creation_skill_version_id=record.creation_skill_version_id,
        project=project,
        resource_ids=resource_ids,
        resource_types=[str(value) for value in resource_types],
        resource_mapping=resource_mapping,
        parameters=parameters,
        workflow_revision=None,
        estimated_cost=None,
        steps=None,
        review_points=None,
        idempotency_key=f"{record.id}:recompile:{snapshot_key}",
    )
    record.status = "invalidated"
    await session.commit()
    result["recompiled_from"] = record.id
    return result


async def restart_creation_plan(
    session: AsyncSession,
    plan_id: str,
    *,
    user_id: str,
    project: Mapping[str, object],
    mode: str = "hybrid",
    script_revision_id: str | None = None,
    episode_id: str | None = None,
    budget_limit: float | None = None,
) -> dict[str, object]:
    """Create a fresh WorkflowRun for a terminal plan while retaining its frozen inputs."""

    result = await session.execute(select(CreationPlanRecord).where(CreationPlanRecord.id == plan_id).with_for_update())
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise CreationPlanNotFoundError(plan_id)
    if not record.workflow_run_id:
        raise CreationPlanStartError("creation_plan_not_started")

    previous_run = await session.get(WorkflowRun, record.workflow_run_id)
    if previous_run is None:
        raise CreationPlanStartError("creation_plan_run_not_found")
    if previous_run.status not in {"succeeded", "failed", "cancelled"}:
        raise CreationPlanStartError("creation_plan_run_not_terminal")

    current_snapshot = ProjectContextSnapshot.from_project(record.project_id, project).to_dict()
    expected_snapshot = json.loads(record.project_snapshot_json)
    if current_snapshot != expected_snapshot:
        raise CreationPlanStartError("project_snapshot_changed")

    revision = await session.get(WorkflowRevision, record.workflow_revision)
    if revision is None or revision.status != "published":
        raise CreationPlanStartError("workflow_revision_unavailable")

    preview = json.loads(record.preview_json)
    report = preview.get("compatibility_report", {})
    if not report.get("compatible", False):
        raise CreationPlanStartError("creation_skill_incompatible", report=report)

    run = await workflow_service.plan_run(
        session,
        revision_id=record.workflow_revision,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        script_revision_id=script_revision_id,
        mode=mode,
        input_snapshot={
            "creation_plan_id": record.id,
            "creation_plan": preview,
            "restart_of_workflow_run_id": previous_run.id,
        },
        actor_id=user_id,
        episode_id=episode_id,
        budget_limit=budget_limit,
    )
    run_status = str(run.get("status") or "planned")
    if run_status == "planned" and isinstance(run.get("version"), int):
        transitioned = await workflow_service.transition_workflow_run(
            session,
            run_id=str(run["id"]),
            target="running",
            expected_version=int(run["version"]),
            actor_id=user_id,
        )
        run_status = str(transitioned.get("status") or "running")

    record.workflow_run_id = str(run["id"])
    record.status = "running" if run_status == "running" else "started"
    record.started_at = utc_now()
    record.cancelled_at = None
    await session.commit()
    return {
        "plan_id": record.id,
        "workflow_run_id": record.workflow_run_id,
        "status": record.status,
        "deduped": bool(run.get("deduped", False)),
        "restarted_from": previous_run.id,
    }


def _stable_plan_id(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "cp_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compile_creation_plan_preview(
    *,
    creation_skill_version: CreationSkillVersion,
    project_id: str,
    project: Mapping[str, object],
    resource_ids: Sequence[str] = (),
    resource_types: Iterable[str] = (),
    resource_mapping: Sequence[Mapping[str, object]] = (),
    parameters: Mapping[str, object] | None = None,
    workflow_revision: str,
    estimated_cost: float = 0.0,
    steps: Sequence[str] = (),
    review_points: Sequence[str] = (),
) -> CreationPlanPreview:
    """Compile a deterministic preview from Project-owned settings."""

    supplied_parameters = dict(parameters or {})
    forbidden = sorted(_FORBIDDEN_OVERRIDES.intersection(supplied_parameters))
    if forbidden:
        raise CreationPlanError(f"CreationPlan does not accept mode overrides: {', '.join(forbidden)}")
    normalized_resource_ids = tuple(dict.fromkeys(str(value).strip() for value in resource_ids if str(value).strip()))
    available_inputs = {str(value) for value in resource_types}
    normalized_mapping = _normalize_resource_mapping(resource_mapping, normalized_resource_ids, available_inputs)
    if normalized_mapping:
        normalized_resource_ids = tuple(item["id"] for item in normalized_mapping)
        available_inputs = {item["type"] for item in normalized_mapping}
    context = ProjectContextSnapshot.from_project(project_id, project)
    stable_payload = {
        "skill_version_id": creation_skill_version.id,
        "project_id": project_id,
        "project_snapshot": {
            "content_mode": context.content_mode,
            "generation_mode": context.generation_mode,
            "grid_storyboard": context.grid_storyboard,
            "aspect_ratio": context.aspect_ratio,
            "style": context.style,
            "model_config": context.model_config,
        },
        "resource_ids": normalized_resource_ids,
        "resource_mapping": [dict(item) for item in normalized_mapping],
        "parameters": supplied_parameters,
        "workflow_revision": workflow_revision,
    }
    plan = CreationPlan.compile(
        plan_id=_stable_plan_id(stable_payload),
        skill_id=creation_skill_version.skill_id,
        workflow_revision=workflow_revision,
        project_context=context,
        skill_inputs={
            "resource_ids": normalized_resource_ids,
            "resource_types": tuple(sorted(available_inputs)),
            "resource_mapping": [dict(item) for item in normalized_mapping],
            "parameters": supplied_parameters,
            "expected_steps": tuple(str(value) for value in steps),
            "review_points": tuple(str(value) for value in review_points),
            "estimated_cost": float(estimated_cost),
        },
        supported_content_modes=creation_skill_version.compatibility.content_modes,
        supported_generation_modes=creation_skill_version.compatibility.generation_modes,
    )
    if estimated_cost < 0:
        raise CreationPlanError("estimated_cost must be non-negative")
    return CreationPlanPreview(
        plan=plan,
        resource_ids=normalized_resource_ids,
        resource_mapping=normalized_mapping,
        parameters=supplied_parameters,
        estimated_cost=float(estimated_cost),
        steps=tuple(steps),
        review_points=tuple(review_points),
    )


def validate_creation_plan_start(preview: CreationPlanPreview, project: Mapping[str, object]) -> None:
    """Apply the start-time gates; callers must create no WorkflowRun on failure."""

    preview.plan.assert_project_matches(project)
    preview.plan.require_compatible()


def compile_project_creation_plan(
    *,
    plan_id: str,
    skill_id: str,
    workflow_revision: str,
    project_id: str,
    project: Mapping[str, object],
    skill_inputs: Mapping[str, Any],
    supported_content_modes: Iterable[str] | None = None,
    supported_generation_modes: Iterable[str] | None = None,
) -> CreationPlan:
    """Compile a plan using Project-owned mode values as the only input.

    The adapter accepts the already-loaded Project mapping so callers decide
    how to obtain and lock project data. It intentionally has no
    generation_mode argument: a plan can only snapshot that field from
    ProjectContextSnapshot.
    """

    context = ProjectContextSnapshot.from_project(project_id, project)
    return CreationPlan.compile(
        plan_id=plan_id,
        skill_id=skill_id,
        workflow_revision=workflow_revision,
        project_context=context,
        skill_inputs=skill_inputs,
        supported_content_modes=supported_content_modes,
        supported_generation_modes=supported_generation_modes,
    )
