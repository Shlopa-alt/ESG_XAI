"""библиотека методов из статей банка: код модели (Qwen), проверка, включение администратором

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True, index=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("net", sa.String(32), nullable=False, server_default=""),
        sa.Column("task", sa.String(32), nullable=False, server_default="predict"),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ready"),
        sa.Column("check_log", sa.Text(), nullable=False, server_default=""),
        sa.Column("fit_s", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fit_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limit_min", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("doc_id", sa.String(512), nullable=False, server_default="", index=True),
        sa.Column("article_title", sa.String(1024), nullable=False, server_default=""),
        sa.Column("doi", sa.String(256), nullable=False, server_default=""),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("qwen_job_id", sa.Integer(), sa.ForeignKey("qwen_jobs.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("methods")
