from pathlib import Path

import pytest

from server.agent_runtime.sdk_tools import (
    SHOTWISE_MCP_TOOL_IDS,
    build_shotwise_agents_tools,
    build_shotwise_tool_list,
)

pytestmark = pytest.mark.unit


def test_context_resolver_is_registered_for_claude_without_public_catalog_entry() -> None:
    tools = build_shotwise_tool_list(project_name="demo", projects_root=Path("."))

    assert any(item.name == "resolve_context_references" for item in tools)
    assert "resolve_context_references" not in SHOTWISE_MCP_TOOL_IDS


def test_context_resolver_is_registered_for_openai_agents() -> None:
    pytest.importorskip("agents")
    tools = build_shotwise_agents_tools(project_name="demo", projects_root=Path("."))

    assert any(item.name == "resolve_context_references" for item in tools)


@pytest.mark.asyncio
async def test_context_resolver_has_no_plan_or_run_side_effect() -> None:
    resolver = next(
        item
        for item in build_shotwise_tool_list(project_name="demo", projects_root=Path("."))
        if item.name == "resolve_context_references"
    )
    result = await resolver.handler({"references": [{"text": "她"}]})
    structured = result.get("structured_content", result)

    assert "creation_plan_id" not in structured
    assert "workflow_run_id" not in structured
