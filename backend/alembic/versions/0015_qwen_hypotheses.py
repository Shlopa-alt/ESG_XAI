"""гипотезы от Qwen: кто предложил, что предложено для проверки, из какой задачи

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hypotheses", sa.Column("source", sa.String(8), nullable=False, server_default="human"))
    op.add_column("hypotheses", sa.Column("suggested", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("hypotheses", sa.Column("qwen_job_id", sa.Integer(), sa.ForeignKey("qwen_jobs.id"), nullable=True))


def downgrade() -> None:
    for column in ("qwen_job_id", "suggested", "source"):
        op.drop_column("hypotheses", column)
