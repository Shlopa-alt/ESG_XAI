"""вес связи у гипотезы (1–3) и кто его поставил

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL — вес не указан (старые гипотезы и гипотезы Qwen)
    op.add_column("hypotheses", sa.Column("weight", sa.Integer(), nullable=True))
    op.add_column("hypotheses", sa.Column("weight_set_by", sa.Integer(),
                                          sa.ForeignKey("users.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("hypotheses", "weight_set_by")
    op.drop_column("hypotheses", "weight")
