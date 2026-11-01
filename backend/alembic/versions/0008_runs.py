"""запуски экспериментов

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "done", "failed", "stopped", name="run_status",
                    native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("resource", sa.String(8), nullable=False, server_default="cpu"),
        sa.Column("runner_commit", sa.String(64), nullable=False, server_default=""),
        sa.Column("dataset_snapshot_id", sa.Integer(), sa.ForeignKey("dataset_snapshots.id"),
                  nullable=True),
        sa.Column("env_lock_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("python", sa.String(32), nullable=False, server_default=""),
        sa.Column("seeds", sa.JSON(), nullable=False),
        sa.Column("parts", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("results_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("mlflow_run_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("runs")
