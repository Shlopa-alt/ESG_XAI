"""Студия: одобренный владельцем код узлов «Python» (sha256 кода) у сценария

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenarios", sa.Column("approved_python", sa.JSON(), nullable=False,
                                         server_default=sa.text("'[]'")))


def downgrade() -> None:
    op.drop_column("scenarios", "approved_python")
