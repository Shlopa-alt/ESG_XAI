"""предложения экспериментов от Qwen

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hypothesis_id", sa.Integer(), sa.ForeignKey("hypotheses.id"), nullable=False),
        sa.Column("qwen_job_id", sa.Integer(), sa.ForeignKey("qwen_jobs.id"), nullable=True),
        sa.Column("status", sa.Enum("proposed", "approved", "rejected", name="proposal_status", native_enum=False,
                                    length=16), nullable=False, server_default="proposed"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("method", sa.String(64), nullable=False, server_default=""),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("dataset_snapshots.id"), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("setup", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("expected", sa.Text(), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("problems", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id"), nullable=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_experiment_proposals_hypothesis_id", "experiment_proposals", ["hypothesis_id"])


def downgrade() -> None:
    op.drop_index("ix_experiment_proposals_hypothesis_id", table_name="experiment_proposals")
    op.drop_table("experiment_proposals")
