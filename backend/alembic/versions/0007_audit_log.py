"""журнал аудита

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("login", sa.String(128), nullable=False, server_default=""),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("client", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
