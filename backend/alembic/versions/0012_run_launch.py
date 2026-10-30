"""запуск экспериментов из формы: шаблон, параметры, задача очереди, сообщение

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("template", sa.String(64), nullable=False, server_default=""))
    op.add_column("runs", sa.Column("config", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("runs", sa.Column("task_id", sa.String(64), nullable=False, server_default=""))
    op.add_column("runs", sa.Column("message", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    for column in ("message", "task_id", "config", "template"):
        op.drop_column("runs", column)
