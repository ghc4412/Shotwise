"""SQLite migration coverage for workflow persistence invariants."""

from __future__ import annotations

import logging.config
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

ROOT = Path(__file__).resolve().parents[1]
REVISION = "wf3_workflow_persistence"


@pytest.fixture
def alembic_cfg(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "workflow-persistence.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    real_file_config = logging.config.fileConfig
    monkeypatch.setattr(
        logging.config,
        "fileConfig",
        lambda *args, **kwargs: real_file_config(*args, **{**kwargs, "disable_existing_loggers": False}),
    )
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config, db_path


@pytest.mark.unit
def test_workflow_persistence_migration_is_reachable_from_alembic_heads() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(REVISION)
    assert revision is not None
    assert revision.revision in script.get_heads()
    assert revision.down_revision
    assert revision.module.__doc__


@pytest.mark.unit
def test_workflow_persistence_migration_applies_and_rolls_back_constraints(alembic_cfg) -> None:
    config, db_path = alembic_cfg
    command.upgrade(config, REVISION)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    expected_constraints = {
        "workflow_revisions": {
            "ck_workflow_revision_number_positive",
            "ck_workflow_revision_content_mode",
            "ck_workflow_revision_generation_mode",
            "ck_workflow_revision_graph_hash_nonempty",
            "ck_workflow_revision_execution_hash_nonempty",
        },
        "workflow_nodes": {
            "ck_workflow_node_weight_nonnegative",
            "ck_workflow_node_estimated_cost_nonnegative",
        },
        "workflow_runs": {
            "ck_workflow_run_budget_limit_nonnegative",
            "ck_workflow_run_spent_nonnegative",
            "ck_workflow_run_reserved_nonnegative",
            "ck_workflow_run_budget_not_exceeded",
        },
    }
    for table_name, constraint_names in expected_constraints.items():
        actual_names = {item["name"] for item in inspector.get_check_constraints(table_name)}
        assert constraint_names <= actual_names

    assert {"ix_workflow_definitions_user_id"} <= {
        index["name"] for index in inspector.get_indexes("workflow_definitions")
    }
    assert {"ix_workflow_runs_user_id"} <= {index["name"] for index in inspector.get_indexes("workflow_runs")}
    engine.dispose()

    command.downgrade(config, "p5_media_assets")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    for table_name, constraint_names in expected_constraints.items():
        actual_names = {item["name"] for item in inspector.get_check_constraints(table_name)}
        assert not constraint_names & actual_names
    assert "ix_workflow_definitions_user_id" not in {
        index["name"] for index in inspector.get_indexes("workflow_definitions")
    }
    assert "ix_workflow_runs_user_id" not in {index["name"] for index in inspector.get_indexes("workflow_runs")}
    engine.dispose()
