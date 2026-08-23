"""DAG execution engine for Shotwise Flow workflows.

The engine consumes published workflow revisions as runs: it schedules ready
nodes in topological order (every upstream node succeeded or skipped), executes
each node through the node adapter registry (``server.services.workflow_adapters``),
persists node outputs as asset references (``output_refs_json``), and records
node-level log/status events into the project event log so the canvas UI can
render per-node status and per-node logs.

Semantics:

- Nodes whose ``config["disabled"]`` is truthy are skipped (pass-through): their
  output is the union of upstream outputs, so downstream nodes keep working.
- A failed node fails the run (its downstream nodes stay blocked).
- A cancelled run stops scheduling; the in-flight node is marked cancelled.
- A paused run stops scheduling new nodes; in-flight generation continues.

The engine only drives state; actual generation reuses the existing Shotwise
services (GenerationQueue / adapters), so real work happens through the same
image/video channels as the rest of the product.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.workflow import (
    ProjectEventLog,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRevision,
    WorkflowRun,
    WorkflowUsageStats,
)
from lib.project_manager import get_project_manager
from lib.workflow import (
    TERMINAL_NODE_STATUSES,
    WorkflowValidationError,
    canonical_json,
    node_graph_edges,
    topological_order,
    transition_node,
    transition_run,
)

logger = logging.getLogger(__name__)

EXECUTOR_POLL_INTERVAL_SEC = 2.0

# Node run statuses that count as "dependency satisfied" for scheduling.
_PASSED = frozenset({"succeeded", "skipped"})


class NodeCancelledError(RuntimeError):
    """Raised by adapters when the workflow run is cancelled mid-execution."""


@dataclass
class AssetRef:
    """A node output: a typed reference into the project asset tree."""

    kind: str
    path: str | None = None
    count: int | None = None
    label: str = ""
    media_asset_id: str | None = None
    legacy_field: str | None = None


@dataclass
class NodeContext:
    """Everything an adapter needs to perform one node execution."""

    project_name: str
    project_path: Path
    node_key: str
    node_type: str
    config: dict[str, Any]
    upstream_outputs: dict[str, dict[str, list[AssetRef]]]
    log: Callable[[str, str], None]
    progress: Callable[[float], None]
    cancelled: Callable[[], Awaitable[bool]]
    generation_mode: str = "storyboard"


@dataclass
class NodeExecutionResult:
    """Adapter return value: output asset refs + a human summary line."""

    outputs: dict[str, list[AssetRef]] = field(default_factory=dict)
    summary: str = ""


NodeAdapter = Callable[[NodeContext], Awaitable[NodeExecutionResult]]


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _ref_to_dict(ref: AssetRef) -> dict[str, Any]:
    return {
        "kind": ref.kind,
        "path": ref.path,
        "count": ref.count,
        "label": ref.label,
        "media_asset_id": ref.media_asset_id,
    }


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _legacy_script_path(project_path: Path, config: dict[str, Any]) -> Path | None:
    candidates: list[Path] = []
    configured = config.get("script_file")
    if isinstance(configured, str) and configured.strip():
        candidates.extend((project_path / configured, project_path / "scripts" / Path(configured).name))
    try:
        project = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        project = {}
    episodes = project.get("episodes") if isinstance(project, dict) else None
    if isinstance(episodes, list):
        for episode in episodes:
            if isinstance(episode, dict) and episode.get("script_file"):
                value = str(episode["script_file"])
                candidates.extend((project_path / value, project_path / "scripts" / Path(value).name))
    return next((path for path in candidates if path.exists() and path.is_file()), None)


def _sync_legacy_outputs(project_path: Path, config: dict[str, Any], outputs: dict[str, list[AssetRef]]) -> None:
    refs = [ref for port_refs in outputs.values() for ref in port_refs if ref.legacy_field and ref.path and ref.label]
    if not refs:
        return
    script_path = _legacy_script_path(project_path, config)
    if script_path is None:
        return
    try:
        script = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    changed = False
    id_keys = ("shot_id", "scene_id", "segment_id", "unit_id", "id")
    for ref in refs:
        target = next(
            (item for item in _iter_dicts(script) if any(str(item.get(key)) == ref.label for key in id_keys)),
            None,
        )
        if target is None:
            continue
        generated = target.get("generated_assets")
        if not isinstance(generated, dict):
            generated = {}
            target["generated_assets"] = generated
        if generated.get(ref.legacy_field) != ref.path:
            generated[ref.legacy_field] = ref.path
            changed = True
        if ref.media_asset_id:
            media_key = f"{ref.legacy_field}_media_asset_id"
            if generated.get(media_key) != ref.media_asset_id:
                generated[media_key] = ref.media_asset_id
                changed = True
    if changed:
        script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _quality_gate_error_params(message: str) -> dict[str, Any]:
    """Normalize a quality-gate failure into agent-actionable error data."""
    prefix = "quality_gate_failed:"
    detail = message[len(prefix) :].strip() if message.startswith(prefix) else message
    try:
        payload = json.loads(detail)
    except (TypeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        failures = payload.get("failures")
        if isinstance(failures, list):
            return {
                "message": str(payload.get("message") or "质量门禁未通过"),
                "passed": False,
                "failures": failures,
                "repair_suggestions": [
                    str(item.get("suggestion"))
                    for item in failures
                    if isinstance(item, dict) and item.get("suggestion")
                ],
            }
    return {
        "message": detail or "质量门禁未通过",
        "passed": False,
        "failures": [],
        "repair_suggestions": ["检查失败门禁所需的输入和上游产物"],
    }


async def _append_event(
    session: AsyncSession,
    *,
    run: WorkflowRun,
    event_type: str,
    payload: dict[str, Any],
) -> ProjectEventLog:
    event = ProjectEventLog(
        event_id=uuid.uuid4().hex,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        aggregate_type="workflow_run",
        aggregate_id=run.id,
        aggregate_version=run.version,
        event_type=event_type,
        event_version=1,
        payload_json=canonical_json(payload),
        actor_type="system",
        actor_id=run.created_by,
        trace_id=run.trace_id,
        created_at=utc_now(),
    )
    session.add(event)
    return event


async def _transition_node_run(
    session: AsyncSession,
    run: WorkflowRun,
    node_run: WorkflowNodeRun,
    target: str,
    *,
    payload: dict[str, Any] | None = None,
) -> None:
    transition_node(node_run.status, target)
    node_run.status = target
    node_run.updated_at = utc_now()
    await _append_event(
        session,
        run=run,
        event_type=f"workflow.node_run.{target}",
        payload={"node_key": node_run.node_key, **(payload or {})},
    )


def _node_config(node: dict[str, Any]) -> dict[str, Any]:
    config = dict(node.get("config") or {})
    if config.get("disabled") is None:
        config["disabled"] = node.get("disabled", False)
    return config


def _collect_upstream_outputs(
    node_run: WorkflowNodeRun,
    node_runs: dict[str, WorkflowNodeRun],
    incoming: dict[str, set[str]],
) -> dict[str, dict[str, list[AssetRef]]]:
    result: dict[str, dict[str, list[AssetRef]]] = {}
    for source_key in sorted(incoming.get(node_run.node_key, set())):
        source = node_runs.get(source_key)
        if source is None or source.status not in _PASSED:
            continue
        outputs = _loads(source.output_refs_json, {})
        result[source_key] = {
            port: [AssetRef(**ref) if isinstance(ref, dict) else ref for ref in refs] for port, refs in outputs.items()
        }
    return result


def _pass_through_outputs(
    node_runs: dict[str, WorkflowNodeRun],
    incoming: dict[str, set[str]],
    node_key: str,
) -> dict[str, list[AssetRef]]:
    merged: dict[str, list[AssetRef]] = {}
    for source_key in sorted(incoming.get(node_key, set())):
        source = node_runs.get(source_key)
        if source is None or source.status not in _PASSED:
            continue
        outputs = _loads(source.output_refs_json, {})
        for port, refs in outputs.items():
            merged.setdefault(port, []).extend(refs)
    return merged


async def _skip_node(
    session: AsyncSession,
    run: WorkflowRun,
    node_run: WorkflowNodeRun,
    node: dict[str, Any],
    node_runs: dict[str, WorkflowNodeRun],
    incoming: dict[str, set[str]],
    reason: str,
) -> None:
    node_run.output_refs_json = canonical_json(_pass_through_outputs(node_runs, incoming, node_run.node_key))
    await _transition_node_run(
        session,
        run,
        node_run,
        "skipped",
        payload={"reason": reason, "node_type": node["node_type"]},
    )


async def _execute_node(
    session: AsyncSession,
    run: WorkflowRun,
    node_run: WorkflowNodeRun,
    node: dict[str, Any],
    incoming: dict[str, set[str]],
    node_runs: dict[str, WorkflowNodeRun],
    generation_mode: str = "storyboard",
) -> None:
    # blocked -> ready -> queued -> running (root nodes are planned as "ready")
    if node_run.status == "blocked":
        await _transition_node_run(session, run, node_run, "ready")
    await _transition_node_run(session, run, node_run, "queued")
    await _transition_node_run(session, run, node_run, "running")
    await session.flush()

    from server.services import workflow_adapters  # deferred: avoids import cycle

    adapter = workflow_adapters.get_adapter(str(node["node_type"]))
    if adapter is None:
        node_run.error_code = "workflow_unknown_node_type"
        await _transition_node_run(session, run, node_run, "failed")
        return

    logs: list[tuple[str, str]] = []
    progress_holder: dict[str, float] = {"value": 0.0}

    def log(level: str, line: str) -> None:
        logs.append((level, line))

    def progress(value: float) -> None:
        progress_holder["value"] = max(0.0, min(1.0, value))

    async def cancelled() -> bool:
        row = await session.execute(select(WorkflowRun.status).where(WorkflowRun.id == run.id))
        return (row.scalar_one_or_none() or "cancelled") != "running"

    ctx = NodeContext(
        project_name=run.project_id,
        project_path=get_project_manager().get_project_path(run.project_id),
        node_key=node_run.node_key,
        node_type=str(node["node_type"]),
        config=_node_config(node),
        upstream_outputs=_collect_upstream_outputs(node_run, node_runs, incoming),
        log=log,
        progress=progress,
        cancelled=cancelled,
        generation_mode=generation_mode,
    )

    try:
        result = await adapter(ctx)
    except NodeCancelledError:
        node_run.output_refs_json = None
        node_run.error_code = "workflow_node_cancelled"
        await _transition_node_run(session, run, node_run, "cancelled")
        logs.append(("warn", "node cancelled"))
    except WorkflowValidationError as exc:  # noqa: PERF203 -- validation errors are expected control flow
        node_run.error_code = exc.code
        node_run.error_params_json = canonical_json(exc.params)
        await _transition_node_run(session, run, node_run, "failed")
        logs.append(("error", f"validation failed: {exc.code} {exc.params}"))
    except Exception as exc:  # noqa: BLE001 -- adapters surface user-facing failures
        logger.exception("workflow node %s failed: %s", node_run.node_key, exc)
        message = str(exc)
        node_run.error_code = (
            "quality_gate_failed" if message.startswith("quality_gate_failed:") else type(exc).__name__
        )
        if node_run.error_code == "quality_gate_failed":
            node_run.error_params_json = canonical_json(_quality_gate_error_params(message))
        await _transition_node_run(session, run, node_run, "failed")
        logs.append(("error", f"node failed: {message}"))
    else:
        from server.services.media_assets import index_workflow_outputs

        parent_media_asset_ids = [
            str(ref.media_asset_id)
            for port_refs in ctx.upstream_outputs.values()
            for refs in port_refs.values()
            for ref in refs
            if ref.media_asset_id
        ]
        indexed_outputs = await asyncio.to_thread(
            index_workflow_outputs,
            project_id=ctx.project_name,
            project_root=ctx.project_path,
            workflow_run_id=run.id,
            workflow_node_key=node_run.node_key,
            outputs=result.outputs,
            parent_media_asset_ids=parent_media_asset_ids,
        )
        legacy_fields = {
            ref.label: ref.legacy_field for refs in result.outputs.values() for ref in refs if ref.legacy_field
        }
        for refs in indexed_outputs.values():
            for ref in refs:
                ref.legacy_field = ref.legacy_field or legacy_fields.get(ref.label)
        _sync_legacy_outputs(ctx.project_path, ctx.config, indexed_outputs)
        node_run.output_refs_json = canonical_json(
            {port: [_ref_to_dict(ref) for ref in refs] for port, refs in indexed_outputs.items()}
        )
        node_run.progress = progress_holder["value"]
        await _transition_node_run(session, run, node_run, "collecting")
        await _transition_node_run(session, run, node_run, "succeeded")
        logs.append(("info", result.summary or "node completed"))

    # Flush node logs as project events so the canvas can replay them.
    for level, line in logs:
        await _append_event(
            session,
            run=run,
            event_type="workflow.node_log",
            payload={"node_key": node_run.node_key, "level": level, "line": line},
        )


async def run_workflow_run(session: AsyncSession, run_id: str) -> dict[str, Any]:
    """Drive one workflow run to a terminal state (or until paused/cancelled)."""

    run = await session.get(WorkflowRun, run_id)
    if run is None:
        return {"id": run_id, "status": "missing"}
    if run.status != "running":
        return {"id": run_id, "status": run.status, "nodes": []}

    revision = await session.get(WorkflowRevision, run.workflow_revision_id)
    if revision is None:
        raise LookupError(f"workflow revision not found: {run.workflow_revision_id}")

    node_rows = (
        (await session.execute(select(WorkflowNode).where(WorkflowNode.revision_id == revision.id))).scalars().all()
    )
    edge_rows = (
        (await session.execute(select(WorkflowEdge).where(WorkflowEdge.revision_id == revision.id))).scalars().all()
    )
    nodes = [
        {
            "node_key": row.node_key,
            "node_type": row.node_type,
            "config": _loads(row.config_json, {}),
            "disabled": _loads(row.config_json, {}).get("disabled", False),
        }
        for row in node_rows
    ]
    edges = [
        {"source_node_key": row.source_node_key, "target_node_key": row.target_node_key, "on_failure": row.on_failure}
        for row in edge_rows
    ]
    order = topological_order(nodes, edges)
    outgoing, incoming = node_graph_edges(edges)
    by_key = {node["node_key"]: node for node in nodes}

    node_runs = {
        nr.node_key: nr
        for nr in (
            (await session.execute(select(WorkflowNodeRun).where(WorkflowNodeRun.workflow_run_id == run.id)))
            .scalars()
            .all()
        )
    }

    while True:
        await session.refresh(run)
        if run.status != "running":
            break

        # Skip disabled nodes (pass-through) before scheduling ready nodes.
        for key in order:
            node_run = node_runs.get(key)
            if node_run is None or node_run.status not in ("blocked", "ready"):
                continue
            if _node_config(by_key[key]).get("disabled"):
                await _skip_node(session, run, node_run, by_key[key], node_runs, incoming, "disabled")
        await session.flush()

        ready = [
            key
            for key in order
            if node_runs.get(key) is not None
            and node_runs[key].status in ("blocked", "ready")
            and all(node_runs[source].status in _PASSED for source in incoming.get(key, set()))
        ]
        if not ready:
            break
        for key in ready:
            await session.refresh(run)
            if run.status != "running":
                break
            await _execute_node(
                session,
                run,
                node_runs[key],
                by_key[key],
                incoming,
                node_runs,
                generation_mode=revision.generation_mode,
            )
            await session.commit()

    # Terminal evaluation: all nodes finished -> succeeded/failed; a failed node
    # with nothing left to schedule -> failed; otherwise the run stays running
    # for the next tick (paused/cancelled handled above).
    await session.refresh(run)
    statuses = [node_runs[key].status for key in node_runs]
    progress = sum(1 for status in statuses if status in TERMINAL_NODE_STATUSES) / max(1, len(statuses))
    run.progress = progress
    target: str | None = None
    if run.status == "running":
        quality_gate_failed = any(node_runs[key].error_code == "quality_gate_failed" for key in node_runs)
        if quality_gate_failed:
            target = "waiting_review"
        elif all(status in TERMINAL_NODE_STATUSES for status in statuses):
            target = "succeeded" if "failed" not in statuses else "failed"
        elif any(status in {"failed", "stale", "orphaned"} for status in statuses):
            target = "failed"
    if target is not None:
        previous = run.status
        transition_run(previous, target)
        run.status = target
        run.version += 1
        run.progress = 1.0 if target == "succeeded" else run.progress
        run.finished_at = utc_now()
        template_lock = _loads(revision.template_lock_json, {})
        template_id = template_lock.get("template_id") if isinstance(template_lock, dict) else None
        if template_id:
            stats = await session.get(WorkflowUsageStats, template_id)
            if stats is not None:
                stats.run_count += 1
                if target == "succeeded":
                    stats.successful_run_count += 1
                stats.total_cost += float(run.spent_amount or 0)
                if run.started_at is not None:
                    stats.total_duration_seconds += max(0.0, (run.finished_at - run.started_at).total_seconds())
        await _append_event(
            session,
            run=run,
            event_type=f"workflow.run.{target}",
            payload={"status": target, "control_generation": run.control_generation},
        )
        await session.commit()
        return {"id": run.id, "status": run.status, "nodes": len(statuses)}

    await session.commit()
    return {"id": run.id, "status": run.status, "nodes": len(statuses)}


async def process_workflow_runs(session: AsyncSession) -> list[dict[str, Any]]:
    """Process every run that is currently running (one engine tick)."""

    rows = (
        (
            await session.execute(
                select(WorkflowRun).where(WorkflowRun.status == "running").order_by(WorkflowRun.created_at)
            )
        )
        .scalars()
        .all()
    )
    results = []
    for run in rows:
        results.append(await run_workflow_run(session, run.id))
    return results


async def workflow_executor_loop() -> None:
    """Background loop started with the app: polls and drives running runs."""

    from lib.db import async_session_factory  # deferred: import cycle at module load

    while True:
        try:
            async with async_session_factory() as session:
                await process_workflow_runs(session)
        except Exception:  # noqa: BLE001 -- the loop must survive tick failures
            logger.exception("workflow executor tick failed")
        await asyncio.sleep(EXECUTOR_POLL_INTERVAL_SEC)
