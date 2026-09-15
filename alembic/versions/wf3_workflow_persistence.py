"""Enforce workflow revision, node, and episode budget invariants."""

from alembic import op  # noqa: I001


revision = "wf3_workflow_persistence"
down_revision = "p5_media_assets"
branch_labels = None
depends_on = None


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _create_workflow_revision_checks() -> None:
    if _is_postgresql():
        op.create_check_constraint("ck_workflow_revision_number_positive", "workflow_revisions", "revision_no > 0")
        op.create_check_constraint(
            "ck_workflow_revision_content_mode",
            "workflow_revisions",
            "content_mode IN ('drama', 'narration', 'ad', 'manga')",
        )
        op.create_check_constraint(
            "ck_workflow_revision_generation_mode",
            "workflow_revisions",
            "generation_mode IN ('storyboard', 'reference_video')",
        )
        op.create_check_constraint(
            "ck_workflow_revision_graph_hash_nonempty",
            "workflow_revisions",
            "length(graph_hash) > 0",
        )
        op.create_check_constraint(
            "ck_workflow_revision_execution_hash_nonempty",
            "workflow_revisions",
            "length(execution_hash) > 0",
        )
        return

    with op.batch_alter_table("workflow_revisions", recreate="always") as batch:
        batch.create_check_constraint("ck_workflow_revision_number_positive", "revision_no > 0")
        batch.create_check_constraint(
            "ck_workflow_revision_content_mode",
            "content_mode IN ('drama', 'narration', 'ad', 'manga')",
        )
        batch.create_check_constraint(
            "ck_workflow_revision_generation_mode",
            "generation_mode IN ('storyboard', 'reference_video')",
        )
        batch.create_check_constraint("ck_workflow_revision_graph_hash_nonempty", "length(graph_hash) > 0")
        batch.create_check_constraint("ck_workflow_revision_execution_hash_nonempty", "length(execution_hash) > 0")


def _create_workflow_node_checks() -> None:
    if _is_postgresql():
        op.create_check_constraint("ck_workflow_node_weight_nonnegative", "workflow_nodes", "weight >= 0")
        op.create_check_constraint(
            "ck_workflow_node_estimated_cost_nonnegative",
            "workflow_nodes",
            "estimated_cost >= 0",
        )
        return

    with op.batch_alter_table("workflow_nodes", recreate="always") as batch:
        batch.create_check_constraint("ck_workflow_node_weight_nonnegative", "weight >= 0")
        batch.create_check_constraint("ck_workflow_node_estimated_cost_nonnegative", "estimated_cost >= 0")


def _create_workflow_run_checks() -> None:
    if _is_postgresql():
        op.create_check_constraint(
            "ck_workflow_run_budget_limit_nonnegative",
            "workflow_runs",
            "budget_limit IS NULL OR budget_limit >= 0",
        )
        op.create_check_constraint("ck_workflow_run_spent_nonnegative", "workflow_runs", "spent_amount >= 0")
        op.create_check_constraint("ck_workflow_run_reserved_nonnegative", "workflow_runs", "reserved_amount >= 0")
        op.create_check_constraint(
            "ck_workflow_run_budget_not_exceeded",
            "workflow_runs",
            "budget_limit IS NULL OR spent_amount + reserved_amount <= budget_limit",
        )
        return

    with op.batch_alter_table("workflow_runs", recreate="always") as batch:
        batch.create_check_constraint(
            "ck_workflow_run_budget_limit_nonnegative",
            "budget_limit IS NULL OR budget_limit >= 0",
        )
        batch.create_check_constraint("ck_workflow_run_spent_nonnegative", "spent_amount >= 0")
        batch.create_check_constraint("ck_workflow_run_reserved_nonnegative", "reserved_amount >= 0")
        batch.create_check_constraint(
            "ck_workflow_run_budget_not_exceeded",
            "budget_limit IS NULL OR spent_amount + reserved_amount <= budget_limit",
        )


def _drop_workflow_revision_checks() -> None:
    if _is_postgresql():
        for name in (
            "ck_workflow_revision_execution_hash_nonempty",
            "ck_workflow_revision_graph_hash_nonempty",
            "ck_workflow_revision_generation_mode",
            "ck_workflow_revision_content_mode",
            "ck_workflow_revision_number_positive",
        ):
            op.drop_constraint(name, "workflow_revisions", type_="check")
        return

    with op.batch_alter_table("workflow_revisions", recreate="always") as batch:
        batch.drop_constraint("ck_workflow_revision_execution_hash_nonempty", type_="check")
        batch.drop_constraint("ck_workflow_revision_graph_hash_nonempty", type_="check")
        batch.drop_constraint("ck_workflow_revision_generation_mode", type_="check")
        batch.drop_constraint("ck_workflow_revision_content_mode", type_="check")
        batch.drop_constraint("ck_workflow_revision_number_positive", type_="check")


def _drop_workflow_node_checks() -> None:
    if _is_postgresql():
        op.drop_constraint("ck_workflow_node_estimated_cost_nonnegative", "workflow_nodes", type_="check")
        op.drop_constraint("ck_workflow_node_weight_nonnegative", "workflow_nodes", type_="check")
        return

    with op.batch_alter_table("workflow_nodes", recreate="always") as batch:
        batch.drop_constraint("ck_workflow_node_estimated_cost_nonnegative", type_="check")
        batch.drop_constraint("ck_workflow_node_weight_nonnegative", type_="check")


def _drop_workflow_run_checks() -> None:
    if _is_postgresql():
        op.drop_constraint("ck_workflow_run_budget_not_exceeded", "workflow_runs", type_="check")
        op.drop_constraint("ck_workflow_run_reserved_nonnegative", "workflow_runs", type_="check")
        op.drop_constraint("ck_workflow_run_spent_nonnegative", "workflow_runs", type_="check")
        op.drop_constraint("ck_workflow_run_budget_limit_nonnegative", "workflow_runs", type_="check")
        return

    with op.batch_alter_table("workflow_runs", recreate="always") as batch:
        batch.drop_constraint("ck_workflow_run_budget_not_exceeded", type_="check")
        batch.drop_constraint("ck_workflow_run_reserved_nonnegative", type_="check")
        batch.drop_constraint("ck_workflow_run_spent_nonnegative", type_="check")
        batch.drop_constraint("ck_workflow_run_budget_limit_nonnegative", type_="check")


def upgrade() -> None:
    op.create_index("ix_workflow_definitions_user_id", "workflow_definitions", ["user_id"])
    op.create_index("ix_workflow_runs_user_id", "workflow_runs", ["user_id"])
    _create_workflow_revision_checks()
    _create_workflow_node_checks()
    _create_workflow_run_checks()


def downgrade() -> None:
    _drop_workflow_run_checks()
    _drop_workflow_node_checks()
    _drop_workflow_revision_checks()
    op.drop_index("ix_workflow_runs_user_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_definitions_user_id", table_name="workflow_definitions")
