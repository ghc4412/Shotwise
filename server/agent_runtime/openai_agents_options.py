"""OpenAI Agents SDK 的 options 装配：Agent / provider / SQLiteSession。

与 ``options_assembler.OptionsAssembler``（Claude 通道）对应。产出
``OpenAIAgentsBuildResult``，由 SessionManager 交给 ``OpenAIAgentsSessionClient``
消费。

会话续接：Agents SDK 的会话历史由 ``SQLiteSession`` 按 ``session_id`` 持久化
到本地 SQLite 文件（``projects_root/.openai_agents_sessions.db``），续接时用
相同 ``session_id`` 即自动恢复历史——因此 OpenAI 通道不需要在 agent_sessions 表
存额外的 SDK 会话 id，直接复用对外 ``sdk_session_id``。

认证：OpenAI 兼容端点（DeepSeek / Kimi / GLM 等）按凭证协议选择 Chat
Completions 或 Responses，经 ``OpenAIProvider`` 注入 active
credential（``build_openai_agents_env_dict``）。
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.agent_protocol import (
    PROTOCOL_RESPONSES,
    normalize_protocol,
)
from lib.i18n import DEFAULT_LOCALE
from server.agent_runtime.document_workflow import PROJECT_DOCUMENT_WORKFLOW

_OPENAI_PERSONA_PROMPT = """你是 Shotwise 智能体，一个专业的 AI 视频内容创作助手。
你负责把小说内容转化为可发布的短视频内容，并通过已注册的工具完成项目操作。

## 工具约束
- 只能调用系统实际提供的工具；工具名称必须来自工具列表。
- 不得调用或臆造 Bash、Read、Write、Edit、Glob、Grep、TodoWrite、base64_writer 等未注册工具。
- 文稿检查必须先调用 list_project_text_files 获取清单，再使用 read_project_text 按页读取；不要执行命令或直接修改文件。
- 项目数据修改只能使用已注册的 Shotwise 工具。
"""

logger = logging.getLogger(__name__)


@dataclass
class OpenAIAgentsBuildResult:
    provider: Any
    model: str
    system_prompt: str
    session: Any  # SQLiteSession
    max_turns: int | None
    tools: list[Any]


class OpenAIAgentsOptionsAssembler:
    """把开会话时现场收集的依赖装配成 OpenAIAgentsBuildResult。"""

    def __init__(
        self,
        *,
        projects_root: Path,
        resolve_project_cwd: Callable[[str], Path],
        prompt_builder: Callable[[str, str], str] | None = None,
        provider_env_loader: Callable[[], Any] | None = None,
        max_turns_provider: Callable[[], int | None] | None = None,
        session_db_path: Path | None = None,
        history_loader: Callable[[str], Any] | None = None,
    ) -> None:
        self.projects_root = Path(projects_root)
        self._resolve_project_cwd = resolve_project_cwd
        self._prompt_builder = prompt_builder
        self._provider_env_loader = provider_env_loader
        self._max_turns_provider = max_turns_provider
        self._session_db_path = session_db_path or (self.projects_root / ".openai_agents_sessions.db")
        self._history_loader = history_loader

    async def build(
        self,
        project_name: str,
        *,
        session_id: str,
        model: str = "",
        locale: str = DEFAULT_LOCALE,
    ) -> OpenAIAgentsBuildResult:
        from agents import OpenAIProvider, SQLiteSession, set_tracing_disabled

        # 禁用 tracing：本地无 OpenAI 上传 key，默认 trace 上传会 401
        set_tracing_disabled(True)

        self._resolve_project_cwd(project_name)  # 项目名校验
        env = await self._load_env()

        api_key = env.get("OPENAI_API_KEY", "").strip()
        base_url = env.get("OPENAI_BASE_URL", "").strip()
        effective_model = model or env.get("OPENAI_MODEL", "").strip()

        protocol = normalize_protocol("openai", env.get("OPENAI_PROTOCOL"))
        provider = OpenAIProvider(
            api_key=api_key or None,
            base_url=base_url or None,
            use_responses=protocol == PROTOCOL_RESPONSES,
            strict_feature_validation=True,
        )

        from server.agent_runtime.sdk_tools import build_shotwise_agents_tools

        tools = build_shotwise_agents_tools(project_name=project_name, projects_root=self.projects_root)
        system_prompt = self._build_system_prompt(project_name, locale, [getattr(t, "name", "") for t in tools])
        session = SQLiteSession(session_id=session_id, db_path=str(self._session_db_path))
        if self._history_loader is not None and session_id:
            entries = await self._history_loader(session_id)
            await _hydrate_openai_session(session, session_id, entries, self._session_db_path)
        max_turns = self._max_turns_provider() if self._max_turns_provider else None

        return OpenAIAgentsBuildResult(
            provider=provider,
            model=effective_model,
            system_prompt=system_prompt,
            session=session,
            max_turns=max_turns,
            tools=tools,
        )

    async def _load_env(self) -> dict[str, str]:
        from lib.config.env_keys import ANTHROPIC_ENV_KEYS, OTHER_PROVIDER_ENV_KEYS
        from lib.config.service import build_openai_agents_env_dict
        from lib.db import async_session_factory

        loader = self._provider_env_loader
        if loader is not None:
            openai_env = await loader()
        else:
            async with async_session_factory() as session:
                openai_env = await build_openai_agents_env_dict(session)

        result: dict[str, str] = dict(openai_env)
        for key in (*ANTHROPIC_ENV_KEYS, *OTHER_PROVIDER_ENV_KEYS):
            result.setdefault(key, "")
        return result

    def _build_system_prompt(self, project_name: str, locale: str, tool_names: list[str]) -> str:
        lang = {"zh": "中文", "en": "英语", "vi": "越南语"}.get(locale, "中文")
        try:
            self._resolve_project_cwd(project_name)
            project_context = (
                "\n## 当前项目上下文\n"
                f"- 项目标识：{project_name}\n"
                "- 项目元数据位于 project.json，需要时使用 read_project_text 分页读取。\n"
            )
        except (ValueError, FileNotFoundError):
            project_context = ""
        return (
            f"{_OPENAI_PERSONA_PROMPT}\n"
            f"{PROJECT_DOCUMENT_WORKFLOW}\n"
            f"## 语言规范\n所有回复使用{lang}。\n"
            f"## 当前可用工具\n{', '.join(name for name in tool_names if name)}\n"
            "只可使用上述工具。"
            f"{project_context}"
        )


async def _hydrate_openai_session(session: Any, session_id: str, entries: list[dict[str, Any]], db_path: Path) -> None:
    """Import canonical user/assistant text once, tracking the event-log seq."""
    if not entries:
        return
    latest_seq = max(int(entry.get("seq", -1)) for entry in entries)
    marker = await asyncio.to_thread(_read_import_marker, db_path, session_id)
    if marker is not None and latest_seq <= marker:
        return
    items: list[dict[str, Any]] = []
    for entry in entries:
        seq = int(entry.get("seq", -1))
        if marker is not None and seq <= marker:
            continue
        role = entry.get("type")
        if role not in ("user", "assistant"):
            continue
        text = _entry_text(entry)
        if text:
            items.append({"role": role, "content": text})
    if items:
        await session.add_items(items)
    await asyncio.to_thread(_write_import_marker, db_path, session_id, latest_seq)


def _entry_text(entry: dict[str, Any]) -> str:
    content = entry.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(block.get("text")) for block in content if isinstance(block, dict) and block.get("text")]
        return "\n".join(parts).strip()
    return ""


def _read_import_marker(db_path: Path, session_id: str) -> int | None:
    with sqlite3.connect(str(db_path), timeout=30) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS shotwise_context_imports "
            "(session_id TEXT PRIMARY KEY, last_seq INTEGER NOT NULL)"
        )
        row = conn.execute(
            "SELECT last_seq FROM shotwise_context_imports WHERE session_id = ?", (session_id,)
        ).fetchone()
    return int(row[0]) if row is not None else None


def _write_import_marker(db_path: Path, session_id: str, last_seq: int) -> None:
    with sqlite3.connect(str(db_path), timeout=30) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS shotwise_context_imports "
            "(session_id TEXT PRIMARY KEY, last_seq INTEGER NOT NULL)"
        )
        conn.execute(
            "INSERT INTO shotwise_context_imports(session_id, last_seq) VALUES (?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET last_seq = excluded.last_seq",
            (session_id, last_seq),
        )
