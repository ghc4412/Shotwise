"""Alembic 迁移：custom_provider.image_request_timeout_seconds 列与正数 CHECK。"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

pytestmark = pytest.mark.unit

_COL = "image_request_timeout_seconds"


@pytest.fixture
def alembic_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """指向项目 alembic 脚本，DB 用临时 sqlite（env.py 经 DATABASE_URL 读取）。"""
    repo_root = Path(__file__).resolve().parent.parent
    cfg = Config()
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    cfg.attributes["_test_db_path"] = str(db_path)
    return cfg


@pytest.fixture
def revisions() -> tuple[str, str]:
    """读出加列迁移的 (revision, down_revision)。"""
    repo_root = Path(__file__).resolve().parent.parent
    versions_dir = repo_root / "alembic" / "versions"
    matches = list(versions_dir.glob("*_custom_provider_image_request_timeout.py"))
    assert len(matches) == 1, f"找到 {len(matches)} 个迁移文件，期望 1"
    text = matches[0].read_text()
    revision: str | None = None
    down_revision: str | None = None
    for line in text.splitlines():
        if line.startswith("revision: str ="):
            revision = line.split("=")[1].strip().strip('"').strip("'")
        elif line.startswith("down_revision:"):
            down_revision = line.split("=")[1].strip().strip('"').strip("'")
    if not revision or not down_revision:
        raise RuntimeError("未在迁移文件中找到 revision / down_revision")
    return revision, down_revision


def _columns(engine: sa.Engine) -> set[str]:
    with engine.begin() as conn:
        rows = conn.execute(sa.text("PRAGMA table_info(custom_provider)")).fetchall()
    return {r[1] for r in rows}


def _insert(engine: sa.Engine, *, row_id: int, timeout: float | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO custom_provider "
                "(id, display_name, discovery_format, base_url, api_key, "
                "image_request_timeout_seconds, created_at, updated_at) "
                "VALUES (:id, 'P', 'openai', 'https://x', 'k', :t, "
                "'2026-06-29 00:00:00', '2026-06-29 00:00:00')"
            ),
            {"id": row_id, "t": timeout},
        )


def test_upgrade_adds_column_existing_row_null(alembic_cfg: Config, revisions: tuple[str, str]):
    """升到加列前插一行，升级后列存在且该行为 NULL（零回归）。"""
    revision_id, parent_id = revisions
    command.upgrade(alembic_cfg, parent_id)

    db_path = alembic_cfg.attributes["_test_db_path"]
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        assert _COL not in _columns(engine), "加列前不应存在请求超时列"
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO custom_provider "
                    "(id, display_name, discovery_format, base_url, api_key, created_at, updated_at) "
                    "VALUES (1, 'P', 'openai', 'https://x', 'k', "
                    "'2026-06-29 00:00:00', '2026-06-29 00:00:00')"
                )
            )

        command.upgrade(alembic_cfg, revision_id)

        assert _COL in _columns(engine)
        with engine.begin() as conn:
            value = conn.execute(sa.text(f"SELECT {_COL} FROM custom_provider WHERE id = 1")).scalar_one()
        assert value is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("bad_value", [-1, 0])
def test_upgrade_rejects_non_positive_timeout(alembic_cfg: Config, revisions: tuple[str, str], bad_value: int):
    """升级后 CHECK 约束拒绝 0/负值；NULL 与正数（含小数）仍合法。"""
    revision_id, _ = revisions
    command.upgrade(alembic_cfg, revision_id)

    db_path = alembic_cfg.attributes["_test_db_path"]
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        # 失败写入放在非自动提交连接里，约束触发即回滚，不污染后续断言
        with engine.connect() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO custom_provider "
                    "(id, display_name, discovery_format, base_url, api_key, "
                    f"{_COL}, created_at, updated_at) "
                    f"VALUES (1, 'P', 'openai', 'https://x', 'k', {bad_value}, "
                    "'2026-06-29 00:00:00', '2026-06-29 00:00:00')"
                )
            )
        _insert(engine, row_id=2, timeout=None)
        _insert(engine, row_id=3, timeout=0.5)
        with engine.begin() as conn:
            null_value = conn.execute(sa.text(f"SELECT {_COL} FROM custom_provider WHERE id = 2")).scalar_one()
            frac_value = conn.execute(sa.text(f"SELECT {_COL} FROM custom_provider WHERE id = 3")).scalar_one()
        assert null_value is None
        assert frac_value == 0.5
    finally:
        engine.dispose()


def test_downgrade_drops_column(alembic_cfg: Config, revisions: tuple[str, str]):
    """downgrade 回退后列消失，其余数据保留。"""
    revision_id, parent_id = revisions
    command.upgrade(alembic_cfg, revision_id)

    db_path = alembic_cfg.attributes["_test_db_path"]
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        _insert(engine, row_id=1, timeout=30.0)

        command.downgrade(alembic_cfg, parent_id)

        assert _COL not in _columns(engine)
        with engine.begin() as conn:
            name = conn.execute(sa.text("SELECT display_name FROM custom_provider WHERE id = 1")).scalar_one()
        assert name == "P"
    finally:
        engine.dispose()
