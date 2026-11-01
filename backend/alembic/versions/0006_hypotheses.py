"""гипотезы и их опоры в базе знаний

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hypotheses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("direction", sa.String(32), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Enum("proposed", "accepted", "rejected", "testing", "tested", name="h_status",
                    native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("decision_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id"), nullable=True),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_hypotheses_code", "hypotheses", ["code"], unique=True)
    op.create_table(
        "hypothesis_refs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hypothesis_id", sa.Integer(), sa.ForeignKey("hypotheses.id"), nullable=False),
        sa.Column("kb_ref_id", sa.Integer(), sa.ForeignKey("kb_refs.id"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hypothesis_refs")
    op.drop_index("ix_hypotheses_code", table_name="hypotheses")
    op.drop_table("hypotheses")
