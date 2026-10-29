"""users

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("login", sa.String(128), nullable=False),
        sa.Column("full_name", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "reader",
                "researcher",
                "reviewer",
                "owner",
                name="user_role",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("nda_access", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_users_login", "users", ["login"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_login", table_name="users")
    op.drop_table("users")
