"""Application service for Shotwise workflow definitions and runs."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.api_errors import ConflictError, NotFoundError
from lib.db.base import utc_now
from lib.db.models.workflow import (
    ProjectEventLog,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRevision,
    WorkflowRun,
)
from lib.workflow import (
    WorkflowValidationError,
    canonical_json,
    graph_hash,
    input_fingerprint,
    transition_run,
    validate_graph,
)

ACTIVE_RUN_STATUSES = ("planned", "running", "paused", "waiting_review")


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


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
) -> dict[str, Any]:
    validate_graph(nodes, edges)
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
        payload={"definition_id": definition_id, "revision_no": revision_no},
        actor_id=actor_id,
    )
    await session.commit()
    return {
        "id": revision.id,
        "revision_no": revision_no,
        "status": revision.status,
        "graph_hash": revision.graph_hash,
        "execution_hash": revision.execution_hash,
        "version": 1,
        "event_cursor": event.seq,
    }


async def _revision_graph(
    session: AsyncSession, revision_id: str, *, actor_id: str
) -> tuple[WorkflowRevision, list[dict[str, Any]], list[dict[str, Any]]]:
    revision = await session.get(WorkflowRevision, revision_id)
    if revision is None:
        raise NotFoundError("workflow_revision_not_found", id=revision_id)
    definition = await session.get(WorkflowDefinition, revision.definition_id)
    if definition is None or definition.user_id != actor_id:
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
    if definition.active_revision_id:
        revision, nodes, edges = await _revision_graph(session, definition.active_revision_id, actor_id=actor_id)
        result["active_revision"] = {
            "id": revision.id,
            "revision_no": revision.revision_no,
            "status": revision.status,
            "graph_hash": revision.graph_hash,
            "execution_hash": revision.execution_hash,
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
) -> dict[str, Any]:
    if mode not in {"auto", "manual", "hybrid"}:
        raise WorkflowValidationError("workflow_input_invalid", reason="mode")
    revision, nodes, edges = await _revision_graph(session, revision_id, actor_id=actor_id)
    if revision.status != "published":
        raise ConflictError("workflow_revision_not_published", id=revision_id)
    definition = await session.get(WorkflowDefinition, revision.definition_id)
    if definition is None or definition.workspace_id != workspace_id or definition.project_id != project_id:
        raise NotFoundError("workflow_revision_not_found", id=revision_id)
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
        payload={"revision_id": revision.id, "mode": mode, "input_fingerprint": fingerprint},
        actor_id=actor_id,
        trace_id=trace_id,
    )
    await session.commit()
    return {"id": run.id, "status": run.status, "version": 1, "event_cursor": event.seq, "deduped": False}


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
