"""Agent SDK adapter for contextual reference resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from claude_agent_sdk import tool

from lib.creative_context import ContextReference, SelectedResource, resolve_context_references
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error


def resolve_context_references_tool(
    *,
    project_id: str,
    project: Mapping[str, object],
    references: Sequence[Mapping[str, object]],
    selected_resources: Sequence[Mapping[str, object] | SelectedResource] = (),
    board_items: Sequence[object] = (),
    media_assets: object = None,
    episode_id: str | None = None,
    shot_id: str | None = None,
) -> dict[str, object]:
    """Resolve structured references without creating a plan or workflow run."""

    normalized_references: list[ContextReference] = []
    for item in references:
        expected_type = item.get("expected_type")
        if not isinstance(expected_type, str):
            expected_type = None
        normalized_references.append(ContextReference(text=str(item.get("text", "")), expected_type=expected_type))

    normalized_selected: list[SelectedResource] = []
    for item in selected_resources:
        if isinstance(item, SelectedResource):
            normalized_selected.append(item)
            continue
        resource_id = item.get("id")
        resource_type = item.get("resource_type")
        if isinstance(resource_id, str) and isinstance(resource_type, str):
            normalized_selected.append(SelectedResource(id=resource_id, resource_type=resource_type))

    return resolve_context_references(
        project_id=project_id,
        project=project,
        references=normalized_references,
        selected_resources=normalized_selected,
        board_items=board_items,
        media_assets=media_assets,
        episode_id=episode_id,
        shot_id=shot_id,
    )


def context_reference_tool(ctx: ToolContext) -> Any:
    """Build the registered in-process resolver for Claude and OpenAI Agents."""

    @tool(
        "resolve_context_references",
        "Resolve contextual references to explicit IDs without creating a plan or run.",
        {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "candidate_context": {"type": "object"},
                "references": {"type": "array", "items": {"type": "object"}},
                "selected_resources": {"type": "array", "items": {"type": "object"}},
                "board_items": {"type": "array"},
                "media_assets": {"type": "array"},
                "episode_id": {"type": "string"},
                "shot_id": {"type": "string"},
            },
            "required": ["references"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            project = ctx.pm.load_project(ctx.project_name)
            candidate_context = args.get("candidate_context")
            if isinstance(candidate_context, Mapping):
                project = {**project, **dict(candidate_context)}
            requested_project_id = args.get("project_id")
            if requested_project_id is not None and str(requested_project_id) != ctx.project_name:
                return {
                    "content": [{"type": "text", "text": "项目上下文不匹配。"}],
                    "structured_content": {
                        "status": "error",
                        "error": {"code": "project_mismatch"},
                        "resolved": {},
                    },
                }
            references = [item for item in args.get("references", ()) if isinstance(item, Mapping)]
            selected_resources = [
                item for item in args.get("selected_resources", ()) if isinstance(item, (Mapping, SelectedResource))
            ]
            result = resolve_context_references_tool(
                project_id=ctx.project_name,
                project=project,
                references=references,
                selected_resources=selected_resources,
                board_items=args.get("board_items", ()),
                media_assets=args.get("media_assets"),
                episode_id=args.get("episode_id") if isinstance(args.get("episode_id"), str) else None,
                shot_id=args.get("shot_id") if isinstance(args.get("shot_id"), str) else None,
            )
            return {
                "content": [{"type": "text", "text": "上下文引用解析完成。"}],
                "structured_content": result,
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("resolve_context_references", exc)

    return _handler


def build_resolve_context_references_tool(ctx: ToolContext) -> Any:
    """Compatibility factory used by the internal SDK catalogue."""

    return context_reference_tool(ctx)


__all__ = [
    "build_resolve_context_references_tool",
    "context_reference_tool",
    "resolve_context_references_tool",
]
