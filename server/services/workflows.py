"""Application service for Shotwise workflow definitions and runs."""

from __future__ import annotations

import json
import math
import os
import uuid
from collections import deque
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.api_errors import ConflictError, NotFoundError
from lib.db.base import utc_now
from lib.db.models.workflow import (
    BudgetReservation,
    ProjectEventLog,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowMarketplaceReview,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRevision,
    WorkflowRun,
    WorkflowTemplate,
    WorkflowUsageStats,
)
from lib.workflow import (
    WorkflowPatch,
    WorkflowValidationError,
    apply_patch_to_graph,
    canonical_json,
    graph_hash,
    input_fingerprint,
    node_graph_edges,
    template_transition,
    transition_run,
    validate_graph,
    validate_modes,
    validate_node_contracts,
    validate_patch,
)
from server.services.workflow_contracts import WorkflowContractValidationError, validate_workflow_template_contract

ACTIVE_RUN_STATUSES = ("planned", "running", "paused", "waiting_review")
PASSED_NODE_STATUSES = frozenset({"succeeded", "skipped"})


def _flag(name: str, *, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


def marketplace_public_enabled() -> bool:
    return _flag("SHOTWISE_WORKFLOW_MARKETPLACE_PUBLIC")


def template_upload_enabled() -> bool:
    return _flag("SHOTWISE_WORKFLOW_TEMPLATE_UPLOAD")


def auto_optimization_enabled() -> bool:
    return _flag("SHOTWISE_WORKFLOW_AUTO_OPTIMIZATION")


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _snapshot_generation_mode(input_snapshot: dict[str, Any]) -> str | None:
    def find(value: Any) -> str | None:
        if isinstance(value, dict):
            explicit = value.get("project_generation_mode")
            if isinstance(explicit, str) and explicit:
                return explicit
            for key in ("project_context", "project_snapshot"):
                nested = value.get(key)
                if isinstance(nested, dict):
                    mode = nested.get("generation_mode")
                    if isinstance(mode, str) and mode:
                        return mode
            for child in value.values():
                mode = find(child)
                if mode:
                    return mode
        elif isinstance(value, list):
            for child in value:
                mode = find(child)
                if mode:
                    return mode
        return None

    return find(input_snapshot)


async def _append_event(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_id: str,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
    event_type: str,
    payload: dict[str, Any],
    actor_id: str,
    trace_id: str | None = None,
) -> ProjectEventLog:
    event = ProjectEventLog(
        event_id=uuid.uuid4().hex,
        workspace_id=workspace_id,
        project_id=project_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        event_type=event_type,
        event_version=1,
        payload_json=canonical_json(payload),
        actor_type="user",
        actor_id=actor_id,
        trace_id=trace_id,
        created_at=utc_now(),
    )
    session.add(event)
    await session.flush()
    return event


async def create_definition(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_id: str,
    name: str,
    actor_id: str,
) -> dict[str, Any]:
    now = utc_now()
    definition = WorkflowDefinition(
        id=uuid.uuid4().hex,
        user_id=actor_id,
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        scope="project",
        created_at=now,
        updated_at=now,
    )
    session.add(definition)
    event = await _append_event(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        aggregate_type="workflow_definition",
        aggregate_id=definition.id,
        aggregate_version=1,
        event_type="workflow.definition.created",
        payload={"name": name},
        actor_id=actor_id,
    )
    await session.commit()
    return {"id": definition.id, "version": 1, "event_cursor": event.seq}


async def create_revision(
    session: AsyncSession,
    *,
    definition_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    template_lock: dict[str, Any] | None,
    actor_id: str,
    content_mode: str = "drama",
    generation_mode: str = "storyboard",
    input_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_graph(nodes, edges)
    validate_modes(content_mode, generation_mode)
    validate_node_contracts(nodes)
    definition = await session.get(WorkflowDefinition, definition_id)
    if definition is None or definition.user_id != actor_id:
        raise NotFoundError("workflow_not_found", id=definition_id)

    result = await session.execute(
        select(func.max(WorkflowRevision.revision_no)).where(WorkflowRevision.definition_id == definition_id)
    )
    revision_no = int(result.scalar_one_or_none() or 0) + 1
    revision = WorkflowRevision(
        id=uuid.uuid4().hex,
        definition_id=definition_id,
        revision_no=revision_no,
        status="draft",
        content_mode=content_mode,
        generation_mode=generation_mode,
        input_schema_json=canonical_json(input_schema or {}),
        graph_hash=graph_hash(nodes, edges, include_layout=True),
        execution_hash=graph_hash(nodes, edges, include_layout=False),
        template_lock_json=canonical_json(template_lock) if template_lock is not None else None,
        created_by=actor_id,
        created_at=utc_now(),
    )
    session.add(revision)
    await session.flush()
    for node in nodes:
        session.add(
            WorkflowNode(
                id=uuid.uuid4().hex,
                revision_id=revision.id,
                node_key=str(node["node_key"]),
                node_type=str(node.get("node_type") or node["node_key"]),
                node_type_version=str(node.get("node_type_version", "1")),
                config_schema_version=str(node.get("config_schema_version", "1")),
                config_json=canonical_json(node.get("config", {})),
                ui_position_json=canonical_json(node.get("ui_position"))
                if node.get("ui_position") is not None
                else None,
                weight=float(node.get("weight", 1.0)),
                retry_policy_json=canonical_json(node.get("retry_policy"))
                if node.get("retry_policy") is not None
                else None,
                approval_policy_json=canonical_json(node.get("approval_policy"))
                if node.get("approval_policy") is not None
                else None,
                input_schema_json=canonical_json(node.get("input_schema", {})),
                output_schema_json=canonical_json(node.get("output_schema", {})),
                executor_id=str(node.get("executor_id", "builtin")),
                required_capabilities_json=canonical_json(node.get("required_capabilities", [])),
                estimated_cost=float(node.get("estimated_cost", 0)),
                cache_policy=str(node.get("cache_policy", "reuse")),
            )
        )
    for edge in edges:
        session.add(
            WorkflowEdge(
                id=uuid.uuid4().hex,
                revision_id=revision.id,
                edge_key=str(edge["edge_key"]),
                source_node_key=str(edge["source_node_key"]),
                target_node_key=str(edge["target_node_key"]),
                condition_json=canonical_json(edge.get("condition")) if edge.get("condition") is not None else None,
                on_failure=str(edge.get("on_failure", "stop")),
                priority=int(edge.get("priority", 0)),
            )
        )
    event = await _append_event(
        session,
        workspace_id=definition.workspace_id,
        project_id=definition.project_id,
        aggregate_type="workflow_revision",
        aggregate_id=revision.id,
        aggregate_version=1,
        event_type="workflow.revision.created",
        payload={"definition_id": definition_id, "revision_no": revision_no, "content_mode": content_mode},
        actor_id=actor_id,
    )
    await session.commit()
    return {
        "id": revision.id,
        "revision_no": revision_no,
        "status": revision.status,
        "graph_hash": revision.graph_hash,
        "execution_hash": revision.execution_hash,
        "content_mode": revision.content_mode,
        "generation_mode": revision.generation_mode,
        "version": 1,
        "event_cursor": event.seq,
    }


async def _revision_graph(
    session: AsyncSession, revision_id: str, *, actor_id: str | None
) -> tuple[WorkflowRevision, list[dict[str, Any]], list[dict[str, Any]]]:
    revision = await session.get(WorkflowRevision, revision_id)
    if revision is None:
        raise NotFoundError("workflow_revision_not_found", id=revision_id)
    definition = await session.get(WorkflowDefinition, revision.definition_id)
    if definition is None or (actor_id is not None and definition.user_id != actor_id):
        raise NotFoundError("workflow_revision_not_found", id=revision_id)
    node_rows = (
        (await session.execute(select(WorkflowNode).where(WorkflowNode.revision_id == revision_id))).scalars().all()
    )
    edge_rows = (
        (await session.execute(select(WorkflowEdge).where(WorkflowEdge.revision_id == revision_id))).scalars().all()
    )
    nodes = [
        {
            "node_key": row.node_key,
            "node_type": row.node_type,
            "node_type_version": row.node_type_version,
            "config_schema_version": row.config_schema_version,
            "config": _loads(row.config_json, {}),
            "ui_position": _loads(row.ui_position_json, None),
            "weight": row.weight,
            "retry_policy": _loads(row.retry_policy_json, None),
            "approval_policy": _loads(row.approval_policy_json, None),
            "input_schema": _loads(row.input_schema_json, {}),
            "output_schema": _loads(row.output_schema_json, {}),
            "executor_id": row.executor_id,
            "required_capabilities": _loads(row.required_capabilities_json, []),
            "estimated_cost": row.estimated_cost,
            "cache_policy": row.cache_policy,
        }
        for row in node_rows
    ]
    edges = [
        {
            "edge_key": row.edge_key,
            "source_node_key": row.source_node_key,
            "target_node_key": row.target_node_key,
            "condition": _loads(row.condition_json, None),
            "on_failure": row.on_failure,
            "priority": row.priority,
        }
        for row in edge_rows
    ]
    return revision, nodes, edges


async def validate_revision(session: AsyncSession, revision_id: str, *, actor_id: str) -> dict[str, Any]:
    revision, nodes, edges = await _revision_graph(session, revision_id, actor_id=actor_id)
    validate_graph(nodes, edges)
    return {
        "valid": True,
        "revision_id": revision.id,
        "graph_hash": revision.graph_hash,
        "execution_hash": revision.execution_hash,
        "content_mode": revision.content_mode,
        "generation_mode": revision.generation_mode,
        "input_schema": _loads(revision.input_schema_json, {}),
    }


async def publish_revision(session: AsyncSession, revision_id: str, *, actor_id: str) -> dict[str, Any]:
    revision, nodes, edges = await _revision_graph(session, revision_id, actor_id=actor_id)
    if revision.status != "draft":
        raise ConflictError("workflow_revision_immutable", id=revision_id, status=revision.status)
    validate_graph(nodes, edges)
    definition = await session.get(WorkflowDefinition, revision.definition_id)
    if definition is None:
        raise NotFoundError("workflow_not_found", id=revision.definition_id)
    revision.status = "published"
    definition.active_revision_id = revision.id
    definition.updated_at = utc_now()
    event = await _append_event(
        session,
        workspace_id=definition.workspace_id,
        project_id=definition.project_id,
        aggregate_type="workflow_revision",
        aggregate_id=revision.id,
        aggregate_version=2,
        event_type="workflow.revision.published",
        payload={"definition_id": definition.id, "revision_no": revision.revision_no},
        actor_id=actor_id,
    )
    await session.commit()
    return {"id": revision.id, "status": revision.status, "version": 2, "event_cursor": event.seq}


async def list_revisions(session: AsyncSession, definition_id: str, *, actor_id: str) -> dict[str, Any]:
    """Return immutable revision history for the definition, newest first."""

    definition = await session.get(WorkflowDefinition, definition_id)
    if definition is None or definition.user_id != actor_id:
        raise NotFoundError("workflow_not_found", id=definition_id)
    rows = (
        (
            await session.execute(
                select(WorkflowRevision)
                .where(WorkflowRevision.definition_id == definition_id)
                .order_by(WorkflowRevision.revision_no.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "revision_no": row.revision_no,
                "status": row.status,
                "graph_hash": row.graph_hash,
                "execution_hash": row.execution_hash,
                "content_mode": row.content_mode,
                "generation_mode": row.generation_mode,
                "is_active": row.id == definition.active_revision_id,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


async def revert_revision(
    session: AsyncSession,
    *,
    definition_id: str,
    revision_id: str,
    actor_id: str,
) -> dict[str, Any]:
    """Create and publish a new revision containing a historical graph."""

    definition = await session.get(WorkflowDefinition, definition_id)
    if definition is None or definition.user_id != actor_id:
        raise NotFoundError("workflow_not_found", id=definition_id)
    source = await session.get(WorkflowRevision, revision_id)
    if source is None or source.definition_id != definition_id:
        raise NotFoundError("workflow_revision_not_found", id=revision_id)
    _, nodes, edges = await _revision_graph(session, revision_id, actor_id=actor_id)
    result = await create_revision(
        session,
        definition_id=definition_id,
        nodes=nodes,
        edges=edges,
        template_lock=_loads(source.template_lock_json, None),
        actor_id=actor_id,
        content_mode=source.content_mode,
        generation_mode=source.generation_mode,
        input_schema=_loads(source.input_schema_json, {}),
    )
    published = await publish_revision(session, result["id"], actor_id=actor_id)
    return {"reverted_from": revision_id, "revision_id": result["id"], **published}


async def get_workflow(session: AsyncSession, definition_id: str, *, actor_id: str) -> dict[str, Any]:
    definition = await session.get(WorkflowDefinition, definition_id)
    if definition is None or definition.user_id != actor_id:
        raise NotFoundError("workflow_not_found", id=definition_id)
    result: dict[str, Any] = {
        "id": definition.id,
        "workspace_id": definition.workspace_id,
        "project_id": definition.project_id,
        "name": definition.name,
        "scope": definition.scope,
        "active_revision_id": definition.active_revision_id,
    }
    active_revision_no: int | None = None
    if definition.active_revision_id:
        revision, nodes, edges = await _revision_graph(session, definition.active_revision_id, actor_id=actor_id)
        active_revision_no = revision.revision_no
        result["active_revision"] = {
            "id": revision.id,
            "revision_no": revision.revision_no,
            "status": revision.status,
            "graph_hash": revision.graph_hash,
            "execution_hash": revision.execution_hash,
            "content_mode": revision.content_mode,
            "generation_mode": revision.generation_mode,
            "input_schema": _loads(revision.input_schema_json, {}),
            "template_lock": _loads(revision.template_lock_json, None),
            "nodes": nodes,
            "edges": edges,
        }

    draft_result = await session.execute(
        select(WorkflowRevision)
        .where(
            WorkflowRevision.definition_id == definition_id,
            WorkflowRevision.status == "draft",
        )
        .order_by(WorkflowRevision.revision_no.desc())
        .limit(1)
    )
    draft = draft_result.scalar_one_or_none()
    if draft is not None and (active_revision_no is None or draft.revision_no > active_revision_no):
        revision, nodes, edges = await _revision_graph(session, draft.id, actor_id=actor_id)
        result["draft_revision"] = {
            "id": revision.id,
            "revision_no": revision.revision_no,
            "status": revision.status,
            "graph_hash": revision.graph_hash,
            "execution_hash": revision.execution_hash,
            "content_mode": revision.content_mode,
            "generation_mode": revision.generation_mode,
            "input_schema": _loads(revision.input_schema_json, {}),
            "template_lock": _loads(revision.template_lock_json, None),
            "nodes": nodes,
            "edges": edges,
        }
    return result


async def plan_run(
    session: AsyncSession,
    *,
    revision_id: str,
    workspace_id: str,
    project_id: str,
    mode: str,
    input_snapshot: dict[str, Any],
    script_revision_id: str | None,
    actor_id: str,
    episode_id: str | None = None,
    budget_limit: float | None = None,
) -> dict[str, Any]:
    if mode not in {"auto", "manual", "hybrid"}:
        raise WorkflowValidationError("workflow_input_invalid", reason="mode")
    if budget_limit is not None and budget_limit < 0:
        raise WorkflowValidationError("workflow_input_invalid", reason="budget_limit")
    revision, nodes, edges = await _revision_graph(session, revision_id, actor_id=actor_id)
    if revision.status != "published":
        raise ConflictError("workflow_revision_not_published", id=revision_id)
    definition = await session.get(WorkflowDefinition, revision.definition_id)
    if definition is None or definition.workspace_id != workspace_id or definition.project_id != project_id:
        raise NotFoundError("workflow_revision_not_found", id=revision_id)
    project_generation_mode = _snapshot_generation_mode(input_snapshot)
    if project_generation_mode is not None and project_generation_mode != revision.generation_mode:
        raise WorkflowValidationError(
            "workflow_generation_mode_mismatch",
            project_generation_mode=project_generation_mode,
            workflow_generation_mode=revision.generation_mode,
        )
    fingerprint = input_fingerprint(
        {
            "schema_version": 1,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "workflow_execution_hash": revision.execution_hash,
            "script_revision_id": script_revision_id,
            "input": input_snapshot,
        }
    )
    existing = (
        await session.execute(
            select(WorkflowRun)
            .where(
                WorkflowRun.user_id == actor_id,
                WorkflowRun.workspace_id == workspace_id,
                WorkflowRun.project_id == project_id,
                WorkflowRun.input_fingerprint == fingerprint,
                WorkflowRun.status.in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(WorkflowRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"id": existing.id, "status": existing.status, "version": existing.version, "deduped": True}

    now = utc_now()
    trace_id = uuid.uuid4().hex
    run = WorkflowRun(
        id=uuid.uuid4().hex,
        user_id=actor_id,
        workflow_revision_id=revision.id,
        workspace_id=workspace_id,
        project_id=project_id,
        script_revision_id=script_revision_id,
        episode_id=episode_id,
        budget_limit=budget_limit,
        spent_amount=0,
        reserved_amount=0,
        status="planned",
        mode=mode,
        execution_hash=revision.execution_hash,
        input_fingerprint=fingerprint,
        graph_snapshot_ref=revision.id,
        input_snapshot_json=canonical_json(input_snapshot),
        progress=0,
        version=1,
        control_generation=0,
        trace_id=trace_id,
        created_by=actor_id,
        created_at=now,
    )
    session.add(run)
    await session.flush()
    targets = {str(edge["target_node_key"]) for edge in edges}
    for node in nodes:
        session.add(
            WorkflowNodeRun(
                id=uuid.uuid4().hex,
                workflow_run_id=run.id,
                node_key=str(node["node_key"]),
                attempt_no=1,
                status="blocked" if str(node["node_key"]) in targets else "ready",
                progress=0,
                progress_source="unknown",
                fencing_token=0,
                created_at=now,
                updated_at=now,
            )
        )
    event = await _append_event(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        aggregate_type="workflow_run",
        aggregate_id=run.id,
        aggregate_version=1,
        event_type="workflow.run.planned",
        payload={
            "revision_id": revision.id,
            "mode": mode,
            "episode_id": episode_id,
            "budget_limit": budget_limit,
            "input_fingerprint": fingerprint,
        },
        actor_id=actor_id,
        trace_id=trace_id,
    )
    await session.commit()
    return {
        "id": run.id,
        "status": run.status,
        "version": 1,
        "episode_id": episode_id,
        "budget_limit": budget_limit,
        "event_cursor": event.seq,
        "deduped": False,
    }


async def find_workflow_run_for_creation_plan(
    session: AsyncSession,
    *,
    creation_plan_id: str,
    project_id: str,
    actor_id: str,
) -> dict[str, Any] | None:
    """Find a run previously created for an immutable Creation Plan."""

    rows = (
        (
            await session.execute(
                select(WorkflowRun)
                .where(
                    WorkflowRun.user_id == actor_id,
                    WorkflowRun.project_id == project_id,
                )
                .order_by(WorkflowRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    for run in rows:
        try:
            snapshot = _loads(run.input_snapshot_json, {})
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(snapshot, dict) and str(snapshot.get("creation_plan_id", "")) == creation_plan_id:
            return {"id": run.id, "status": run.status, "version": run.version, "deduped": True}
    return None


async def request_workflow_run_execution(
    session: AsyncSession,
    *,
    run_id: str,
    actor_id: str,
) -> dict[str, Any]:
    """Durably hand a running run to the existing polling executor.

    The executor consumes running rows from process_workflow_runs. The event is
    an idempotent audit marker; the running row remains the durable work item,
    so a process restart can recover it without a second execution request.
    """

    run = await session.get(WorkflowRun, run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    if run.status != "running":
        return {
            "id": run.id,
            "status": run.status,
            "dispatch_status": "not_running",
            "executor": "workflow_executor_loop",
        }

    existing = (
        await session.execute(
            select(ProjectEventLog)
            .where(
                ProjectEventLog.aggregate_type == "workflow_run",
                ProjectEventLog.aggregate_id == run.id,
                ProjectEventLog.event_type == "workflow.run.dispatch_requested",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is None:
        await _append_event(
            session,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            aggregate_type="workflow_run",
            aggregate_id=run.id,
            aggregate_version=run.version,
            event_type="workflow.run.dispatch_requested",
            payload={"status": run.status, "executor": "workflow_executor_loop"},
            actor_id=actor_id,
            trace_id=run.trace_id,
        )
    await session.commit()
    return {
        "id": run.id,
        "status": run.status,
        "dispatch_status": "queued" if existing is None else "already_queued",
        "executor": "workflow_executor_loop",
    }


async def transition_workflow_run(
    session: AsyncSession,
    *,
    run_id: str,
    target: str,
    expected_version: int,
    actor_id: str,
) -> dict[str, Any]:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    if run.version != expected_version:
        raise ConflictError("workflow_version_conflict", expected=expected_version, actual=run.version)
    previous_status = run.status
    transition_run(previous_status, target)
    now = utc_now()
    run.status = target
    run.version += 1
    if target in {"paused", "cancelled"} or (target == "running" and previous_status in {"paused", "waiting_review"}):
        run.control_generation += 1
    if target == "running" and run.started_at is None:
        run.started_at = now
    if target in {"succeeded", "failed", "cancelled"}:
        run.finished_at = now
    event = await _append_event(
        session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        aggregate_type="workflow_run",
        aggregate_id=run.id,
        aggregate_version=run.version,
        event_type=f"workflow.run.{target}",
        payload={"status": target, "control_generation": run.control_generation},
        actor_id=actor_id,
        trace_id=run.trace_id,
    )
    await session.commit()
    return {
        "id": run.id,
        "status": run.status,
        "version": run.version,
        "control_generation": run.control_generation,
        "event_cursor": event.seq,
    }


async def get_run(session: AsyncSession, run_id: str, *, actor_id: str) -> dict[str, Any]:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    node_runs = (
        (
            await session.execute(
                select(WorkflowNodeRun)
                .where(WorkflowNodeRun.workflow_run_id == run_id)
                .order_by(WorkflowNodeRun.created_at, WorkflowNodeRun.node_key)
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": run.id,
        "workflow_revision_id": run.workflow_revision_id,
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "status": run.status,
        "mode": run.mode,
        "progress": run.progress,
        "version": run.version,
        "control_generation": run.control_generation,
        "input_fingerprint": run.input_fingerprint,
        "episode_id": run.episode_id,
        "budget_limit": run.budget_limit,
        "spent_amount": run.spent_amount,
        "reserved_amount": run.reserved_amount,
        "remaining_amount": None
        if run.budget_limit is None
        else max(0.0, run.budget_limit - run.spent_amount - run.reserved_amount),
        "nodes": [
            {
                "id": node.id,
                "node_key": node.node_key,
                "attempt_no": node.attempt_no,
                "status": node.status,
                "progress": node.progress,
                "progress_source": node.progress_source,
                "phase_code": node.phase_code,
                "error_code": node.error_code,
                "error_params": _loads(node.error_params_json, {}),
                "output_refs": _loads(node.output_refs_json, {}),
                "fencing_token": node.fencing_token,
            }
            for node in node_runs
        ],
    }


async def list_runs(session: AsyncSession, project_id: str, *, actor_id: str, limit: int = 50) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(WorkflowRun)
                .where(WorkflowRun.user_id == actor_id, WorkflowRun.project_id == project_id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "workflow_revision_id": row.workflow_revision_id,
                "status": row.status,
                "mode": row.mode,
                "progress": row.progress,
                "version": row.version,
                "control_generation": row.control_generation,
                "created_at": row.created_at.isoformat(),
                "episode_id": row.episode_id,
                "budget_limit": row.budget_limit,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ]
    }


async def list_events(
    session: AsyncSession,
    project_id: str,
    *,
    actor_id: str,
    after: int = 0,
    limit: int = 500,
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(ProjectEventLog)
                .where(
                    ProjectEventLog.actor_id == actor_id,
                    ProjectEventLog.project_id == project_id,
                    ProjectEventLog.seq > after,
                )
                .order_by(ProjectEventLog.seq)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "seq": row.seq,
                "event_id": row.event_id,
                "aggregate_type": row.aggregate_type,
                "aggregate_id": row.aggregate_id,
                "aggregate_version": row.aggregate_version,
                "event_type": row.event_type,
                "event_version": row.event_version,
                "payload": _loads(row.payload_json, {}),
                "trace_id": row.trace_id,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "cursor": rows[-1].seq if rows else after,
    }


# ---------------------------------------------------------------------------
# Canvas workflow management: list / export / import / node logs / migration
# ---------------------------------------------------------------------------

LEGACY_FLOW_NODE_TYPES = [
    "source_import",
    "script_generate",
    "script_review",
    "character_reference",
    "storyboard_generate",
    "storyboard_review",
    "shot_image_generate",
    "shot_video_generate",
    "voice_generate",
    "subtitle_generate",
    "compose",
    "quality_check",
    "export",
]


def legacy_linear_graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The pre-canvas linear chain, expressed as a DAG for migration.

    Mirrors the default revision the legacy FlowMonitor used to create, so old
    projects keep a recognizable one-click production flow after migration.
    """

    nodes = [
        {
            "node_key": node_type,
            "node_type": node_type,
            "node_type_version": "1",
            "config_schema_version": "1",
            "config": {},
            "ui_position": {"x": index * 240, "y": 0},
            "weight": 2.0 if "generate" in node_type else 1.0,
        }
        for index, node_type in enumerate(LEGACY_FLOW_NODE_TYPES)
    ]
    edges = [
        {
            "edge_key": f"{source}-{target}",
            "source_node_key": source,
            "target_node_key": target,
            "on_failure": "stop",
            "priority": 0,
        }
        for source, target in zip(LEGACY_FLOW_NODE_TYPES, LEGACY_FLOW_NODE_TYPES[1:])
    ]
    return nodes, edges


async def list_definitions(session: AsyncSession, project_id: str, *, actor_id: str) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(WorkflowDefinition)
                .where(WorkflowDefinition.user_id == actor_id, WorkflowDefinition.project_id == project_id)
                .order_by(WorkflowDefinition.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "scope": row.scope,
                "active_revision_id": row.active_revision_id,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]
    }


async def export_definition(session: AsyncSession, definition_id: str, *, actor_id: str) -> dict[str, Any]:
    """Serialize a workflow definition (with its active revision) as JSON."""

    definition = await session.get(WorkflowDefinition, definition_id)
    if definition is None or definition.user_id != actor_id:
        raise NotFoundError("workflow_not_found", id=definition_id)
    if not definition.active_revision_id:
        return {
            "schema_version": 2,
            "name": definition.name,
            "nodes": [],
            "edges": [],
            "template_lock": None,
            "content_mode": "drama",
            "generation_mode": "storyboard",
            "input_schema": {},
        }
    revision, nodes, edges = await _revision_graph(session, definition.active_revision_id, actor_id=actor_id)
    return {
        "schema_version": 2,
        "name": definition.name,
        "nodes": nodes,
        "edges": edges,
        "template_lock": _loads(revision.template_lock_json, None),
        "content_mode": revision.content_mode,
        "generation_mode": revision.generation_mode,
        "input_schema": _loads(revision.input_schema_json, {}),
    }


async def import_definition(
    session: AsyncSession,
    *,
    workspace_id: str,
    project_id: str,
    name: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    template_lock: dict[str, Any] | None,
    actor_id: str,
    content_mode: str = "drama",
    generation_mode: str = "storyboard",
    input_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a published definition from exported workflow JSON (import)."""

    validate_graph(nodes, edges)
    definition = await create_definition(
        session, workspace_id=workspace_id, project_id=project_id, name=name, actor_id=actor_id
    )
    revision = await create_revision(
        session,
        definition_id=definition["id"],
        nodes=nodes,
        edges=edges,
        template_lock=template_lock,
        actor_id=actor_id,
        content_mode=content_mode,
        generation_mode=generation_mode,
        input_schema=input_schema,
    )
    await publish_revision(session, revision["id"], actor_id=actor_id)
    return {"definition_id": definition["id"], "revision_id": revision["id"]}


async def migrate_project(
    session: AsyncSession, *, workspace_id: str, project_id: str, actor_id: str
) -> dict[str, Any]:
    """Idempotently create a canvas workflow for a legacy project.

    Projects that already have a definition (or an in-flight run without a
    definition, which is not possible today) keep their existing graph.
    """

    existing = (
        (
            await session.execute(
                select(WorkflowDefinition)
                .where(
                    WorkflowDefinition.user_id == actor_id,
                    WorkflowDefinition.project_id == project_id,
                    WorkflowDefinition.workspace_id == workspace_id,
                )
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return {"migrated": False, "definition_id": existing.id}
    definition = await create_definition(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        name=f"{project_id} production",
        actor_id=actor_id,
    )
    nodes, edges = legacy_linear_graph()
    revision = await create_revision(
        session,
        definition_id=definition["id"],
        nodes=nodes,
        edges=edges,
        template_lock={"template_schema_version": 1},
        actor_id=actor_id,
    )
    await publish_revision(session, revision["id"], actor_id=actor_id)
    return {"migrated": True, "definition_id": definition["id"], "revision_id": revision["id"]}


def _template_graph(node_types: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        {
            "node_key": node_type,
            "node_type": node_type,
            "node_type_version": "1",
            "config_schema_version": "1",
            "config": {},
            "ui_position": {"x": index * 260, "y": (index % 3) * 80},
            "weight": 2.0 if "generate" in node_type else 1.0,
        }
        for index, node_type in enumerate(node_types)
    ]
    edges = [
        {
            "edge_key": f"{source}-{target}",
            "source_node_key": source,
            "target_node_key": target,
            "on_failure": "stop",
            "priority": 0,
        }
        for source, target in zip(node_types, node_types[1:])
    ]
    return nodes, edges


def list_templates() -> dict[str, Any]:
    """Return the built-in templates shared by simple and canvas views."""

    definitions = (
        (
            "novel-to-manga",
            "flow_template_novel_to_manga",
            "flow_template_novel_to_manga_desc",
            LEGACY_FLOW_NODE_TYPES,
        ),
        (
            "storyboard-to-video",
            "flow_template_storyboard",
            "flow_template_storyboard_desc",
            [
                "script_generate",
                "script_review",
                "character_reference",
                "storyboard_generate",
                "quality_check",
                "shot_image_generate",
                "shot_video_generate",
                "compose",
                "export",
            ],
        ),
        (
            "reference-to-video",
            "flow_template_reference",
            "flow_template_reference_desc",
            ["source_import", "script_review", "reference_video_generate", "quality_check", "export"],
        ),
    )
    items = []
    for template_id, name_key, description_key, node_types in definitions:
        nodes, edges = _template_graph(list(node_types))
        items.append(
            {
                "id": template_id,
                "scope": "official",
                "name_key": name_key,
                "description_key": description_key,
                "template_lock": {"template_schema_version": 1, "template_id": template_id},
                "generation_mode": "reference_video" if template_id == "reference-to-video" else "storyboard",
                "nodes": nodes,
                "edges": edges,
            }
        )
    return {"items": items}


async def retry_run_from_node(
    session: AsyncSession,
    *,
    run_id: str,
    node_key: str,
    actor_id: str,
    start: bool = False,
) -> dict[str, Any]:
    """Fork a failed run at a node while retaining successful upstream outputs.

    The original run remains immutable for auditability.  A new planned run
    reuses the same revision and input snapshot, copies passed nodes, and
    schedules the selected node plus all downstream nodes again.
    """

    source_run = await session.get(WorkflowRun, run_id)
    if source_run is None or source_run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    if source_run.status not in {"failed", "paused"}:
        raise ConflictError("workflow_retry_invalid_status", status=source_run.status)

    revision, nodes, edges = await _revision_graph(session, source_run.workflow_revision_id, actor_id=actor_id)
    by_key = {str(node["node_key"]): node for node in nodes}
    if node_key not in by_key:
        raise NotFoundError("workflow_node_not_found", node_key=node_key)

    source_rows = (
        (
            await session.execute(
                select(WorkflowNodeRun)
                .where(WorkflowNodeRun.workflow_run_id == source_run.id)
                .order_by(WorkflowNodeRun.node_key, WorkflowNodeRun.attempt_no.desc())
            )
        )
        .scalars()
        .all()
    )
    latest: dict[str, WorkflowNodeRun] = {}
    for row in source_rows:
        latest.setdefault(row.node_key, row)
    target_row = latest.get(node_key)
    if target_row is None or target_row.status not in {"failed", "stale", "orphaned"}:
        raise ConflictError(
            "workflow_retry_node_invalid_status", node_key=node_key, status=target_row.status if target_row else None
        )

    outgoing, incoming = node_graph_edges(edges)
    descendants: set[str] = set()
    queue = deque(outgoing.get(node_key, set()))
    while queue:
        current = queue.popleft()
        if current in descendants:
            continue
        descendants.add(current)
        queue.extend(outgoing.get(current, set()))

    now = utc_now()
    retry_run = WorkflowRun(
        id=uuid.uuid4().hex,
        user_id=actor_id,
        workflow_revision_id=revision.id,
        workspace_id=source_run.workspace_id,
        project_id=source_run.project_id,
        script_revision_id=source_run.script_revision_id,
        status="planned",
        mode=source_run.mode,
        execution_hash=source_run.execution_hash,
        input_fingerprint=source_run.input_fingerprint,
        graph_snapshot_ref=source_run.graph_snapshot_ref,
        input_snapshot_json=source_run.input_snapshot_json,
        progress=0,
        version=1,
        control_generation=0,
        trace_id=uuid.uuid4().hex,
        created_by=actor_id,
        created_at=now,
    )
    session.add(retry_run)
    await session.flush()

    for node in nodes:
        key = str(node["node_key"])
        previous = latest.get(key)
        if key == node_key:
            status = "ready"
        elif key in descendants:
            status = "blocked"
        elif previous is not None and previous.status in PASSED_NODE_STATUSES:
            status = previous.status
        else:
            status = "ready" if not incoming.get(key) else "blocked"
        session.add(
            WorkflowNodeRun(
                id=uuid.uuid4().hex,
                workflow_run_id=retry_run.id,
                node_key=key,
                attempt_no=(previous.attempt_no + 1) if previous is not None else 1,
                status=status,
                progress=previous.progress if previous is not None and status in PASSED_NODE_STATUSES else 0,
                progress_source=previous.progress_source
                if previous is not None and status in PASSED_NODE_STATUSES
                else "checkpoint",
                phase_code=previous.phase_code if previous is not None and status in PASSED_NODE_STATUSES else None,
                output_refs_json=previous.output_refs_json
                if previous is not None and status in PASSED_NODE_STATUSES
                else None,
                fencing_token=0,
                created_at=now,
                updated_at=now,
            )
        )

    event = await _append_event(
        session,
        workspace_id=retry_run.workspace_id,
        project_id=retry_run.project_id,
        aggregate_type="workflow_run",
        aggregate_id=retry_run.id,
        aggregate_version=1,
        event_type="workflow.run.retry_planned",
        payload={"source_run_id": source_run.id, "retry_from": node_key},
        actor_id=actor_id,
        trace_id=retry_run.trace_id,
    )
    await session.commit()
    result = {
        "id": retry_run.id,
        "status": retry_run.status,
        "version": 1,
        "event_cursor": event.seq,
        "source_run_id": source_run.id,
        "retry_from": node_key,
    }
    if start:
        result.update(
            await transition_workflow_run(
                session,
                run_id=retry_run.id,
                target="running",
                expected_version=1,
                actor_id=actor_id,
            )
        )
    return result


async def list_node_logs(
    session: AsyncSession,
    run_id: str,
    node_key: str,
    *,
    actor_id: str,
    limit: int = 500,
) -> dict[str, Any]:
    """Node-scoped log lines emitted by the execution engine."""

    run = await session.get(WorkflowRun, run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    rows = (
        (
            await session.execute(
                select(ProjectEventLog)
                .where(
                    ProjectEventLog.actor_id == actor_id,
                    ProjectEventLog.project_id == run.project_id,
                    ProjectEventLog.aggregate_id == run.id,
                    ProjectEventLog.event_type == "workflow.node_log",
                )
                .order_by(ProjectEventLog.seq.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items = []
    for row in reversed(rows):
        payload = _loads(row.payload_json, {})
        if payload.get("node_key") != node_key:
            continue
        items.append(
            {
                "seq": row.seq,
                "level": payload.get("level", "info"),
                "line": payload.get("line", ""),
                "created_at": row.created_at.isoformat(),
            }
        )
    return {"items": items}


# ---------------------------------------------------------------------------
# Template marketplace and agent patch contracts
# ---------------------------------------------------------------------------

TEMPLATE_TYPES = frozenset({"manga", "short_drama"})


def _template_payload(template: WorkflowTemplate, stats: WorkflowUsageStats | None = None) -> dict[str, Any]:
    return {
        "id": template.id,
        "scope": "marketplace",
        "name_key": template.name,
        "description_key": template.description,
        "name": template.name,
        "description": template.description,
        "cover_ref": template.cover_ref,
        "template_type": template.template_type,
        "status": template.status,
        "draft_revision_id": template.draft_revision_id,
        "published_revision_id": template.published_revision_id,
        "contract": _loads(template.contract_json, {}),
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
        "published_at": template.published_at.isoformat() if template.published_at else None,
        "stats": {
            "views": stats.views if stats else 0,
            "derivations": stats.derivations if stats else 0,
            "run_count": stats.run_count if stats else 0,
            "successful_run_count": stats.successful_run_count if stats else 0,
            "success_rate": (stats.successful_run_count / stats.run_count) if stats and stats.run_count else 0.0,
            "average_cost": (stats.total_cost / stats.run_count) if stats and stats.run_count else 0.0,
            "average_duration_seconds": (stats.total_duration_seconds / stats.run_count)
            if stats and stats.run_count
            else 0.0,
            "rating": (stats.rating_total / stats.rating_count) if stats and stats.rating_count else None,
        },
    }


def _validate_template_contract(
    contract: dict[str, Any], *, nodes: list[dict[str, Any]] | None = None, edges: list[dict[str, Any]] | None = None
) -> None:
    """Validate marketplace metadata, node schemas, references, and graph safety."""
    payload = dict(contract)
    if nodes is not None:
        payload["nodes"] = nodes
    if edges is not None:
        payload["edges"] = edges
    try:
        validate_workflow_template_contract(payload)
    except WorkflowContractValidationError as exc:
        raise WorkflowValidationError("workflow_template_invalid", reason="contract", issues=list(exc.issues)) from exc
    aspect_ratios = contract.get("aspect_ratios")
    if aspect_ratios is not None and (
        not isinstance(aspect_ratios, list)
        or not all(isinstance(item, str) and item in {"16:9", "9:16", "1:1"} for item in aspect_ratios)
    ):
        raise WorkflowValidationError("workflow_template_invalid", reason="aspect_ratios")
    for field in ("copyright_declaration", "author", "license", "example_project", "cover_ref"):
        value = contract.get(field)
        if value is not None and not isinstance(value, str):
            raise WorkflowValidationError("workflow_template_invalid", reason=field)


async def create_template_draft(
    session: AsyncSession,
    *,
    name: str,
    description: str,
    template_type: str,
    contract: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    actor_id: str,
    content_mode: str = "drama",
    generation_mode: str = "storyboard",
    cover_ref: str | None = None,
) -> dict[str, Any]:
    if template_type not in TEMPLATE_TYPES:
        raise WorkflowValidationError("workflow_template_invalid", reason="template_type")
    _validate_template_contract(contract, nodes=nodes, edges=edges)
    validate_graph(nodes, edges)
    now = utc_now()
    template_id = uuid.uuid4().hex
    template = WorkflowTemplate(
        id=template_id,
        user_id=actor_id,
        name=name,
        description=description,
        cover_ref=cover_ref,
        template_type=template_type,
        status="draft",
        contract_json=canonical_json(contract),
        created_at=now,
        updated_at=now,
    )
    session.add(template)
    definition = WorkflowDefinition(
        id=uuid.uuid4().hex,
        user_id=actor_id,
        workspace_id="marketplace",
        project_id=f"template:{template_id}",
        name=name,
        scope="template",
        created_at=now,
        updated_at=now,
    )
    session.add(definition)
    await session.flush()
    revision = await create_revision(
        session,
        definition_id=definition.id,
        nodes=nodes,
        edges=edges,
        template_lock={"template_id": template_id, "template_schema_version": 1},
        actor_id=actor_id,
        content_mode=content_mode,
        generation_mode=generation_mode,
        input_schema=contract.get("input_schema"),
    )
    template.draft_revision_id = revision["id"]
    stats = WorkflowUsageStats(template_id=template_id)
    session.add(stats)
    await session.commit()
    return _template_payload(template, stats)


async def list_creator_templates(session: AsyncSession, *, actor_id: str) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(WorkflowTemplate)
                .where(WorkflowTemplate.user_id == actor_id)
                .order_by(WorkflowTemplate.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    items: list[dict[str, Any]] = []
    for template in rows:
        payload = await get_template(session, template.id, actor_id=actor_id, public=False)
        reviews = (
            (
                await session.execute(
                    select(WorkflowMarketplaceReview)
                    .where(WorkflowMarketplaceReview.template_id == template.id)
                    .order_by(WorkflowMarketplaceReview.created_at.desc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        history = [
            {
                "id": review.id,
                "revision_id": review.revision_id,
                "status": review.status,
                "decision": review.decision,
                "comment": review.comment,
                "reviewer_id": review.reviewer_id,
                "created_at": review.created_at.isoformat(),
            }
            for review in reviews
        ]
        payload["review_history"] = history
        payload["reviews"] = history
        items.append(payload)
    return {"items": items}


async def update_template_draft(
    session: AsyncSession,
    template_id: str,
    *,
    name: str,
    description: str,
    template_type: str,
    contract: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    actor_id: str,
    content_mode: str = "drama",
    generation_mode: str = "storyboard",
    cover_ref: str | None = None,
) -> dict[str, Any]:
    template = await session.get(WorkflowTemplate, template_id)
    if template is None or template.user_id != actor_id:
        raise NotFoundError("workflow_template_not_found", id=template_id)
    if template.status not in {"draft", "rejected"}:
        raise WorkflowValidationError("workflow_template_not_editable", status=template.status)
    if template_type not in TEMPLATE_TYPES:
        raise WorkflowValidationError("workflow_template_invalid", reason="template_type")
    _validate_template_contract(contract, nodes=nodes, edges=edges)
    validate_graph(nodes, edges)
    if not template.draft_revision_id:
        raise WorkflowValidationError("workflow_template_invalid", reason="missing_revision")
    current_revision = await session.get(WorkflowRevision, template.draft_revision_id)
    if current_revision is None:
        raise NotFoundError("workflow_revision_not_found", id=template.draft_revision_id)
    revision = await create_revision(
        session,
        definition_id=current_revision.definition_id,
        nodes=nodes,
        edges=edges,
        template_lock={"template_id": template.id, "template_schema_version": 1},
        actor_id=actor_id,
        content_mode=content_mode,
        generation_mode=generation_mode,
        input_schema=contract.get("input_schema"),
    )
    template.name = name
    template.description = description
    template.cover_ref = cover_ref
    template.template_type = template_type
    template.contract_json = canonical_json(contract)
    template.draft_revision_id = revision["id"]
    template.status = "draft"
    template.submitted_at = None
    template.updated_at = utc_now()
    await session.commit()
    return _template_payload(template, await session.get(WorkflowUsageStats, template.id))


async def get_template(
    session: AsyncSession, template_id: str, *, actor_id: str, public: bool = False
) -> dict[str, Any]:
    template = await session.get(WorkflowTemplate, template_id)
    if template is None or (public and template.status != "published" and template.user_id != actor_id):
        raise NotFoundError("workflow_template_not_found", id=template_id)
    if not public and template.user_id != actor_id:
        raise NotFoundError("workflow_template_not_found", id=template_id)
    stats = await session.get(WorkflowUsageStats, template_id)
    payload = _template_payload(template, stats)
    revision_id = template.published_revision_id or template.draft_revision_id
    if revision_id:
        revision, nodes, edges = await _revision_graph(session, revision_id, actor_id=None)
        payload["revision"] = {
            "id": revision.id,
            "revision_no": revision.revision_no,
            "status": revision.status,
            "content_mode": revision.content_mode,
            "generation_mode": revision.generation_mode,
            "input_schema": _loads(revision.input_schema_json, {}),
            "nodes": nodes,
            "edges": edges,
        }
    return payload


async def submit_template(session: AsyncSession, template_id: str, *, actor_id: str) -> dict[str, Any]:
    template = await session.get(WorkflowTemplate, template_id)
    if template is None or template.user_id != actor_id:
        raise NotFoundError("workflow_template_not_found", id=template_id)
    template_transition(template.status, "submitted")
    if not template.draft_revision_id:
        raise WorkflowValidationError("workflow_template_invalid", reason="missing_revision")
    revision, nodes, edges = await _revision_graph(session, template.draft_revision_id, actor_id=actor_id)
    _validate_template_contract(_loads(template.contract_json, {}), nodes=nodes, edges=edges)
    validate_graph(nodes, edges)
    template.status = "submitted"
    template.submitted_at = utc_now()
    template.updated_at = utc_now()
    await session.commit()
    return {"id": template.id, "status": template.status, "revision_id": revision.id}


async def withdraw_template(session: AsyncSession, template_id: str, *, actor_id: str) -> dict[str, Any]:
    template = await session.get(WorkflowTemplate, template_id)
    if template is None or template.user_id != actor_id:
        raise NotFoundError("workflow_template_not_found", id=template_id)
    template_transition(template.status, "draft")
    template.status = "draft"
    template.updated_at = utc_now()
    await session.commit()
    return {"id": template.id, "status": template.status}


async def review_template(
    session: AsyncSession,
    template_id: str,
    *,
    reviewer_id: str,
    decision: str,
    comment: str,
) -> dict[str, Any]:
    template = await session.get(WorkflowTemplate, template_id)
    if template is None:
        raise NotFoundError("workflow_template_not_found", id=template_id)
    target = {"approve": "published", "reject": "rejected", "changes_requested": "draft"}.get(decision)
    if decision == "start":
        template_transition(template.status, "under_review")
        if not template.draft_revision_id:
            raise WorkflowValidationError("workflow_template_invalid", reason="missing_revision")
        session.add(
            WorkflowMarketplaceReview(
                id=uuid.uuid4().hex,
                template_id=template.id,
                revision_id=template.draft_revision_id,
                status="under_review",
                decision="start",
                comment=comment,
                reviewer_id=reviewer_id,
                created_at=utc_now(),
            )
        )
        template.status = "under_review"
        template.updated_at = utc_now()
        await session.commit()
        return {"id": template.id, "status": template.status, "decision": decision, "comment": comment}
    if target is None:
        raise WorkflowValidationError("workflow_template_invalid", reason="decision")
    if template.status == "submitted":
        template.status = "under_review"
    elif template.status != "under_review":
        raise WorkflowValidationError(
            "workflow_template_invalid_transition", status=template.status, target="under_review"
        )
    template.status = "under_review"
    revision_id = template.draft_revision_id
    if not revision_id:
        raise WorkflowValidationError("workflow_template_invalid", reason="missing_revision")
    review = WorkflowMarketplaceReview(
        id=uuid.uuid4().hex,
        template_id=template.id,
        revision_id=revision_id,
        status="under_review",
        decision=decision,
        comment=comment,
        reviewer_id=reviewer_id,
        created_at=utc_now(),
    )
    session.add(review)
    if target == "published":
        revision = await session.get(WorkflowRevision, revision_id)
        definition = await session.get(WorkflowDefinition, revision.definition_id) if revision else None
        if revision is None or definition is None:
            raise NotFoundError("workflow_revision_not_found", id=revision_id)
        _source_revision, nodes, edges = await _revision_graph(session, revision_id, actor_id=None)
        _validate_template_contract(_loads(template.contract_json, {}), nodes=nodes, edges=edges)
        validate_graph(nodes, edges)
        revision.status = "published"
        definition.active_revision_id = revision.id
        template.published_revision_id = revision.id
        template.status = "published"
        template.published_at = utc_now()
    elif target == "rejected":
        template.status = "rejected"
    else:
        template.status = "draft"
    template.updated_at = utc_now()
    await session.commit()
    return {"id": template.id, "status": template.status, "decision": decision, "comment": comment}


async def set_template_suspended(
    session: AsyncSession, template_id: str, *, reviewer_id: str, suspended: bool
) -> dict[str, Any]:
    template = await session.get(WorkflowTemplate, template_id)
    if template is None:
        raise NotFoundError("workflow_template_not_found", id=template_id)
    target = "suspended" if suspended else "published"
    template_transition(template.status, target)
    template.status = target
    template.updated_at = utc_now()
    await session.commit()
    return {"id": template.id, "status": template.status, "actor_id": reviewer_id}


async def list_marketplace(
    session: AsyncSession, *, template_type: str | None = None, limit: int = 50
) -> dict[str, Any]:
    stmt = select(WorkflowTemplate).where(WorkflowTemplate.status == "published")
    if template_type:
        if template_type not in TEMPLATE_TYPES:
            raise WorkflowValidationError("workflow_template_invalid", reason="template_type")
        stmt = stmt.where(WorkflowTemplate.template_type == template_type)
    rows = (await session.execute(stmt.order_by(WorkflowTemplate.published_at.desc()).limit(limit))).scalars().all()
    items = []
    for row in rows:
        detail = await get_template(session, row.id, actor_id="", public=True)
        revision = detail.pop("revision", None)
        detail["template_lock"] = {
            "template_id": row.id,
            "source_revision_id": row.published_revision_id,
            "template_schema_version": 1,
        }
        detail["nodes"] = revision["nodes"] if revision else []
        detail["edges"] = revision["edges"] if revision else []
        items.append(detail)
    return {"items": items}


async def record_template_view(session: AsyncSession, template_id: str) -> dict[str, Any]:
    template = await session.get(WorkflowTemplate, template_id)
    if template is None or template.status != "published":
        raise NotFoundError("workflow_template_not_found", id=template_id)
    stats = await session.get(WorkflowUsageStats, template_id)
    if stats is None:
        stats = WorkflowUsageStats(template_id=template_id)
        session.add(stats)
    stats.views += 1
    await session.commit()
    return {"template_id": template_id, "views": stats.views}


async def rate_template(session: AsyncSession, template_id: str, *, rating: float, actor_id: str) -> dict[str, Any]:
    if rating < 1 or rating > 5:
        raise WorkflowValidationError("workflow_template_invalid", reason="rating")
    template = await session.get(WorkflowTemplate, template_id)
    if template is None or template.status != "published":
        raise NotFoundError("workflow_template_not_found", id=template_id)
    if template.user_id == actor_id:
        raise WorkflowValidationError("workflow_template_invalid", reason="author_rating")
    stats = await session.get(WorkflowUsageStats, template_id)
    if stats is None:
        stats = WorkflowUsageStats(template_id=template_id)
        session.add(stats)
    stats.rating_total += rating
    stats.rating_count += 1
    await session.commit()
    return {
        "template_id": template_id,
        "rating": stats.rating_total / stats.rating_count,
        "rating_count": stats.rating_count,
    }


async def get_template_upgrade(session: AsyncSession, definition_id: str, *, actor_id: str) -> dict[str, Any]:
    definition = await session.get(WorkflowDefinition, definition_id)
    if definition is None or definition.user_id != actor_id:
        raise NotFoundError("workflow_not_found", id=definition_id)
    if not definition.active_revision_id:
        return {"available": False, "reason": "no_active_revision"}

    current, current_nodes, current_edges = await _revision_graph(
        session, definition.active_revision_id, actor_id=actor_id
    )
    template_lock = _loads(current.template_lock_json, {})
    template_id = template_lock.get("template_id") if isinstance(template_lock, dict) else None
    source_revision_id = template_lock.get("source_revision_id") if isinstance(template_lock, dict) else None
    if not template_id or not source_revision_id:
        return {"available": False, "reason": "not_template_derived"}

    template = await session.get(WorkflowTemplate, str(template_id))
    latest_id = template.published_revision_id if template is not None else None
    latest = await session.get(WorkflowRevision, latest_id) if latest_id else None
    if template is None or latest is None or template.status != "published":
        return {
            "available": False,
            "reason": "template_unavailable",
            "template_id": str(template_id),
            "current_revision_id": current.id,
            "current_source_revision_id": str(source_revision_id),
        }
    if latest.id == source_revision_id:
        return {
            "available": False,
            "reason": "up_to_date",
            "template_id": template.id,
            "current_revision_id": current.id,
            "current_source_revision_id": source_revision_id,
            "latest_revision_id": latest.id,
            "latest_revision_no": latest.revision_no,
        }

    _, latest_nodes, latest_edges = await _revision_graph(session, latest.id, actor_id=None)
    current_by_key = {str(node["node_key"]): node for node in current_nodes}
    latest_by_key = {str(node["node_key"]): node for node in latest_nodes}
    current_edges_by_key = {str(edge["edge_key"]): edge for edge in current_edges}
    latest_edges_by_key = {str(edge["edge_key"]): edge for edge in latest_edges}
    changed_nodes = sorted(
        key
        for key in current_by_key.keys() & latest_by_key.keys()
        if canonical_json(current_by_key[key]) != canonical_json(latest_by_key[key])
    )
    added_nodes = sorted(latest_by_key.keys() - current_by_key.keys())
    removed_nodes = sorted(current_by_key.keys() - latest_by_key.keys())
    added_edges = sorted(latest_edges_by_key.keys() - current_edges_by_key.keys())
    removed_edges = sorted(current_edges_by_key.keys() - latest_edges_by_key.keys())
    compatibility_reasons: list[str] = []
    if current.content_mode != latest.content_mode:
        compatibility_reasons.append("content_mode_changed")
    if current.generation_mode != latest.generation_mode:
        compatibility_reasons.append("generation_mode_changed")
    try:
        validate_graph(latest_nodes, latest_edges)
        validate_node_contracts(latest_nodes)
    except WorkflowValidationError:
        compatibility_reasons.append("latest_revision_invalid")
    current_cost = sum(float(node.get("estimated_cost", 0) or 0) for node in current_nodes)
    latest_cost = sum(float(node.get("estimated_cost", 0) or 0) for node in latest_nodes)
    return {
        "available": True,
        "template_id": template.id,
        "current_revision_id": current.id,
        "current_source_revision_id": source_revision_id,
        "latest_revision_id": latest.id,
        "latest_revision_no": latest.revision_no,
        "compatible": not compatibility_reasons,
        "compatibility_reasons": compatibility_reasons,
        "estimated_cost_delta": latest_cost - current_cost,
        "changes": {
            "added_nodes": added_nodes,
            "removed_nodes": removed_nodes,
            "changed_nodes": changed_nodes,
            "added_edges": added_edges,
            "removed_edges": removed_edges,
        },
    }


async def upgrade_workflow_template(
    session: AsyncSession, definition_id: str, *, actor_id: str, confirmed: bool
) -> dict[str, Any]:
    if not confirmed:
        raise WorkflowValidationError("workflow_template_upgrade_confirmation_required")
    upgrade = await get_template_upgrade(session, definition_id, actor_id=actor_id)
    if not upgrade.get("available"):
        raise ConflictError("workflow_template_upgrade_unavailable", reason=upgrade.get("reason"))
    if not upgrade.get("compatible"):
        raise ConflictError(
            "workflow_template_upgrade_incompatible",
            reasons=upgrade.get("compatibility_reasons", []),
        )
    current, _, _ = await _revision_graph(session, str(upgrade["current_revision_id"]), actor_id=actor_id)
    latest, nodes, edges = await _revision_graph(session, str(upgrade["latest_revision_id"]), actor_id=None)
    template_lock = _loads(current.template_lock_json, {})
    if not isinstance(template_lock, dict):
        template_lock = {}
    template_lock.update(
        {
            "source_revision_id": latest.id,
            "upgraded_from_revision_id": current.id,
            "upgraded_at": utc_now().isoformat(),
        }
    )
    revision = await create_revision(
        session,
        definition_id=current.definition_id,
        nodes=nodes,
        edges=edges,
        template_lock=template_lock,
        actor_id=actor_id,
        content_mode=latest.content_mode,
        generation_mode=latest.generation_mode,
        input_schema=_loads(latest.input_schema_json, {}),
    )
    published = await publish_revision(session, revision["id"], actor_id=actor_id)
    return {"upgrade": upgrade, "revision": published}


async def derive_template(
    session: AsyncSession,
    template_id: str,
    *,
    workspace_id: str,
    project_id: str,
    name: str,
    actor_id: str,
) -> dict[str, Any]:
    template = await session.get(WorkflowTemplate, template_id)
    if template is None or template.status != "published" or not template.published_revision_id:
        raise ConflictError("workflow_template_not_published", id=template_id)
    source, nodes, edges = await _revision_graph(session, template.published_revision_id, actor_id=None)
    definition = await create_definition(
        session, workspace_id=workspace_id, project_id=project_id, name=name, actor_id=actor_id
    )
    revision = await create_revision(
        session,
        definition_id=definition["id"],
        nodes=nodes,
        edges=edges,
        template_lock={
            "template_id": template.id,
            "source_revision_id": source.id,
            "derived_at": utc_now().isoformat(),
        },
        actor_id=actor_id,
        content_mode=source.content_mode,
        generation_mode=source.generation_mode,
        input_schema=_loads(source.input_schema_json, {}),
    )
    await publish_revision(session, revision["id"], actor_id=actor_id)
    stats = await session.get(WorkflowUsageStats, template.id)
    if stats:
        stats.derivations += 1
    await session.commit()
    return {"definition_id": definition["id"], "revision_id": revision["id"], "template_id": template.id}


async def _completed_patch_nodes(session: AsyncSession, run_id: str) -> set[str]:
    rows = (
        (await session.execute(select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run_id)))
        .scalars()
        .all()
    )
    return {row.node_key for row in rows if row.status in PASSED_NODE_STATUSES}


async def validate_patch_for_run(
    session: AsyncSession, run_id: str, patch: WorkflowPatch, *, actor_id: str
) -> dict[str, Any]:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    revision, nodes, edges = await _revision_graph(session, run.workflow_revision_id, actor_id=actor_id)
    if patch.base_revision_id != revision.id:
        raise ConflictError("workflow_patch_stale_revision", expected=revision.id, actual=patch.base_revision_id)
    remaining = None if run.budget_limit is None else run.budget_limit - run.spent_amount - run.reserved_amount
    completed_nodes = await _completed_patch_nodes(session, run_id)
    preview = validate_patch(
        nodes,
        edges,
        patch,
        remaining_budget=remaining,
        allow_destructive=True,
        completed_nodes=completed_nodes,
    )
    if not auto_optimization_enabled():
        preview["requires_confirmation"] = True
    return preview


async def apply_patch_for_run(
    session: AsyncSession,
    run_id: str,
    patch: WorkflowPatch,
    *,
    actor_id: str,
    confirmed: bool,
    start: bool = False,
) -> dict[str, Any]:
    """Authorize a patch, persist a new draft revision, and optionally plan it."""
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    revision, nodes, edges = await _revision_graph(session, run.workflow_revision_id, actor_id=actor_id)
    if patch.base_revision_id != revision.id:
        raise ConflictError("workflow_patch_stale_revision", expected=revision.id, actual=patch.base_revision_id)
    remaining = None if run.budget_limit is None else run.budget_limit - run.spent_amount - run.reserved_amount
    completed_nodes = await _completed_patch_nodes(session, run_id)
    preview = validate_patch(
        nodes, edges, patch, remaining_budget=remaining, completed_nodes=completed_nodes, allow_destructive=confirmed
    )
    if preview["requires_confirmation"] and not confirmed:
        raise WorkflowValidationError("workflow_patch_confirmation_required", operation="patch")
    next_nodes, next_edges = apply_patch_to_graph(nodes, edges, patch)
    result = await create_revision(
        session,
        definition_id=revision.definition_id,
        nodes=next_nodes,
        edges=next_edges,
        template_lock={
            **(_loads(revision.template_lock_json, {}) or {}),
            "parent_revision_id": revision.id,
            "patch_reason": patch.reason,
            "patch_scope": patch.scope,
        },
        actor_id=actor_id,
        content_mode=revision.content_mode,
        generation_mode=revision.generation_mode,
        input_schema=_loads(revision.input_schema_json, {}),
    )
    response: dict[str, Any] = {
        "revision_id": result["id"],
        "status": result["status"],
        "parent_revision_id": revision.id,
        "affected_nodes": preview["affected_nodes"],
        "estimated_cost_delta": preview["estimated_cost_delta"],
    }
    if start:
        published = await publish_revision(session, result["id"], actor_id=actor_id)
        planned = await plan_run(
            session,
            revision_id=result["id"],
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            script_revision_id=run.script_revision_id,
            mode=run.mode,
            input_snapshot=_loads(run.input_snapshot_json, {}),
            actor_id=actor_id,
            episode_id=run.episode_id,
            budget_limit=run.budget_limit,
        )
        response.update({"published": published, "run": planned})
    return response


def _static_template_validation(payload: dict[str, Any]) -> dict[str, Any]:
    revision = payload.get("active_revision") or payload.get("revision") or payload
    graph = revision
    raw_nodes = graph.get("nodes", [])
    raw_edges = graph.get("edges", [])
    nodes = [node for node in raw_nodes if isinstance(node, dict)] if isinstance(raw_nodes, list) else []
    edges = [edge for edge in raw_edges if isinstance(edge, dict)] if isinstance(raw_edges, list) else []
    node_keys = {str(node.get("node_key") or node.get("key") or node.get("id")) for node in nodes}
    missing_endpoints = [
        edge
        for edge in edges
        if str(edge.get("source_node_key") or edge.get("source") or edge.get("source_id")) not in node_keys
        or str(edge.get("target_node_key") or edge.get("target") or edge.get("target_id")) not in node_keys
    ]
    return {
        "valid": bool(nodes) and not missing_endpoints,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "missing_endpoints": missing_endpoints,
    }


async def list_pending_template_reviews(
    session: AsyncSession,
    *,
    template_type: str | None = None,
    risk_tag: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    stmt = select(WorkflowTemplate).where(WorkflowTemplate.status.in_(("submitted", "under_review")))
    if template_type:
        stmt = stmt.where(WorkflowTemplate.template_type == template_type)
    rows = (await session.execute(stmt.order_by(WorkflowTemplate.submitted_at.asc()).limit(limit))).scalars().all()
    items: list[dict[str, Any]] = []
    for template in rows:
        contract = _loads(template.contract_json, {})
        tags = contract.get("risk_tags", []) if isinstance(contract, dict) else []
        if risk_tag and risk_tag not in tags:
            continue
        reviews = (
            (
                await session.execute(
                    select(WorkflowMarketplaceReview)
                    .where(WorkflowMarketplaceReview.template_id == template.id)
                    .order_by(WorkflowMarketplaceReview.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        detail = await get_template(session, template.id, actor_id=template.user_id, public=False)
        items.append(
            {
                **detail,
                "risk_tags": tags,
                "static_validation": _static_template_validation(detail),
                "reviews": [
                    {
                        "id": review.id,
                        "decision": review.decision,
                        "comment": review.comment,
                        "reviewer_id": review.reviewer_id,
                        "created_at": review.created_at.isoformat(),
                    }
                    for review in reviews
                ],
            }
        )
    return {"items": items}


async def reserve_run_budget(session: AsyncSession, run_id: str, *, amount: float, actor_id: str) -> dict[str, Any]:
    if not math.isfinite(amount) or amount <= 0:
        raise WorkflowValidationError("workflow_input_invalid", reason="budget_reservation")
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    remaining = None if run.budget_limit is None else run.budget_limit - run.spent_amount - run.reserved_amount
    if remaining is not None and amount > remaining:
        raise WorkflowValidationError("workflow_budget_exceeded", requested=amount, remaining=remaining)
    reservation = BudgetReservation(
        id=uuid.uuid4().hex,
        workspace_id=run.workspace_id,
        workflow_run_id=run.id,
        currency="USD",
        estimated_amount=amount,
        reserved_amount=amount,
        settled_amount=0,
        status="reserved",
    )
    session.add(reservation)
    run.reserved_amount += amount
    await session.commit()
    return {
        "reservation_id": reservation.id,
        "run_id": run.id,
        "reserved_amount": run.reserved_amount,
        "remaining_amount": None
        if run.budget_limit is None
        else run.budget_limit - run.spent_amount - run.reserved_amount,
    }


async def settle_run_budget(
    session: AsyncSession, reservation_id: str, *, amount: float, actor_id: str
) -> dict[str, Any]:
    if not math.isfinite(amount) or amount < 0:
        raise WorkflowValidationError("workflow_input_invalid", reason="settled_amount")
    reservation = await session.get(BudgetReservation, reservation_id)
    if reservation is None:
        raise NotFoundError("workflow_budget_reservation_not_found", id=reservation_id)
    run = await session.get(WorkflowRun, reservation.workflow_run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=reservation.workflow_run_id)
    if reservation.status in {"released", "settled"}:
        if amount == 0:
            return {
                "reservation_id": reservation.id,
                "spent_amount": run.spent_amount,
                "reserved_amount": run.reserved_amount,
                "remaining_amount": None
                if run.budget_limit is None
                else max(0.0, run.budget_limit - run.spent_amount - run.reserved_amount),
            }
        raise WorkflowValidationError("workflow_budget_reservation_closed", id=reservation.id)
    if amount > reservation.reserved_amount:
        raise WorkflowValidationError("workflow_input_invalid", reason="settled_amount")
    if run.budget_limit is not None and run.spent_amount + amount > run.budget_limit + 1e-9:
        raise WorkflowValidationError(
            "workflow_budget_exceeded", spent=run.spent_amount + amount, limit=run.budget_limit
        )
    reservation.reserved_amount -= amount
    reservation.settled_amount += amount
    if reservation.reserved_amount <= 1e-9:
        reservation.reserved_amount = 0
        reservation.status = "settled"
    else:
        reservation.status = "reserved"
    run.reserved_amount = max(0.0, run.reserved_amount - amount)
    run.spent_amount += amount
    await session.commit()
    return {
        "reservation_id": reservation.id,
        "spent_amount": run.spent_amount,
        "reserved_amount": run.reserved_amount,
        "remaining_amount": None
        if run.budget_limit is None
        else run.budget_limit - run.spent_amount - run.reserved_amount,
    }


async def release_run_budget(
    session: AsyncSession,
    reservation_id: str,
    *,
    actor_id: str,
    amount: float | None = None,
) -> dict[str, Any]:
    """Release an outstanding reservation without changing settled spend.

    Releasing an already closed reservation is idempotent when no amount is
    requested.  This lets terminal run cleanup safely retry after a worker
    crash without creating negative reservations.
    """

    if amount is not None and (not math.isfinite(amount) or amount < 0):
        raise WorkflowValidationError("workflow_input_invalid", reason="released_amount")
    reservation = await session.get(BudgetReservation, reservation_id)
    if reservation is None:
        raise NotFoundError("workflow_budget_reservation_not_found", id=reservation_id)
    run = await session.get(WorkflowRun, reservation.workflow_run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=reservation.workflow_run_id)
    outstanding = max(0.0, reservation.reserved_amount)
    if outstanding == 0:
        if amount not in (None, 0):
            raise WorkflowValidationError("workflow_budget_reservation_closed", id=reservation.id)
        return {
            "reservation_id": reservation.id,
            "spent_amount": run.spent_amount,
            "reserved_amount": run.reserved_amount,
            "remaining_amount": None
            if run.budget_limit is None
            else max(0.0, run.budget_limit - run.spent_amount - run.reserved_amount),
        }
    release_amount = outstanding if amount is None else amount
    if release_amount > outstanding:
        raise WorkflowValidationError("workflow_input_invalid", reason="released_amount")
    reservation.reserved_amount = max(0.0, outstanding - release_amount)
    if reservation.reserved_amount <= 1e-9:
        reservation.reserved_amount = 0
        reservation.status = "released"
    run.reserved_amount = max(0.0, run.reserved_amount - release_amount)
    await session.commit()
    return {
        "reservation_id": reservation.id,
        "spent_amount": run.spent_amount,
        "reserved_amount": run.reserved_amount,
        "remaining_amount": None
        if run.budget_limit is None
        else max(0.0, run.budget_limit - run.spent_amount - run.reserved_amount),
    }


async def release_run_budgets(session: AsyncSession, run_id: str, *, actor_id: str) -> dict[str, Any]:
    """Release every unsettled reservation belonging to a terminal run."""

    run = await session.get(WorkflowRun, run_id)
    if run is None or run.user_id != actor_id:
        raise NotFoundError("workflow_run_not_found", id=run_id)
    reservations = (
        (await session.execute(select(BudgetReservation).where(BudgetReservation.workflow_run_id == run_id)))
        .scalars()
        .all()
    )
    released = 0.0
    for reservation in reservations:
        outstanding = max(0.0, reservation.reserved_amount)
        if outstanding == 0:
            continue
        reservation.reserved_amount = 0
        reservation.status = "released"
        released += outstanding
    run.reserved_amount = max(0.0, run.reserved_amount - released)
    await session.commit()
    return {
        "run_id": run.id,
        "released_amount": released,
        "spent_amount": run.spent_amount,
        "reserved_amount": run.reserved_amount,
        "remaining_amount": None
        if run.budget_limit is None
        else max(0.0, run.budget_limit - run.spent_amount - run.reserved_amount),
    }
