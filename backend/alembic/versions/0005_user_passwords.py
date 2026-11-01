"""личные пароли: хеш, требование сменить временный, блокировка

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(256), nullable=False,
                                     server_default=""))
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False,
                                     server_default=sa.true()))


def downgrade() -> None:
    for col in ("is_active", "must_change_password", "password_hash"):
        op.drop_column("users", col)
