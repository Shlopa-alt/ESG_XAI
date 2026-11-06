"""черновики датасетов из таблиц статей KBRAG

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doc_id", sa.String(512), nullable=False),
        sa.Column("kb_path", sa.String(256), nullable=False, server_default="esg"),
        sa.Column("article_title", sa.String(1024), nullable=False, server_default=""),
        sa.Column("doi", sa.String(256), nullable=False, server_default=""),
        sa.Column("table_number", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("columns", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rows", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("history", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.Enum("proposed", "approved", "rejected", name="data_draft_status",
                                    native_enum=False, length=16),
                  nullable=False, server_default="proposed"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("qwen_job_id", sa.Integer(), sa.ForeignKey("qwen_jobs.id"), nullable=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id"), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_data_drafts_doc_id", "data_drafts", ["doc_id"])


def downgrade() -> None:
    op.drop_index("ix_data_drafts_doc_id", table_name="data_drafts")
    op.drop_table("data_drafts")
