"""эксперименты, датасеты, ссылки на KBRAG, рецензии

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=16)


def _now() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("license", sa.String(256), nullable=False, server_default=""),
        sa.Column("access_level", _enum("public", "nda", name="access_level"), nullable=False),
        _now(),
    )
    op.create_index("ix_datasets_code", "datasets", ["code"], unique=True)
    op.create_table(
        "dataset_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("row_count", sa.Integer(), nullable=True),
        _now(),
    )
    op.create_table(
        "kb_refs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", _enum("article", "fact", "entity", name="kb_ref_kind"), nullable=False),
        sa.Column("kbrag_id", sa.String(512), nullable=False),
        sa.Column("kb_path", sa.String(256), nullable=False, server_default=""),
        sa.Column("title", sa.String(1024), nullable=False, server_default=""),
        sa.Column("doi", sa.String(256), nullable=False, server_default=""),
        sa.Column("quote", sa.Text(), nullable=False, server_default=""),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False, server_default=""),
        sa.Column("direction", sa.String(32), nullable=False, server_default=""),
        sa.Column(
            "status",
            _enum("draft", "planned", "running", "review", "done", "failed", name="exp_status"),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            _enum("confirmed", "rejected", "inconclusive", name="exp_outcome"),
            nullable=True,
        ),
        sa.Column("method", sa.String(512), nullable=False, server_default=""),
        sa.Column("data_summary", sa.String(512), nullable=False, server_default=""),
        sa.Column(
            "dataset_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("dataset_snapshots.id"),
            nullable=True,
        ),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("runner_commit", sa.String(64), nullable=False, server_default=""),
        sa.Column("env_lock", sa.Text(), nullable=False, server_default=""),
        sa.Column("mlflow_run_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("setup", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("conclusion", sa.Text(), nullable=False, server_default=""),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("reproducibility", sa.JSON(), nullable=False),
        sa.Column("report_path", sa.String(512), nullable=False, server_default=""),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        _now(),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_experiments_code", "experiments", ["code"], unique=True)
    op.create_table(
        "experiment_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("kb_ref_id", sa.Integer(), sa.ForeignKey("kb_refs.id"), nullable=False),
        sa.Column(
            "relation",
            _enum("tests", "uses_method", "replicates", "motivated_by", name="link_relation"),
            nullable=False,
        ),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("verdict", _enum("approve", "changes", "reject", name="verdict"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        _now(),
    )


def downgrade() -> None:
    for table in ("reviews", "experiment_links", "experiments", "kb_refs", "dataset_snapshots"):
        op.drop_table(table)
    op.drop_index("ix_datasets_code", table_name="datasets")
    op.drop_table("datasets")
