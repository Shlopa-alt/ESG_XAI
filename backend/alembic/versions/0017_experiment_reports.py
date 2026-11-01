"""отчёты по экспериментам: факты расчёта, текст Qwen, рецензия, база знаний

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Enum("draft", "review", "approved", "rejected", name="report_status",
                                    native_enum=False, length=16), nullable=False, server_default="draft"),
        sa.Column("facts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("sections", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("problems", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("qwen_job_id", sa.Integer(), sa.ForeignKey("qwen_jobs.id"), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("kb_import_id", sa.Integer(), sa.ForeignKey("kb_imports.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_experiment_reports_experiment_id", "experiment_reports", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_experiment_reports_experiment_id", table_name="experiment_reports")
    op.drop_table("experiment_reports")
