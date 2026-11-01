"""очередь задач Qwen по требованию

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qwen_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.Enum("queued", "running", "done", "failed", "cancelled", name="qwen_job_status",
                                    native_enum=False, length=16), nullable=False, server_default="queued"),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_qwen_jobs_status", "qwen_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_qwen_jobs_status", table_name="qwen_jobs")
    op.drop_table("qwen_jobs")
