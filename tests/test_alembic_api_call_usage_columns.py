"""Alembic 迁移：api_calls 的使用记录列（加列 + 从任务载荷反查 task_id 的回填）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

pytestmark = pytest.mark.unit

_REVISION = "20260918_api_call_usage_columns"
_PARENT = "20260914_publish_job_leases"
_NEW_COLUMNS = {"task_id", "purpose", "session_id", "inputs", "error_code", "error_params"}

_INSERT_TASK = (
    "INSERT INTO tasks (task_id, user_id, project_name, task_type, media_type, resource_id, status, "
    "source, payload_json, queued_at, updated_at) VALUES "
    "(:task_id, :user_id, 'demo', :task_type, :media_type, 'E1S01', 'succeeded', 'webui', "
    ":payload_json, '2026-09-01 00:00:00', '2026-09-01 00:00:00')"
)
_INSERT_CALL = (
    "INSERT INTO api_calls (id, user_id, project_name, call_type, model, status, started_at, "
    "created_at, updated_at) VALUES "
    "(:id, :user_id, 'demo', :call_type, 'veo-3.1-generate-preview', 'success', "
    "'2026-09-01 00:00:00', '2026-09-01 00:00:00', '2026-09-01 00:00:00')"
)
_INSERT_USER = (
    "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
    "VALUES (:id, :username, 'user', 1, '2026-09-01 00:00:00', '2026-09-01 00:00:00')"
)


@pytest.fixture
def alembic_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, Path]:
    repo_root = Path(__file__).resolve().parent.parent
    cfg = Config()  # 不传 ini 路径 → config_file_name=None → env.py 跳过 fileConfig
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    db_path = tmp_path / "api-call-usage.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    return cfg, db_path


def _columns(engine: sa.Engine) -> set[str]:
    with engine.begin() as connection:
        return {row[1] for row in connection.execute(sa.text("PRAGMA table_info(api_calls)"))}


def _indexes(engine: sa.Engine) -> set[str]:
    with engine.begin() as connection:
        return {row[1] for row in connection.execute(sa.text("PRAGMA index_list('api_calls')"))}


def _row(engine: sa.Engine, call_id: int) -> tuple[object, ...]:
    with engine.begin() as connection:
        row = connection.execute(
            sa.text(
                "SELECT task_id, purpose, session_id, inputs, error_code, error_params FROM api_calls WHERE id = :id"
            ),
            {"id": call_id},
        ).fetchone()
    assert row is not None
    return tuple(row)


def _seed(engine: sa.Engine) -> None:
    """覆盖能精确反查与必须跳过的历史载荷形态。"""
    with engine.begin() as connection:
        connection.execute(sa.text(_INSERT_USER), {"id": "other", "username": "other"})
        for call_id in range(1, 10):
            connection.execute(sa.text(_INSERT_CALL), {"id": call_id, "user_id": "default", "call_type": "video"})

        tasks = (
            # 唯一应被回填的一条：video + int api_call_id + user 匹配
            ("T-match", "default", "video", "video", '{"api_call_id": 1, "duration": 8}'),
            # 同一 call_id 但任务属于另一个用户：不得跨用户写归属
            ("T-other-user", "other", "video", "video", '{"api_call_id": 2}'),
            # 非 video 任务不反查
            ("T-image", "default", "image", "image", '{"api_call_id": 3}'),
            # 非法 JSON / 顶层非对象 / 布尔 / 字符串 / 浮点 / 嵌套对象：全部跳过
            ("T-malformed", "default", "video", "video", "{not json"),
            ("T-bool", "default", "video", "video", '{"api_call_id": true}'),
            ("T-string", "default", "video", "video", '{"api_call_id": "6"}'),
            ("T-float", "default", "video", "video", '{"api_call_id": 7.0}'),
            ("T-list", "default", "video", "video", "[1, 2]"),
            ("T-nested", "default", "video", "video", '{"meta": {"api_call_id": 9}}'),
        )
        for task_id, user_id, task_type, media_type, payload_json in tasks:
            connection.execute(
                sa.text(_INSERT_TASK),
                {
                    "task_id": task_id,
                    "user_id": user_id,
                    "task_type": task_type,
                    "media_type": media_type,
                    "payload_json": payload_json,
                },
            )


def test_upgrade_adds_columns_and_backfills_only_own_video_task_id(alembic_cfg: tuple[Config, Path]) -> None:
    config, db_path = alembic_cfg
    command.upgrade(config, _PARENT)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        assert not _NEW_COLUMNS & _columns(engine)
        _seed(engine)

        command.upgrade(config, _REVISION)

        assert _columns(engine) >= _NEW_COLUMNS
        assert "idx_api_calls_task_id" in _indexes(engine)
        assert _row(engine, 1) == ("T-match", "generation_task", None, None, None, None)
        for call_id in range(2, 10):
            assert _row(engine, call_id) == (None, None, None, None, None, None), f"call {call_id} 不应被回填"
    finally:
        engine.dispose()


def test_downgrade_drops_columns_then_upgrade_round_trips(alembic_cfg: tuple[Config, Path]) -> None:
    config, db_path = alembic_cfg
    command.upgrade(config, _REVISION)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        command.downgrade(config, _PARENT)

        assert not _NEW_COLUMNS & _columns(engine)
        assert "idx_api_calls_task_id" not in _indexes(engine)
        # 同表既有索引不因批式重建而丢失
        assert _indexes(engine) >= {"idx_api_calls_project_name", "idx_api_calls_status"}

        command.upgrade(config, _REVISION)

        assert _columns(engine) >= _NEW_COLUMNS
        assert "idx_api_calls_task_id" in _indexes(engine)
    finally:
        engine.dispose()
