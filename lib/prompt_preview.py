"""Safe prompt preview snapshots captured at task admission.

The queue stores the snapshot beside the task payload so the task detail API can
show what was actually admitted without exposing provider credentials or making
the UI reconstruct a request from mutable project data.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

PROMPT_PREVIEW_PAYLOAD_KEY = "__shotwise_prompt_preview"
"""Internal payload key; removed from the public task payload projection."""


def _prompt_text(value: object) -> tuple[str, str]:
    if isinstance(value, str):
        return value, "plain_text"
    if isinstance(value, Mapping):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), "structured"
        except (TypeError, ValueError):
            return "", "unknown"
    return ("" if value is None else str(value)), "unknown"


def _provider_and_model(provider_id: str | None, payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    provider = provider_id or None
    model: str | None = None
    for key in ("video_provider_i2v", "video_provider_r2v", "image_provider_t2i", "image_provider_i2i"):
        value = payload.get(key)
        if not isinstance(value, str) or "/" not in value:
            continue
        candidate_provider, candidate_model = value.split("/", 1)
        if candidate_provider and candidate_model:
            provider = provider or candidate_provider
            model = candidate_model
            break
    return provider, model


def _references(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:32]:
        if isinstance(item, Mapping):
            label = item.get("label") or item.get("name") or item.get("id")
            raw_value = item.get("value") or item.get("url") or item.get("path") or item.get("id")
            if isinstance(raw_value, str) and raw_value:
                result.append(
                    {
                        "kind": str(item.get("kind") or item.get("type") or "other"),
                        "label": str(label or raw_value),
                        "value": raw_value,
                    }
                )
        elif isinstance(item, str) and item:
            result.append({"kind": "other", "label": item, "value": item})
    return result


def build_enqueue_prompt_preview(
    *,
    project_name: str,
    task_type: str,
    media_type: str,
    resource_id: str,
    script_file: str | None,
    provider_id: str | None,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a bounded, provider-agnostic preview for one admitted task.

    This is intentionally not a provider payload serializer. Provider-specific
    normalization still happens at execution time, while this snapshot records
    the immutable enqueue inputs and the safe metadata known at admission.
    """
    original_prompt, shape = _prompt_text(payload.get("prompt"))
    provider, model = _provider_and_model(provider_id, payload)
    references = _references(payload.get("references"))
    summary: dict[str, Any] = {
        "project_name": project_name,
        "task_type": task_type,
        "media_type": media_type,
        "resource_id": resource_id,
    }
    if script_file:
        summary["script_file"] = script_file

    request: dict[str, Any] = {
        "id": resource_id,
        "label": f"{task_type}:{resource_id}",
        "original_prompt": original_prompt,
        "effective_prompt": original_prompt or None,
        "shape": shape,
        "provider": provider,
        "model": model,
        "references": references,
        "duration_seconds": payload.get("duration_seconds")
        if isinstance(payload.get("duration_seconds"), (int, float))
        and not isinstance(payload.get("duration_seconds"), bool)
        else None,
        "resolution": payload.get("resolution") if isinstance(payload.get("resolution"), str) else None,
        "capability_adjustments": [
            item for item in payload.get("capability_adjustments", [])[:32] if isinstance(item, str)
        ]
        if isinstance(payload.get("capability_adjustments"), list)
        else [],
        "warnings": [item for item in payload.get("warnings", [])[:32] if isinstance(item, str)]
        if isinstance(payload.get("warnings"), list)
        else [],
        "request_summary": summary,
    }
    return {"source": "enqueue_snapshot", "requests": [request]}


__all__ = ["PROMPT_PREVIEW_PAYLOAD_KEY", "build_enqueue_prompt_preview"]
