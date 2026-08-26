"""Shotwise workflow, execution and event-log ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, TimestampMixin, UserOwnedMixin


class WorkflowDefinition(UserOwnedMixin, TimestampMixin, Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="project")
    active_revision_id: Mapped[str | None] = mapped_column(String(36))


class WorkflowRevision(Base):
    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint("definition_id", "revision_no", name="uq_workflow_revision_number"),
        CheckConstraint("revision_no > 0", name="ck_workflow_revision_number_positive"),
        CheckConstraint(
            "content_mode IN ('drama', 'narration', 'ad', 'manga')",
            name="ck_workflow_revision_content_mode",
        ),
        CheckConstraint(
            "generation_mode IN ('storyboard', 'reference_video')",
            name="ck_workflow_revision_generation_mode",
        ),
        CheckConstraint("length(graph_hash) > 0", name="ck_workflow_revision_graph_hash_nonempty"),
        CheckConstraint("length(execution_hash) > 0", name="ck_workflow_revision_execution_hash_nonempty"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    definition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    content_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="drama")
    generation_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="storyboard")
    input_schema_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    template_lock_json: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"
    __table_args__ = (
        UniqueConstraint("revision_id", "node_key", name="uq_workflow_node_key"),
        CheckConstraint("weight >= 0", name="ck_workflow_node_weight_nonnegative"),
        CheckConstraint("estimated_cost >= 0", name="ck_workflow_node_estimated_cost_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    config_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ui_position_json: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    retry_policy_json: Mapped[str | None] = mapped_column(Text)
    approval_policy_json: Mapped[str | None] = mapped_column(Text)
    input_schema_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_schema_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    executor_id: Mapped[str] = mapped_column(String(128), nullable=False, default="builtin")
    required_capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cache_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="reuse")


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"
    __table_args__ = (UniqueConstraint("revision_id", "edge_key", name="uq_workflow_edge_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    edge_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    target_node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    condition_json: Mapped[str | None] = mapped_column(Text)
    on_failure: Mapped[str] = mapped_column(String(24), nullable=False, default="stop")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkflowRun(UserOwnedMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_project_status", "project_id", "status"),
        CheckConstraint("budget_limit IS NULL OR budget_limit >= 0", name="ck_workflow_run_budget_limit_nonnegative"),
        CheckConstraint("spent_amount >= 0", name="ck_workflow_run_spent_nonnegative"),
        CheckConstraint("reserved_amount >= 0", name="ck_workflow_run_reserved_nonnegative"),
        CheckConstraint(
            "budget_limit IS NULL OR spent_amount + reserved_amount <= budget_limit",
            name="ck_workflow_run_budget_not_exceeded",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_revisions.id"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    script_revision_id: Mapped[str | None] = mapped_column(String(128))
    episode_id: Mapped[str | None] = mapped_column(String(128), index=True)
    budget_limit: Mapped[float | None] = mapped_column(Float)
    spent_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reserved_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="planned")
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default="hybrid")
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    graph_snapshot_ref: Mapped[str | None] = mapped_column(String(200))
    input_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    progress: Mapped[float | None] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    control_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowNodeRun(Base):
    __tablename__ = "workflow_node_runs"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "node_key", "attempt_no", name="uq_workflow_node_run_attempt"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="blocked")
    input_hash: Mapped[str | None] = mapped_column(String(64))
    input_snapshot_json: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float | None] = mapped_column(Float)
    progress_source: Mapped[str | None] = mapped_column(String(32))
    phase_code: Mapped[str | None] = mapped_column(String(64))
    phase_params_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_params_json: Mapped[str | None] = mapped_column(Text)
    output_refs_json: Mapped[str | None] = mapped_column(Text)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowNodeRunItem(Base):
    __tablename__ = "workflow_node_run_items"
    __table_args__ = (UniqueConstraint("node_run_id", "item_key", name="uq_workflow_node_item_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_node_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_key: Mapped[str] = mapped_column(String(200), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    input_snapshot_json: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="blocked")
    current_attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lineage_hash: Mapped[str | None] = mapped_column(String(64))
    output_refs_json: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_params_json: Mapped[str | None] = mapped_column(Text)


class ExternalExecution(Base):
    __tablename__ = "external_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_account_id: Mapped[str | None] = mapped_column(String(128))
    endpoint_snapshot: Mapped[str | None] = mapped_column(Text)
    model_snapshot: Mapped[str | None] = mapped_column(Text)
    provider_job_id: Mapped[str | None] = mapped_column(String(256))
    provider_idempotency_key: Mapped[str | None] = mapped_column(String(256))
    submit_state: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared")
    remote_state: Mapped[str | None] = mapped_column(String(64))
    cancel_state: Mapped[str | None] = mapped_column(String(64))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    response_digest: Mapped[str | None] = mapped_column(String(64))
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowApproval(Base):
    __tablename__ = "workflow_approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workflow_node_runs.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    budget_limit: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowTemplate(UserOwnedMixin, TimestampMixin, Base):
    """Marketplace metadata for a creator-owned, reviewable workflow template."""

    __tablename__ = "workflow_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_ref: Mapped[str | None] = mapped_column(String(500))
    template_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    draft_revision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workflow_revisions.id"))
    published_revision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workflow_revisions.id"))
    contract_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowMarketplaceReview(Base):
    __tablename__ = "workflow_marketplace_reviews"
    __table_args__ = (Index("ix_workflow_marketplace_reviews_template_created", "template_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflow_revisions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowUsageStats(Base):
    __tablename__ = "workflow_usage_stats"

    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_templates.id", ondelete="CASCADE"), primary_key=True
    )
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    derivations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rating_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workflow_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_run_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workflow_node_runs.id", ondelete="CASCADE"))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    estimated_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    reserved_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    settled_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    price_catalog_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="reserved")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectEventLog(Base):
    __tablename__ = "project_event_log"
    __table_args__ = (Index("ix_project_event_log_project_seq", "project_id", "seq"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    causation_id: Mapped[str | None] = mapped_column(String(36))
    correlation_id: Mapped[str | None] = mapped_column(String(36))
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
