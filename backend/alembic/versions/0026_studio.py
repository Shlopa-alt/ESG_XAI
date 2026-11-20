"""Студия: сценарии SC-NN, их версии и расчёты

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def _now() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True, index=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        _now(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_table(
        "scenario_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("scenarios.id"), nullable=False,
                  index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("graph", sa.JSON(), nullable=False),
        sa.Column("saved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("scenario_id", "version"),
    )
    op.create_table(
        "studio_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("scenarios.id"), nullable=False,
                  index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("until", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        _now(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("views", sa.JSON(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("results_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("runner_commit", sa.String(64), nullable=False, server_default=""),
        sa.Column("env_lock_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("python", sa.String(32), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("studio_runs")
    op.drop_table("scenario_versions")
    op.drop_table("scenarios")
