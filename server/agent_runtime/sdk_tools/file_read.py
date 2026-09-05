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
from server.services.project_files import enumerate_project_text_files, project_text_files_signature

_ALLOWED_SUFFIXES = {".txt", ".md", ".json"}
_ALLOWED_ROOTS = ("source", "scripts", "drafts")
_MAX_LINES = 400
_MAX_CHARS = 120_000


def list_project_text_files_tool(ctx: ToolContext) -> Any:
    @tool(
        "list_project_text_files",
        "列出当前绑定项目的文稿、草稿和结构化剧本文本文件，不读取全文。文稿任务开始前必须调用；默认检查 source/，且不包含 source/raw/ 上传备份。",
        {"type": "object", "properties": {}},
    )
    async def _handler(_args: dict[str, Any]) -> dict[str, Any]:
        try:
            project_path = ctx.project_path.resolve()
            files = enumerate_project_text_files(project_path)
            ctx.mark_text_files_listed(project_text_files_signature(project_path))
            documents_by_category = {
                category: [item for item in files if item["category"] == category]
                for category in ("source", "drafts", "scripts")
            }
            metadata = [item for item in files if item["category"] == "metadata"]
            primary_category = next(
                (category for category in ("source", "drafts", "scripts") if documents_by_category[category]),
                None,
            )
            lines = [f"当前项目: {ctx.project_name}", "文稿目录优先级：source/ → drafts/ → scripts/"]
            if primary_category is None:
                lines.append("当前首选文稿候选：无（这不代表页面没有其他类型文件）")
            else:
                lines.append(f"当前首选文稿候选（{primary_category}/）：")
                lines.extend(
                    f"- {item['path']} ({item['size']} bytes)" for item in documents_by_category[primary_category]
                )
                for category in ("source", "drafts", "scripts"):
                    if category == primary_category or not documents_by_category[category]:
                        continue
                    lines.append(f"备用项目文本（{category}/，仅在首选目录没有合适文稿时使用）：")
                    lines.extend(f"- {item['path']} ({item['size']} bytes)" for item in documents_by_category[category])
            if metadata:
                lines.append("项目元数据（不计入文稿候选，仅按需读取）：")
                lines.extend(f"- {item['path']} ({item['size']} bytes)" for item in metadata)
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}
        except (OSError, ValueError) as exc:
            return tool_error("list_project_text_files", exc)

    return _handler


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
            if not ctx.has_fresh_text_file_list():
                raise ValueError("请先调用 list_project_text_files 获取当前项目文件清单；文件发生变化后必须重新列出")
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
            relative_lower = relative.lower()
            if relative_lower == "source/raw" or relative_lower.startswith("source/raw/"):
                raise ValueError("source/raw/ 是上传备份目录，不作为文稿读取")
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
