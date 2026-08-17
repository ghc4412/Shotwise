"""Agent Runtime tool for AI character relationship analysis."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.character_relations import analyze_character_relations


def analyze_character_relations_tool(ctx: ToolContext) -> Any:
    @tool(
        "analyze_character_relations",
        "分析当前项目已登记角色之间的语义关系（亲属、恋爱、盟友、敌对等），"
        "读取项目概述、角色描述和剧本证据，校验后直接写入正式关系图谱。"
        "保留用户在画布中的人工修改与删除；失败时保留旧图并返回失败原因。",
        {"type": "object", "properties": {}},
    )
    async def _handler(_args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await analyze_character_relations(ctx.pm, ctx.project_name)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"角色关系分析完成，当前关系数: {len(result.get('edges', []))}",
                    }
                ],
                "structured_content": result,
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("analyze_character_relations", exc)

    return _handler


__all__ = ["analyze_character_relations_tool"]
