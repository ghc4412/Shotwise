"""Project events emitted when durable publish jobs change state."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from lib.project_change_hints import ProjectChangeSource, emit_project_change_batch

logger = logging.getLogger(__name__)

PUBLISH_JOB_ENTITY_TYPE = "publish_job"
PUBLISH_JOB_UPDATED_ACTION = "publish_job_updated"


def build_publish_job_change(
    publish_job_id: str,
    *,
    action: str = PUBLISH_JOB_UPDATED_ACTION,
) -> dict[str, Any]:
    """Build a publish-job refresh signal for the project event stream."""
    normalized_id = str(publish_job_id).strip()
    if not normalized_id:
        raise ValueError("publish_job_id must not be empty")
    return {
        "entity_type": PUBLISH_JOB_ENTITY_TYPE,
        "action": action,
        "entity_id": normalized_id,
        "label": normalized_id,
        "focus": None,
        "important": False,
    }


def emit_publish_job_events(
    project_name: str,
    publish_job_ids: Iterable[str],
    *,
    source: ProjectChangeSource = "worker",
) -> None:
    """Emit best-effort publish-job refresh signals."""
    normalized_project = str(project_name).strip()
    if not normalized_project:
        return
    changes = []
    for publish_job_id in publish_job_ids:
        try:
            changes.append(build_publish_job_change(publish_job_id))
        except ValueError:
            continue
    if not changes:
        return
    try:
        emit_project_change_batch(normalized_project, changes, source=source)
    except Exception:
        logger.exception("发送发布任务项目事件失败 project=%s count=%d", normalized_project, len(changes))


def emit_publish_job_event(
    project_name: str,
    publish_job_id: str,
    *,
    source: ProjectChangeSource = "worker",
) -> None:
    """Emit one publish-job refresh signal."""
    emit_publish_job_events(project_name, (publish_job_id,), source=source)


__all__ = [
    "PUBLISH_JOB_ENTITY_TYPE",
    "PUBLISH_JOB_UPDATED_ACTION",
    "build_publish_job_change",
    "emit_publish_job_event",
    "emit_publish_job_events",
]
