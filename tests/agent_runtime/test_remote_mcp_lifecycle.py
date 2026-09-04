"""Remote MCP resource ownership across session startup and teardown."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from server.agent_runtime.session_manager import AgentStartupError, ManagedSession, SessionManager
from server.agent_runtime.session_store import SessionMetaStore
from tests.factories import make_session_meta

pytestmark = pytest.mark.unit


def _manager(tmp_path: Path) -> SessionManager:
    root = tmp_path / "repo"
    (root / "projects" / "demo").mkdir(parents=True)
    (root / "projects" / "demo" / "project.json").write_text(
        '{"title": "demo"}',
        encoding="utf-8",
    )
    return SessionManager(root, SessionMetaStore())


@pytest.mark.asyncio
async def test_actor_startup_failure_closes_remote_mcp_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    cleanup = AsyncMock()

    class _FailingActor:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def start(self) -> None:
            raise RuntimeError("connect failed")

    monkeypatch.setattr(SessionManager, "_ensure_capacity", AsyncMock(return_value=None))
    monkeypatch.setattr(
        manager,
        "_build_client_factory",
        AsyncMock(return_value=(lambda: None, "claude", cleanup)),
    )
    monkeypatch.setattr("server.agent_runtime.session_manager.SessionActor", _FailingActor)

    with pytest.raises(AgentStartupError, match="connect failed"):
        await manager.send_new_session("demo", "hello")

    cleanup.assert_awaited_once_with()
    assert manager.sessions == {}


@pytest.mark.asyncio
async def test_actor_construction_failure_closes_remote_mcp_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    cleanup = AsyncMock()

    class _FailingActor:
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("actor construction failed")

    monkeypatch.setattr(SessionManager, "_ensure_capacity", AsyncMock(return_value=None))
    monkeypatch.setattr(
        manager,
        "_build_client_factory",
        AsyncMock(return_value=(lambda: None, "claude", cleanup)),
    )
    monkeypatch.setattr("server.agent_runtime.session_manager.SessionActor", _FailingActor)

    with pytest.raises(AgentStartupError, match="actor construction failed"):
        await manager.send_new_session("demo", "hello")

    cleanup.assert_awaited_once_with()
    assert manager.sessions == {}


@pytest.mark.asyncio
async def test_resumed_session_startup_failure_closes_remote_mcp_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    cleanup = AsyncMock()

    class _FailingActor:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def start(self) -> None:
            raise RuntimeError("resume failed")

    monkeypatch.setattr(SessionManager, "_ensure_capacity", AsyncMock(return_value=None))
    monkeypatch.setattr(
        manager,
        "_build_client_factory",
        AsyncMock(return_value=(lambda: None, "claude", cleanup)),
    )
    monkeypatch.setattr("server.agent_runtime.session_manager.SessionActor", _FailingActor)
    meta = make_session_meta(id="resumed-session", project_name="demo", status="idle")

    with pytest.raises(AgentStartupError, match="resume failed"):
        await manager.get_or_connect(meta.id, meta=meta)

    cleanup.assert_awaited_once_with()
    assert manager.sessions == {}


@pytest.mark.asyncio
async def test_normal_session_close_releases_remote_mcp_resources_once(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    cleanup = AsyncMock()

    class _Actor:
        async def enqueue(self, command) -> None:
            command.complete()

        async def wait(self) -> None:
            return None

    managed = ManagedSession(
        session_id="session-1",
        actor=_Actor(),  # type: ignore[arg-type]
        status="idle",
        project_name="demo",
    )
    managed._cleanup = cleanup
    manager.sessions[managed.session_id] = managed

    await manager.close_session(managed.session_id)
    await manager.close_session(managed.session_id)

    cleanup.assert_awaited_once_with()
    assert managed._cleanup is None
    assert manager.sessions == {}
