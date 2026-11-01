"""CR от Qwen по одобренному отчёту: источник, отчёт, задача Qwen, замечания проверки

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("change_requests") as b:
        b.add_column(sa.Column("source", sa.String(16), nullable=False, server_default=""))
        b.add_column(sa.Column("report_id", sa.Integer(), sa.ForeignKey("experiment_reports.id"), nullable=True))
        b.add_column(sa.Column("qwen_job_id", sa.Integer(), sa.ForeignKey("qwen_jobs.id"), nullable=True))
        b.add_column(sa.Column("problems", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("change_requests") as b:
        b.drop_column("problems")
        b.drop_column("qwen_job_id")
        b.drop_column("report_id")
        b.drop_column("source")
