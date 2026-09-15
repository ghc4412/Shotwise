"""Schema contract tests for the final-render review and publishing migrations."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REVIEW_REVISION = "20260914_render_review_snapshots"
_PUBLISH_REVISION = "20260914_publish_jobs"
_ACCOUNTS_REVISION = "20260914_publishing_accounts"
_HEAD_REVISION = "20260914_publish_job_leases"
_PARENT_REVISION = "20260913_render_job_active_unique"


@pytest.fixture
def alembic_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, Path]:
    db_path = tmp_path / "p1-schema.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    cfg = Config()
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return cfg, db_path


def _inspect(db_path: Path) -> sa.Inspector:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        return sa.inspect(engine)
    finally:
        # Inspector keeps only dialect metadata needed by these assertions.
        engine.dispose()


def _table_columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {name for index in inspector.get_indexes(table_name) if (name := index["name"]) is not None}


def test_p1_migrations_create_publish_and_review_schema_and_round_trip(alembic_cfg) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")

    inspector = _inspect(db_path)
    assert _HEAD_REVISION == _current_revision(db_path)
    version_column = next(
        column for column in inspector.get_columns("alembic_version") if column["name"] == "version_num"
    )
    assert getattr(version_column["type"], "length", None) == 128
    assert {
        "render_review_snapshots",
        "publish_jobs",
        "publishing_accounts",
    }.issubset(set(inspector.get_table_names()))

    assert _table_columns(inspector, "render_review_snapshots") == {
        "id",
        "artifact_id",
        "plan_id",
        "project_name",
        "user_id",
        "revision_number",
        "source_fingerprint",
        "artifact_fingerprint",
        "status",
        "checks_json",
        "created_at",
        "confirmed_by",
        "confirmed_at",
    }
    assert {
        "id",
        "user_id",
        "plan_id",
        "project_name",
        "artifact_id",
        "review_snapshot_id",
        "account_id",
        "revision_number",
        "source_fingerprint",
        "artifact_fingerprint",
        "platform",
        "destination_json",
        "idempotency_key",
        "request_fingerprint",
        "status",
        "attempt",
        "max_attempts",
        "error_code",
        "error_message",
        "external_content_id",
        "external_status",
        "next_poll_at",
        "last_polled_at",
        "worker_id",
        "lease_until",
        "created_at",
        "started_at",
        "completed_at",
        "updated_at",
    } == _table_columns(inspector, "publish_jobs")
    assert {
        "ix_render_review_snapshots_artifact_id",
        "ix_render_review_snapshots_plan_id",
        "ix_render_review_snapshots_user_id",
        "ix_render_review_snapshots_artifact_created",
        "ix_render_review_snapshots_user_project",
    } == _index_names(inspector, "render_review_snapshots")
    assert {
        "ix_publish_jobs_status",
        "ix_publish_jobs_plan_id",
        "ix_publish_jobs_plan_revision",
        "ix_publish_jobs_artifact_id",
        "ix_publish_jobs_user_id",
        "ix_publish_jobs_user_status",
        "ix_publish_jobs_poll",
        "ix_publish_jobs_account_id",
        "ix_publish_jobs_lease",
    } == _index_names(inspector, "publish_jobs")

    review_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("render_review_snapshots")}
    publish_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("publish_jobs")}
    assert "render_artifacts" in review_fks
    assert {"assembly_plans", "render_artifacts", "publishing_accounts"}.issubset(publish_fks)

    command.downgrade(cfg, _PARENT_REVISION)
    inspector = _inspect(db_path)
    tables = set(inspector.get_table_names())
    assert "render_review_snapshots" not in tables
    assert "publish_jobs" not in tables
    assert "publishing_accounts" not in tables

    command.upgrade(cfg, "head")
    assert _current_revision(db_path) == _HEAD_REVISION


def _current_revision(db_path: Path) -> str | None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    finally:
        engine.dispose()
