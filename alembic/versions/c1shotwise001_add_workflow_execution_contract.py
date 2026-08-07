"""add Shotwise workflow and execution contract tables

Revision ID: c1shotwise001
Revises: b7f2c41d9a30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1shotwise001"
down_revision: str | Sequence[str] | None = "b7f2c41d9a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps(table: str) -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="project"),
        sa.Column("active_revision_id", sa.String(36)),
        *_timestamps("workflow_definitions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workflow_definitions_workspace_id", "workflow_definitions", ["workspace_id"])
    op.create_index("ix_workflow_definitions_project_id", "workflow_definitions", ["project_id"])

    op.create_table(
        "workflow_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("definition_id", sa.String(36), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("graph_hash", sa.String(64), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("template_lock_json", sa.Text()),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("definition_id", "revision_no", name="uq_workflow_revision_number"),
    )
    op.create_index("ix_workflow_revisions_definition_id", "workflow_revisions", ["definition_id"])

    op.create_table(
        "workflow_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("node_key", sa.String(128), nullable=False),
        sa.Column("node_type", sa.String(128), nullable=False),
        sa.Column("node_type_version", sa.String(32), nullable=False, server_default="1"),
        sa.Column("config_schema_version", sa.String(32), nullable=False, server_default="1"),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("ui_position_json", sa.Text()),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("retry_policy_json", sa.Text()),
        sa.Column("approval_policy_json", sa.Text()),
        sa.ForeignKeyConstraint(["revision_id"], ["workflow_revisions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("revision_id", "node_key", name="uq_workflow_node_key"),
    )
    op.create_index("ix_workflow_nodes_revision_id", "workflow_nodes", ["revision_id"])

    op.create_table(
        "workflow_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("edge_key", sa.String(128), nullable=False),
        sa.Column("source_node_key", sa.String(128), nullable=False),
        sa.Column("target_node_key", sa.String(128), nullable=False),
        sa.Column("condition_json", sa.Text()),
        sa.Column("on_failure", sa.String(24), nullable=False, server_default="stop"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["revision_id"], ["workflow_revisions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("revision_id", "edge_key", name="uq_workflow_edge_key"),
    )
    op.create_index("ix_workflow_edges_revision_id", "workflow_edges", ["revision_id"])

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("workflow_revision_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("script_revision_id", sa.String(128)),
        sa.Column("status", sa.String(24), nullable=False, server_default="planned"),
        sa.Column("mode", sa.String(24), nullable=False, server_default="hybrid"),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("graph_snapshot_ref", sa.String(200)),
        sa.Column("input_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("progress", sa.Float()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("control_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_revision_id"], ["workflow_revisions.id"]),
    )
    op.create_index("ix_workflow_runs_workflow_revision_id", "workflow_runs", ["workflow_revision_id"])
    op.create_index("ix_workflow_runs_workspace_id", "workflow_runs", ["workspace_id"])
    op.create_index("ix_workflow_runs_project_id", "workflow_runs", ["project_id"])
    op.create_index("ix_workflow_runs_trace_id", "workflow_runs", ["trace_id"])
    op.create_index("ix_workflow_runs_input_fingerprint", "workflow_runs", ["input_fingerprint"])
    op.create_index("ix_workflow_runs_project_status", "workflow_runs", ["project_id", "status"])

    op.create_table(
        "workflow_node_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_run_id", sa.String(36), nullable=False),
        sa.Column("node_key", sa.String(128), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="blocked"),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("input_snapshot_json", sa.Text()),
        sa.Column("progress", sa.Float()),
        sa.Column("progress_source", sa.String(32)),
        sa.Column("phase_code", sa.String(64)),
        sa.Column("phase_params_json", sa.Text()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_params_json", sa.Text()),
        sa.Column("output_refs_json", sa.Text()),
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workflow_run_id", "node_key", "attempt_no", name="uq_workflow_node_run_attempt"),
    )
    op.create_index("ix_workflow_node_runs_workflow_run_id", "workflow_node_runs", ["workflow_run_id"])

    op.create_table(
        "workflow_node_run_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("node_run_id", sa.String(36), nullable=False),
        sa.Column("item_key", sa.String(200), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64)),
        sa.Column("input_snapshot_json", sa.Text()),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="blocked"),
        sa.Column("current_attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lineage_hash", sa.String(64)),
        sa.Column("output_refs_json", sa.Text()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_params_json", sa.Text()),
        sa.ForeignKeyConstraint(["node_run_id"], ["workflow_node_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("node_run_id", "item_key", name="uq_workflow_node_item_key"),
    )
    op.create_index("ix_workflow_node_run_items_node_run_id", "workflow_node_run_items", ["node_run_id"])

    op.create_table(
        "external_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), nullable=False, unique=True),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("provider_account_id", sa.String(128)),
        sa.Column("endpoint_snapshot", sa.Text()),
        sa.Column("model_snapshot", sa.Text()),
        sa.Column("provider_job_id", sa.String(256)),
        sa.Column("provider_idempotency_key", sa.String(256)),
        sa.Column("submit_state", sa.String(32), nullable=False, server_default="prepared"),
        sa.Column("remote_state", sa.String(64)),
        sa.Column("cancel_state", sa.String(64)),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("response_digest", sa.String(64)),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("last_polled_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"], ondelete="CASCADE"),
    )

    op.create_table(
        "workflow_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_run_id", sa.String(36), nullable=False),
        sa.Column("node_run_id", sa.String(36)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("execution_hash", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("budget_limit", sa.Float()),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(128), nullable=False),
        sa.Column("decided_by", sa.String(128)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_run_id"], ["workflow_node_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workflow_approvals_workflow_run_id", "workflow_approvals", ["workflow_run_id"])

    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("workflow_run_id", sa.String(36), nullable=False),
        sa.Column("node_run_id", sa.String(36)),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("estimated_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reserved_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("settled_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("price_catalog_version", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False, server_default="reserved"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_run_id"], ["workflow_node_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_budget_reservations_workspace_id", "budget_reservations", ["workspace_id"])
    op.create_index("ix_budget_reservations_workflow_run_id", "budget_reservations", ["workflow_run_id"])

    op.create_table(
        "project_event_log",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("causation_id", sa.String(36)),
        sa.Column("correlation_id", sa.String(36)),
        sa.Column("actor_type", sa.String(32), nullable=False, server_default="user"),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("trace_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_event_log_workspace_id", "project_event_log", ["workspace_id"])
    op.create_index("ix_project_event_log_project_id", "project_event_log", ["project_id"])
    op.create_index("ix_project_event_log_project_seq", "project_event_log", ["project_id", "seq"])

    with op.batch_alter_table("tasks") as batch:
        for name, column in (
            ("workflow_run_id", sa.Column("workflow_run_id", sa.String(36))),
            ("workflow_node_run_id", sa.Column("workflow_node_run_id", sa.String(36))),
            ("workflow_node_run_item_id", sa.Column("workflow_node_run_item_id", sa.String(36))),
            ("input_fingerprint", sa.Column("input_fingerprint", sa.String(64))),
            ("request_idempotency_key", sa.Column("request_idempotency_key", sa.String(256))),
            ("progress", sa.Column("progress", sa.Float())),
            ("progress_source", sa.Column("progress_source", sa.String(32))),
            ("phase_code", sa.Column("phase_code", sa.String(64))),
            ("lease_owner", sa.Column("lease_owner", sa.String(128))),
            ("lease_until", sa.Column("lease_until", sa.DateTime(timezone=True))),
            ("fencing_token", sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0")),
        ):
            batch.add_column(column)
            batch.create_index(f"ix_tasks_{name}", [name], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        for name in (
            "fencing_token",
            "lease_until",
            "lease_owner",
            "phase_code",
            "progress_source",
            "progress",
            "request_idempotency_key",
            "input_fingerprint",
            "workflow_node_run_item_id",
            "workflow_node_run_id",
            "workflow_run_id",
        ):
            batch.drop_index(f"ix_tasks_{name}")
            batch.drop_column(name)
    for table in (
        "project_event_log",
        "budget_reservations",
        "workflow_approvals",
        "external_executions",
        "workflow_node_run_items",
        "workflow_node_runs",
        "workflow_runs",
        "workflow_edges",
        "workflow_nodes",
        "workflow_revisions",
        "workflow_definitions",
    ):
        op.drop_table(table)
