"""Bind frozen Creation Skill releases to concrete Workflow Revisions."""

import sqlalchemy as sa

from alembic import op

revision = "p4_creation_skill_workflow_binding"
down_revision = "p3skill001"
branch_labels = None
depends_on = None


_PUBLISHED_BINDING_CHECK = (
    "status <> 'published' OR (workflow_revision_id IS NOT NULL AND length(trim(workflow_revision_id)) > 0)"
)


def _repair_existing_bindings() -> None:
    """Repair resolvable legacy bindings before enforcing published-row validity."""

    bind = op.get_bind()
    metadata = sa.MetaData()
    skill_versions = sa.Table("creation_skill_versions", metadata, autoload_with=bind)
    workflow_revisions = sa.Table("workflow_revisions", metadata, autoload_with=bind)
    rows = (
        bind.execute(
            sa.select(
                skill_versions.c.id,
                skill_versions.c.workflow_template_revision_alias,
                skill_versions.c.status,
            ).where(skill_versions.c.workflow_revision_id.is_(None))
        )
        .mappings()
        .all()
    )

    for row in rows:
        version_id = str(row["id"])
        alias = str(row["workflow_template_revision_alias"] or "").strip()
        predicates = [workflow_revisions.c.id == version_id]
        if alias:
            predicates.extend(
                (
                    workflow_revisions.c.id == alias,
                    workflow_revisions.c.template_lock_json.like(f"%{version_id}%"),
                    workflow_revisions.c.template_lock_json.like(f"%{alias}%"),
                )
            )
        candidates = (
            bind.execute(
                sa.select(workflow_revisions.c.id)
                .where(workflow_revisions.c.status == "published")
                .where(sa.or_(*predicates))
            )
            .scalars()
            .all()
        )

        if len(candidates) == 1:
            bind.execute(
                skill_versions.update()
                .where(skill_versions.c.id == version_id)
                .values(workflow_revision_id=candidates[0])
            )
        elif len(candidates) > 1:
            raise RuntimeError(
                "Ambiguous published Workflow Revisions for CreationSkillVersion "
                f"{version_id}: {sorted(str(candidate) for candidate in candidates)}"
            )
        elif row["status"] == "published":
            # Preserve the historical row without inventing an executable workflow.
            bind.execute(
                skill_versions.update().where(skill_versions.c.id == version_id).values(status="legacy_unbound")
            )


def upgrade() -> None:
    with op.batch_alter_table("creation_skill_versions") as batch_op:
        batch_op.add_column(sa.Column("workflow_revision_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_creation_skill_versions_workflow_revision",
            "workflow_revisions",
            ["workflow_revision_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    _repair_existing_bindings()

    with op.batch_alter_table("creation_skill_versions") as batch_op:
        batch_op.create_check_constraint(
            "ck_creation_skill_version_published_workflow_revision",
            _PUBLISHED_BINDING_CHECK,
        )


def downgrade() -> None:
    with op.batch_alter_table("creation_skill_versions") as batch_op:
        batch_op.drop_constraint("ck_creation_skill_version_published_workflow_revision", type_="check")
        batch_op.drop_constraint("fk_creation_skill_versions_workflow_revision", type_="foreignkey")
        batch_op.drop_column("workflow_revision_id")
