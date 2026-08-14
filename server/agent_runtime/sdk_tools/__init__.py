"""Shotwise SDK in-process MCP tools.

Tools registered here run **in the server main process** (not inside the
agent sandbox), so they can read ``projects/.shotwise.db`` and call provider
HTTP without poking holes in ``filesystem.denyRead`` / network allowlist.

Each session gets its own MCP server built via :func:`build_shotwise_mcp_server`
— ``project_name`` is closure-bound, so the agent cannot redirect tools to a
different project via prompt injection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server

from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.enqueue_assets import (
    generate_assets_tool,
    list_pending_assets_tool,
)
from server.agent_runtime.sdk_tools.enqueue_grid import generate_grid_tool
from server.agent_runtime.sdk_tools.enqueue_image_edits import edit_images_tool
from server.agent_runtime.sdk_tools.enqueue_narration_audio import generate_narration_audio_tool
from server.agent_runtime.sdk_tools.enqueue_storyboards import generate_storyboards_tool
from server.agent_runtime.sdk_tools.enqueue_videos import (
    generate_video_all_tool,
    generate_video_episode_tool,
    generate_video_scene_tool,
    generate_video_selected_tool,
)
from server.agent_runtime.sdk_tools.episode_planning import (
    plan_episodes_tool,
    reset_episode_planning_tool,
)
from server.agent_runtime.sdk_tools.patch_episode_meta import patch_episode_meta_tool
from server.agent_runtime.sdk_tools.patch_project import patch_project_tool
from server.agent_runtime.sdk_tools.patch_script import (
    insert_segment_tool,
    patch_episode_script_tool,
    remove_segment_tool,
    split_segment_tool,
)
from server.agent_runtime.sdk_tools.text_generation import (
    confirm_script_review_tool,
    generate_episode_script_tool,
    get_video_capabilities_tool,
    normalize_drama_script_tool,
    open_reference_step1_for_edit_tool,
    split_narration_segments_tool,
    split_reference_video_units_tool,
    validate_and_promote_reference_draft_tool,
)

__all__ = ["build_shotwise_mcp_server", "ToolContext", "SHOTWISE_MCP_TOOL_IDS"]

# Single source of truth for the Shotwise in-process MCP tool catalogue.
# Each id is the **short tool name** (without the ``mcp__shotwise__`` prefix the
# SDK adds at registration). Frontend display names live in
# ``frontend/src/i18n/{zh,en,vi}/dashboard.ts`` under the ``tool_name_<id>``
# keys; ``tests/test_frontend_mcp_tool_i18n.py`` cross-checks that every id
# here has a translation in all locales, so adding a tool without wiring up
# i18n fails CI.
SHOTWISE_MCP_TOOL_IDS: tuple[str, ...] = (
    "list_pending_assets",
    "generate_assets",
    "generate_storyboards",
    "edit_images",
    "generate_grid",
    "generate_video_episode",
    "generate_video_scene",
    "generate_video_all",
    "generate_video_selected",
    "generate_narration_audio",
    "generate_episode_script",
    "confirm_script_review",
    "normalize_drama_script",
    "split_reference_video_units",
    "open_reference_step1_for_edit",
    "validate_and_promote_reference_draft",
    "split_narration_segments",
    "get_video_capabilities",
    "plan_episodes",
    "reset_episode_planning",
    "patch_episode_script",
    "patch_episode_meta",
    "insert_segment",
    "remove_segment",
    "split_segment",
    "patch_project",
)


def build_shotwise_tool_list(*, project_name: str, projects_root: Path) -> list[Any]:
    """构建全部 Shotwise 工具定义（SdkMcpTool 列表）。

    Claude 通道经 ``create_sdk_mcp_server`` in-process 注册；OpenAI Agents SDK
    通道经 ``build_shotwise_agents_tools`` 转成 FunctionTool 进程内注册。两条
    通道共用同一批工具工厂，行为一致。
    """
    ctx = ToolContext(project_name=project_name, projects_root=projects_root)
    return [
        list_pending_assets_tool(ctx),
        generate_assets_tool(ctx),
        generate_storyboards_tool(ctx),
        edit_images_tool(ctx),
        generate_grid_tool(ctx),
        generate_video_episode_tool(ctx),
        generate_video_scene_tool(ctx),
        generate_video_all_tool(ctx),
        generate_video_selected_tool(ctx),
        generate_narration_audio_tool(ctx),
        generate_episode_script_tool(ctx),
        confirm_script_review_tool(ctx),
        normalize_drama_script_tool(ctx),
        split_reference_video_units_tool(ctx),
        open_reference_step1_for_edit_tool(ctx),
        validate_and_promote_reference_draft_tool(ctx),
        split_narration_segments_tool(ctx),
        get_video_capabilities_tool(ctx),
        plan_episodes_tool(ctx),
        reset_episode_planning_tool(ctx),
        patch_episode_script_tool(ctx),
        patch_episode_meta_tool(ctx),
        insert_segment_tool(ctx),
        remove_segment_tool(ctx),
        split_segment_tool(ctx),
        patch_project_tool(ctx),
    ]


def build_shotwise_mcp_server(*, project_name: str, projects_root: Path) -> Any:
    """Build the per-session in-process MCP server with all Shotwise tools."""
    tools = build_shotwise_tool_list(project_name=project_name, projects_root=projects_root)
    return create_sdk_mcp_server(
        name="shotwise",
        version="1.0.0",
        tools=tools,
    )


def build_shotwise_agents_tools(*, project_name: str, projects_root: Path) -> list[Any]:
    """把 Shotwise 工具转成 OpenAI Agents SDK 的 FunctionTool 列表（进程内注册）。

    复用 ``build_shotwise_tool_list`` 的 SdkMcpTool（name / description /
    input_schema / handler），handler 签名是 ``async (args: dict) -> dict``，
    适配到 FunctionTool 的 ``on_invoke_tool(context, params_json) -> str``。
    """
    tools: list[Any] = []
    for sdk_tool in build_shotwise_tool_list(project_name=project_name, projects_root=projects_root):
        tools.append(_sdk_tool_to_function_tool(sdk_tool))
    return tools


def _sdk_tool_to_function_tool(sdk_tool: Any) -> Any:
    from agents import FunctionTool

    async def on_invoke_tool(_context: Any, params_json: str) -> str:
        try:
            args = json.loads(params_json) if params_json else {}
        except json.JSONDecodeError:
            args = {}
        try:
            result = await sdk_tool.handler(args)
        except Exception as exc:  # 工具异常转为模型可见文本，不打断整轮
            return f"{sdk_tool.name} failed: {exc}"
        if not isinstance(result, dict):
            return str(result)
        texts: list[str] = []
        content = result.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        texts.append(text)
        return "\n".join(texts) if texts else str(result)

    return FunctionTool(
        name=sdk_tool.name,
        description=sdk_tool.description,
        params_json_schema=_sdk_tool_json_schema(sdk_tool),
        on_invoke_tool=on_invoke_tool,
    )


def _sdk_tool_json_schema(sdk_tool: Any) -> dict[str, Any]:
    """把 SdkMcpTool.input_schema（dict 或 TypedDict）转成 JSON Schema。"""
    schema = getattr(sdk_tool, "input_schema", None)
    if isinstance(schema, dict):
        if "type" in schema and isinstance(schema["type"], str):
            return schema
        props: dict[str, Any] = {}
        for name, py_type in schema.items():
            props[name] = _python_type_to_json_schema(py_type)
        return {"type": "object", "properties": props}
    if isinstance(schema, type):
        return _python_type_to_json_schema(schema)
    return {"type": "object"}


def _python_type_to_json_schema(py_type: Any) -> dict[str, Any]:
    from typing import Annotated, get_args, get_origin

    origin = get_origin(py_type)
    if getattr(origin, "_name", None) in ("NotRequired", "Required", "ReadOnly"):
        return _python_type_to_json_schema(get_args(py_type)[0])
    if origin is Annotated:
        args = get_args(py_type)
        schema = _python_type_to_json_schema(args[0])
        for meta in args[1:]:
            if isinstance(meta, str):
                schema["description"] = meta
                break
        return schema
    if py_type is str:
        return {"type": "string"}
    if py_type is int:
        return {"type": "integer"}
    if py_type is float:
        return {"type": "number"}
    if py_type is bool:
        return {"type": "boolean"}
    raw_origin = getattr(py_type, "__origin__", None)
    if raw_origin is not None:
        origin_name = getattr(raw_origin, "_name", None)
        if origin_name in ("Union", "Optional"):
            args = getattr(py_type, "__args__", ())
            non_none = [a for a in args if a is not type(None)]  # noqa: E721
            if len(non_none) == 1:
                return _python_type_to_json_schema(non_none[0])
            return {"anyOf": [_python_type_to_json_schema(a) for a in non_none]}
        if raw_origin is list:
            item_args = getattr(py_type, "__args__", ())
            if item_args:
                return {"type": "array", "items": _python_type_to_json_schema(item_args[0])}
            return {"type": "array"}
        if raw_origin is dict:
            return {"type": "object"}
    return {"type": "string"}
