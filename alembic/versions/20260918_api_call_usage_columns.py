"""api_calls 增加用量记录上下文与失败分类列。

给 ``api_calls`` 补上回溯来源所需的 task_id / purpose / session_id / inputs，以及失败分类的
error_code / error_params。历史 video 任务的调用行按 ``tasks.payload_json.api_call_id`` 反查回填，
回填同时校验 user_id，避免跨用户写错归属。

Revision ID: 20260918_api_call_usage_columns
Revises: 20260914_publish_job_leases
Create Date: 2026-09-18 10:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260918_api_call_usage_columns"
down_revision: str | Sequence[str] | None = "20260914_publish_job_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_COLUMNS = ("task_id", "purpose", "session_id", "inputs", "error_code", "error_params")
_TASK_ID_INDEX = "idx_api_calls_task_id"


def _backfill_task_id_from_task_payload() -> None:
    """把历史 video 任务的 ``payload_json.api_call_id`` 反向写成 ``api_calls.task_id``。

    ``payload_json`` 是 Text 列（两种方言上都不是原生 JSON 类型），解析放在 Python 侧。
    回填只做能精确得到的：反查到的行同时标记 ``purpose = generation_task``，其余新列留空。
    更新条件带 ``user_id``，跨用户的行即使 id 撞上也不动。
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT task_id, user_id, payload_json FROM tasks WHERE media_type = 'video' AND payload_json IS NOT NULL"
        )
    ).fetchall()

    updates: list[dict[str, object]] = []
    for task_id, user_id, payload_json in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        call_id = payload.get("api_call_id")
        # bool 是 int 的子类，单独排除，避免把 payload 里的布尔值当成行号。
        if isinstance(call_id, bool) or not isinstance(call_id, int):
            continue
        updates.append({"call_id": call_id, "task_id": task_id, "user_id": user_id})

    if updates:
        bind.execute(
            sa.text(
                "UPDATE api_calls SET task_id = :task_id, purpose = 'generation_task' "
                "WHERE id = :call_id AND user_id = :user_id"
            ),
            updates,
        )


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("api_calls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("purpose", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("session_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("inputs", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("error_code", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("error_params", sa.JSON(), nullable=True))
        batch_op.create_index(_TASK_ID_INDEX, ["task_id"], unique=False)

    _backfill_task_id_from_task_payload()


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("api_calls", schema=None) as batch_op:
        batch_op.drop_index(_TASK_ID_INDEX)
        for column in reversed(_NEW_COLUMNS):
            batch_op.drop_column(column)
