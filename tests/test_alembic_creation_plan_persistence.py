"""SQLite migration coverage for persisted Creation Plan dependencies."""

from __future__ import annotations

import logging.config
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
P3_REVISION = "p3skill001"
P4_REVISION = "p4_creation_skill_workflow_binding"


@pytest.fixture
def alembic_cfg(tmp_path, monkeypatch):
    db_path = tmp_path / "creation-plans.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    real_file_config = logging.config.fileConfig
    monkeypatch.setattr(
        logging.config,
        "fileConfig",
        lambda *args, **kwargs: real_file_config(*args, **{**kwargs, "disable_existing_loggers": False}),
    )
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return cfg, db_path


def test_p4_preserves_unbound_history_and_enforces_published_binding(alembic_cfg):
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, P3_REVISION)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    metadata = sa.MetaData()
    metadata.reflect(bind=engine, only=("creation_skill_definitions", "creation_skill_versions"))
    definitions = metadata.tables["creation_skill_definitions"]
    versions = metadata.tables["creation_skill_versions"]
    frozen_at = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            definitions.insert().values(
                id="legacy-skill",
                slug="legacy-skill",
                official=True,
                active=True,
                created_at=frozen_at,
                updated_at=frozen_at,
            )
        )
        conn.execute(
            versions.insert().values(
                id="legacy-skill:v1",
                skill_id="legacy-skill",
                version=1,
                title="Legacy Skill",
                summary="Historical release",
                category="test",
                workflow_template_revision_alias="missing-revision",
                expected_outputs_json="[]",
                review_required=False,
                status="published",
                frozen_at=frozen_at,
            )
        )
    engine.dispose()

    command.upgrade(cfg, P4_REVISION)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        status, revision_id = conn.execute(
            sa.text("SELECT status, workflow_revision_id FROM creation_skill_versions WHERE id = 'legacy-skill:v1'")
        ).one()
        assert status == "legacy_unbound"
        assert revision_id is None

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text("UPDATE creation_skill_versions SET status = 'published' WHERE id = 'legacy-skill:v1'")
            )
    engine.dispose()
