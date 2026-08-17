from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from server.agent_runtime.openai_agents_options import OpenAIAgentsOptionsAssembler, _hydrate_openai_session


class _FakeSession:
    def __init__(self, items: list[dict[str, Any]] | None = None) -> None:
        self.items = list(items or [])

    async def get_items(self) -> list[dict[str, Any]]:
        return list(self.items)

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        self.items.extend(items)


@pytest.mark.unit
async def test_hydrate_openai_session_imports_user_assistant_text_once(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    entries = [
        {"seq": 1, "type": "user", "content": [{"type": "text", "text": "分析章节"}]},
        {"seq": 2, "type": "assistant", "content": [{"type": "text", "text": "已开始分析"}]},
        {"seq": 3, "type": "system", "content": [{"type": "text", "text": "skip"}]},
    ]
    session = _FakeSession()

    await _hydrate_openai_session(session, "session-1", entries, db_path)
    await _hydrate_openai_session(session, "session-1", entries, db_path)

    await _hydrate_openai_session(
        session,
        "session-1",
        entries + [{"seq": 4, "type": "user", "content": [{"type": "text", "text": "继续"}]}],
        db_path,
    )

    assert session.items == [
        {"role": "user", "content": "分析章节"},
        {"role": "assistant", "content": "已开始分析"},
        {"role": "user", "content": "继续"},
    ]


@pytest.mark.unit
async def test_hydrate_openai_session_preserves_repeated_messages(tmp_path: Path) -> None:
    session = _FakeSession()

    await _hydrate_openai_session(
        session,
        "session-repeated",
        [
            {"seq": 1, "type": "user", "content": "继续"},
            {"seq": 2, "type": "assistant", "content": "已继续"},
            {"seq": 3, "type": "user", "content": "继续"},
        ],
        tmp_path / "sessions.db",
    )

    assert session.items == [
        {"role": "user", "content": "继续"},
        {"role": "assistant", "content": "已继续"},
        {"role": "user", "content": "继续"},
    ]


@pytest.mark.unit
def test_openai_prompt_is_independent_from_claude_tool_instructions(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    assembler = OpenAIAgentsOptionsAssembler(
        projects_root=tmp_path,
        resolve_project_cwd=lambda _name: project,
    )

    prompt = assembler._build_system_prompt("demo", "zh", ["patch_project", "read_project_text"])

    assert "只能调用系统实际提供的工具" in prompt
    assert "read_project_text" in prompt
    assert "Bash 命令必须写在单行" not in prompt
    assert "Write/Edit 不要写入代码文件" not in prompt
