"""черновики данных по ссылкам из статей: источник данных, скачанный файл, предложение статьи

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
    with op.batch_alter_table("data_drafts") as b:
        # table — таблица статьи (задача tables), link — данные по ссылке из статьи (задача data_links)
        b.add_column(sa.Column("source_kind", sa.String(16), nullable=False, server_default="table"))
        b.add_column(sa.Column("source_url", sa.String(2048), nullable=False, server_default=""))
        b.add_column(sa.Column("link_context", sa.Text(), nullable=False, server_default=""))
        b.add_column(sa.Column("file_url", sa.String(2048), nullable=False, server_default=""))
        b.add_column(sa.Column("file_name", sa.String(512), nullable=False, server_default=""))
        b.add_column(sa.Column("file_path", sa.String(1024), nullable=False, server_default=""))
        b.add_column(sa.Column("file_sha256", sa.String(64), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("data_drafts") as b:
        for name in ("file_sha256", "file_path", "file_name", "file_url", "link_context", "source_url",
                     "source_kind"):
            b.drop_column(name)
