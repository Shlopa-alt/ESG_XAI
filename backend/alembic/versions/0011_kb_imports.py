"""очередь импорта статей через сайт

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kb_path", sa.String(256), nullable=False),
        sa.Column("source", sa.String(8), nullable=False, server_default="file"),
        sa.Column("filename", sa.String(512), nullable=False, server_default=""),
        sa.Column("storage_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("bytes_len", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("doi", sa.String(256), nullable=False, server_default=""),
        sa.Column("title", sa.String(1024), nullable=False, server_default=""),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "status",
            sa.Enum("queued", "processing", "done", "duplicate", "failed", name="kb_import_status",
                    native_enum=False, length=16),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("doc_id", sa.String(512), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_kb_imports_sha256", "kb_imports", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_kb_imports_sha256", table_name="kb_imports")
    op.drop_table("kb_imports")
