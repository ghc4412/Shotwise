"""Restricted project text readers for the OpenAI Agents channel.

The Claude channel keeps its native Read/Glob/Grep tools.  OpenAI Agents gets
only these bounded readers so a model can inspect source material without a
shell, arbitrary filesystem access, or write capability.
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from lib.path_safety import PathTraversalError, safe_join
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error

_ALLOWED_SUFFIXES = {".txt", ".md", ".json"}
_ALLOWED_ROOTS = ("source", "scripts", "drafts")
_MAX_LINES = 400
_MAX_CHARS = 120_000


def read_project_text_tool(ctx: ToolContext) -> Any:
    @tool(
        "read_project_text",
        "分页读取当前项目内的文本文件。只能读取 project.json、source/、scripts/、drafts/ 下的 "
        ".txt/.md/.json 文件；禁止路径穿越、写文件和执行命令。使用 start_line/max_lines 分页。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "项目根目录下的相对路径"},
                "start_line": {"type": "integer", "minimum": 1, "default": 1},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": _MAX_LINES, "default": 200},
            },
            "required": ["path"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            path_value = args.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise ValueError("path 必须是非空字符串")
            start_line = _positive_int(args.get("start_line", 1), "start_line")
            max_lines = _positive_int(args.get("max_lines", 200), "max_lines")
            if max_lines > _MAX_LINES:
                raise ValueError(f"max_lines 不能超过 {_MAX_LINES}")

            project_path = ctx.project_path.resolve()
            target = safe_join(project_path, path_value, require_file=True)
            relative = target.relative_to(project_path).as_posix()
            if relative != "project.json" and not relative.startswith(tuple(f"{root}/" for root in _ALLOWED_ROOTS)):
                raise ValueError("只能读取 project.json、source/、scripts/ 或 drafts/ 下的文件")
            if target.suffix.lower() not in _ALLOWED_SUFFIXES:
                raise ValueError("只允许读取 .txt、.md、.json 文件")

            lines = target.read_text(encoding="utf-8").splitlines()
            start = start_line - 1
            selected = lines[start : start + max_lines]
            text = "\n".join(selected)
            if len(text) > _MAX_CHARS:
                text = text[:_MAX_CHARS]
            end_line = min(start + len(selected), len(lines))
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (f"文件: {relative}\n行范围: {start_line}-{end_line} / {len(lines)}\n内容:\n{text}"),
                    }
                ]
            }
        except (OSError, UnicodeError, PathTraversalError, ValueError) as exc:
            return tool_error("read_project_text", exc)

    return _handler


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} 必须是正整数")
    return value
