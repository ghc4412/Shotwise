"""Project events emitted when durable render jobs change state."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from lib.project_change_hints import ProjectChangeSource, emit_project_change_batch

logger = logging.getLogger(__name__)

RENDER_JOB_ENTITY_TYPE = "render_job"
RENDER_JOB_UPDATED_ACTION = "render_job_updated"


def build_render_job_change(
    render_job_id: str,
    *,
    action: str = RENDER_JOB_UPDATED_ACTION,
) -> dict[str, Any]:
    """Build a render-job refresh signal for the project event stream."""

    normalized_id = str(render_job_id).strip()
    if not normalized_id:
        raise ValueError("render_job_id must not be empty")
    return {
        "entity_type": RENDER_JOB_ENTITY_TYPE,
        "action": action,
        "entity_id": normalized_id,
        "label": normalized_id,
        "focus": None,
        "important": False,
    }


def emit_render_job_events(
    project_name: str,
    render_job_ids: Iterable[str],
    *,
    source: ProjectChangeSource = "worker",
) -> None:
    """Emit best-effort render-job refresh signals."""

    normalized_project = str(project_name).strip()
    if not normalized_project:
        return
    changes = []
    for render_job_id in render_job_ids:
        try:
            changes.append(build_render_job_change(render_job_id))
        except ValueError:
            continue
    if not changes:
        return
    try:
        emit_project_change_batch(normalized_project, changes, source=source)
    except Exception:
        logger.exception("发送渲染任务项目事件失败 project=%s count=%d", normalized_project, len(changes))


def emit_render_job_event(
    project_name: str,
    render_job_id: str,
    *,
    source: ProjectChangeSource = "worker",
) -> None:
    """Emit one render-job refresh signal."""

    emit_render_job_events(project_name, (render_job_id,), source=source)


__all__ = [
    "RENDER_JOB_ENTITY_TYPE",
    "RENDER_JOB_UPDATED_ACTION",
    "build_render_job_change",
    "emit_render_job_event",
    "emit_render_job_events",
]
