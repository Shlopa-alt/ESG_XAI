"""тип связи у гипотезы: как влияет и на какие показатели

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # пусто — тип связи не указан (старые гипотезы и гипотезы Qwen)
    op.add_column("hypotheses", sa.Column("effect", sa.String(16), nullable=False, server_default=""))
    op.add_column("hypotheses",
                  sa.Column("target_kind", sa.String(16), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("hypotheses", "target_kind")
    op.drop_column("hypotheses", "effect")
