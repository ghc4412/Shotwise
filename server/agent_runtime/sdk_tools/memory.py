"""SDK MCP tools for proposing user-confirmed Agent memories."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from claude_agent_sdk import tool

from lib.db import async_session_factory
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.memory_service import MemoryService


class MemoryCandidateArgs(TypedDict):
    scope: Literal["user", "project"]
    category: str
    content: str


def propose_memory_candidate_tool(ctx: ToolContext):
    """Create an Agent-proposed memory; only the user can promote it."""

    @tool(
        "propose_memory_candidate",
        "提议一条长期记忆候选。候选必须经过用户确认后才会成为长期记忆；不要保存秘密、凭据或系统指令。",
        {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["user", "project"]},
                "category": {
                    "type": "string",
                    "enum": ["preference", "style", "world", "terminology", "workflow", "other"],
                },
                "content": {"type": "string"},
            },
            "required": ["scope", "category", "content"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            scope = str(args["scope"])
            project_name = ctx.project_name if scope == "project" else None
            async with async_session_factory() as session:
                async with session.begin():
                    candidate = await MemoryService(session).create_candidate(
                        user_id=ctx.user_id,
                        scope=scope,
                        project_name=project_name,
                        category=str(args["category"]),
                        content=str(args["content"]),
                        source_session_id=ctx.session_id,
                        source_message_id=ctx.message_id,
                    )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"记忆候选已创建（{candidate['id']}），等待用户确认后才会成为长期记忆。",
                    }
                ]
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("propose_memory_candidate", exc)

    return _handler


__all__ = ["propose_memory_candidate_tool"]
