"""Студия: подключения к внешним базам данных (пароль — шифротекстом) и публикация сценария
как веб-сервиса

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "db_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False, unique=True, index=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("host", sa.String(256), nullable=False, server_default=""),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("database", sa.String(256), nullable=False, server_default=""),
        sa.Column("username", sa.String(256), nullable=False, server_default=""),
        sa.Column("password_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("allow_write", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.add_column("scenarios", sa.Column("published_version", sa.Integer(), nullable=True))
    op.add_column("scenarios", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scenarios", sa.Column("published_by", sa.Integer(), sa.ForeignKey("users.id"),
                                         nullable=True))


def downgrade() -> None:
    op.drop_column("scenarios", "published_by")
    op.drop_column("scenarios", "published_at")
    op.drop_column("scenarios", "published_version")
    op.drop_table("db_connections")
