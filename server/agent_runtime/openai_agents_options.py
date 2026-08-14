"""OpenAI Agents SDK 的 options 装配：Agent / provider / SQLiteSession。

与 ``options_assembler.OptionsAssembler``（Claude 通道）对应。产出
``OpenAIAgentsBuildResult``，由 SessionManager 交给 ``OpenAIAgentsSessionClient``
消费。

会话续接：Agents SDK 的会话历史由 ``SQLiteSession`` 按 ``session_id`` 持久化
到本地 SQLite 文件（``projects_root/.openai_agents_sessions.db``），续接时用
相同 ``session_id`` 即自动恢复历史——因此 OpenAI 通道不需要在 agent_sessions 表
存额外的 SDK 会话 id，直接复用对外 ``sdk_session_id``。

认证：OpenAI 兼容端点（DeepSeek / Kimi / GLM 等）走 Chat Completions API，
经 ``OpenAIProvider(api_key, base_url, use_responses=False)`` 注入 active
credential（``build_openai_agents_env_dict``）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.i18n import DEFAULT_LOCALE

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
    ) -> None:
        self.projects_root = Path(projects_root)
        self._resolve_project_cwd = resolve_project_cwd
        self._prompt_builder = prompt_builder
        self._provider_env_loader = provider_env_loader
        self._max_turns_provider = max_turns_provider
        self._session_db_path = session_db_path or (self.projects_root / ".openai_agents_sessions.db")

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

        provider = OpenAIProvider(
            api_key=api_key or None,
            base_url=base_url or None,
            use_responses=False,  # Chat Completions 兼容端点（国内供应商不支持 Responses）
        )

        from server.agent_runtime.sdk_tools import build_shotwise_agents_tools

        tools = build_shotwise_agents_tools(project_name=project_name, projects_root=self.projects_root)
        system_prompt = self._build_system_prompt(project_name, locale)
        session = SQLiteSession(session_id=session_id, db_path=str(self._session_db_path))
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

    def _build_system_prompt(self, project_name: str, locale: str) -> str:
        if self._prompt_builder is not None:
            return self._prompt_builder(project_name, locale)
        return ""
