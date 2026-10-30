"""Эксперименты, датасеты, ссылки на базу знаний KBRAG и рецензии (docs/SPEC.md, раздел 3)."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EXP_STATUSES = ("draft", "planned", "running", "review", "done", "failed")
EXP_OUTCOMES = ("confirmed", "rejected", "inconclusive")
KB_REF_KINDS = ("article", "fact", "entity")
LINK_RELATIONS = ("tests", "uses_method", "replicates", "motivated_by")
VERDICTS = ("approve", "changes", "reject")
ACCESS_LEVELS = ("public", "nda")


def _enum(values: tuple[str, ...], name: str) -> Enum:
    return Enum(*values, name=name, native_enum=False, length=16)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    license: Mapped[str] = mapped_column(String(256), default="")
    access_level: Mapped[str] = mapped_column(_enum(ACCESS_LEVELS, "access_level"), default="public")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetSnapshot(Base):
    __tablename__ = "dataset_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    version: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(1024), default="")
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbRef(Base):
    """Снимок того, на что сослались в KBRAG: статья, факт или сущность графа."""

    __tablename__ = "kb_refs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(_enum(KB_REF_KINDS, "kb_ref_kind"))
    kbrag_id: Mapped[str] = mapped_column(String(512))
    kb_path: Mapped[str] = mapped_column(String(256), default="")
    title: Mapped[str] = mapped_column(String(1024), default="")
    doi: Mapped[str] = mapped_column(String(256), default="")
    quote: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    direction: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(_enum(EXP_STATUSES, "exp_status"), default="draft")
    outcome: Mapped[str | None] = mapped_column(_enum(EXP_OUTCOMES, "exp_outcome"), nullable=True)
    method: Mapped[str] = mapped_column(String(512), default="")
    data_summary: Mapped[str] = mapped_column(String(512), default="")
    dataset_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_snapshots.id"), nullable=True
    )
    config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runner_commit: Mapped[str] = mapped_column(String(64), default="")
    env_lock: Mapped[str] = mapped_column(Text, default="")
    mlflow_run_id: Mapped[str] = mapped_column(String(64), default="")
    setup: Mapped[list[str]] = mapped_column(JSON, default=list)
    results: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    conclusion: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list)
    reproducibility: Mapped[list[str]] = mapped_column(JSON, default=list)
    report_path: Mapped[str] = mapped_column(String(512), default="")
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentLink(Base):
    __tablename__ = "experiment_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    kb_ref_id: Mapped[int] = mapped_column(ForeignKey("kb_refs.id"))
    relation: Mapped[str] = mapped_column(_enum(LINK_RELATIONS, "link_relation"))


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(16))  # experiment | cr
    target_id: Mapped[int] = mapped_column(Integer)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    verdict: Mapped[str] = mapped_column(_enum(VERDICTS, "verdict"))
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
